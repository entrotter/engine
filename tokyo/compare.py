#!/usr/bin/env python3
"""New Tokyo implementation: owned Anvil + read-only archive proxy + same-root trials."""
import argparse
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import resource
import signal
import socket
import subprocess
import threading
import time
import urllib.request

WETH = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2'
USDC = '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48'
ROUTER = '0xE592427A0AEce92De3Edee1F18E0157C05861564'
FACTORY = '0x1F98431c8aD98523631AE4a59f267346ea31F984'
ACTOR = '0x000000000000000000000000000000000000bEEF'
READS = frozenset({'eth_chainId', 'eth_blockNumber', 'eth_getBlockByNumber',
                  'eth_getBlockByHash', 'eth_getBalance', 'eth_getTransactionCount',
                  'eth_getCode', 'eth_getStorageAt', 'eth_call', 'eth_getProof',
                  'eth_getTransactionReceipt', 'eth_getTransactionByHash'})
LIMIT = 2_000_000

class Failure(Exception):
    pass


def rpc(url, method, params=()):
    req = urllib.request.Request(url, json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':list(params)}).encode(), {'Content-Type':'application/json','User-Agent':'Entrotter-Tokyo/0.1'})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read(LIMIT+1)
        if len(raw)>LIMIT:
            raise Failure('RPC response exceeded size limit')
        reply=json.loads(raw)
    except Exception:
        raise Failure('RPC unavailable or invalid response (endpoint redacted)') from None
    if 'error' in reply:
        raise Failure('RPC method failed: '+method+' code='+str(reply['error'].get('code')))
    if 'result' not in reply:
        raise Failure('RPC missing result')
    return reply['result']


def upstream(url, method, params=()):
    if method not in READS:
        raise Failure('Upstream write or unknown method refused')
    return rpc(url, method, params)


@contextmanager
def read_proxy(url):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<65536:
                    raise Failure('request bound')
                req=json.loads(self.rfile.read(size))
                value=upstream(url,req['method'],req.get('params',[]))
                result={'jsonrpc':'2.0','id':req.get('id'),'result':value}
            except Exception:
                result={'jsonrpc':'2.0','id':None,'error':{'code':-32000,'message':'Read proxy refused or archive unavailable'}}
            body=json.dumps(result).encode()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    server.daemon_threads=True
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def units(value,decimals):
    if not isinstance(decimals,int) or not 0<=decimals<=18 or not isinstance(value,str) or not re.fullmatch(r'\d+(\.\d+)?',value):
        raise Failure('Invalid decimal amount or decimals')
    try:
        n=Decimal(value)*10**decimals
        if not n.is_finite() or n<=0 or n!=n.to_integral_value() or n>=2**128:
            raise Failure('Amount must be positive, exact and bounded')
        return int(n)
    except InvalidOperation:
        raise Failure('Invalid amount') from None


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def pin(url,block,expected=None):
    if upstream(url,'eth_chainId')!='0x1':
        raise Failure('Expected Ethereum chain 1')
    b=upstream(url,'eth_getBlockByNumber',[hex(block),False])
    if not b or int(b['number'],16)!=block or not re.fullmatch('0x[0-9a-fA-F]{64}',b['hash']):
        raise Failure('Invalid pinned block')
    if expected and b['hash'].lower()!=expected.lower():
        raise Failure('Pinned block hash mismatch')
    return {'chainId':1,'blockNumber':block,'blockHash':b['hash'],'stateRoot':b['stateRoot'],'timestamp':int(b['timestamp'],16)}


def limits():
    resource.setrlimit(resource.RLIMIT_CPU,(150,150))
    resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
    resource.setrlimit(resource.RLIMIT_FSIZE,(8_000_000,8_000_000))


@contextmanager
def node(anvil,url,block):
    with socket.socket() as s:
        s.bind(('127.0.0.1',0)); port=s.getsockname()[1]
    # No secret RPC URL reaches Anvil's process arguments or logs.
    proc=subprocess.Popen([anvil,'--host','127.0.0.1','--port',str(port),'--fork-url',url,'--fork-block-number',str(block),'--no-storage-caching','--silent','--accounts','0'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,preexec_fn=limits)
    local=f'http://127.0.0.1:{port}'
    timer=threading.Timer(180,lambda: proc.kill() if proc.poll() is None else None); timer.start()
    try:
        for _ in range(150):
            if proc.poll() is not None:
                raise Failure('Anvil exited before readiness')
            try:
                rpc(local,'web3_clientVersion'); break
            except Failure:
                time.sleep(.1)
        else:
            raise Failure('Anvil readiness timeout')
        yield local,proc.pid
    finally:
        timer.cancel()
        if proc.poll() is None:
            proc.terminate()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill(); proc.wait(timeout=3)


def calldata(cast,signature,*args):
    r=subprocess.run([cast,'calldata',signature,*map(str,args)],capture_output=True,text=True,timeout=10)
    if r.returncode or len(r.stdout)>8192:
        raise Failure('ABI encoding failed')
    return r.stdout.strip()


def call(local,to,data):
    return rpc(local,'eth_call',[{'to':to,'data':data},'latest'])


def send(local,to,data,value=0):
    tx={'from':ACTOR,'to':to,'data':data,'value':hex(value),'gas':hex(500000),'gasPrice':hex(2_000_000_000)}
    h=rpc(local,'eth_sendTransaction',[tx])
    for _ in range(100):
        r=rpc(local,'eth_getTransactionReceipt',[h])
        if r:
            return {'transaction':tx,'receipt':r}
        time.sleep(.05)
    raise Failure('Receipt timeout')


def balances(local,cast):
    data=calldata(cast,'balanceOf(address)',ACTOR)
    return {'ETH':str(int(rpc(local,'eth_getBalance',[ACTOR,'latest']),16)),
            'WETH':str(int(call(local,WETH,data),16)), 'USDC':str(int(call(local,USDC,data),16))}


def observe(local,cast,pool):
    return {'balances':balances(local,cast),
            'nonce':rpc(local,'eth_getTransactionCount',[ACTOR,'latest']),
            'allowance':call(local,WETH,calldata(cast,'allowance(address,address)',ACTOR,ROUTER)),
            'poolSlot0':call(local,pool,calldata(cast,'slot0()')),
            'poolLiquidity':call(local,pool,calldata(cast,'liquidity()'))}


def decision(status,amount,output,gas,minimum,max_spend,max_gas):
    if status=='hold': return 'HOLD','No transaction: balances unchanged and zero execution gas.'
    if status=='revert': return 'HOLD','Minimum-output trial reverted. Token balances unchanged; execution gas was spent.'
    reasons=[]
    if amount>max_spend: reasons.append('input exceeds the user spending cap')
    if output<minimum: reasons.append('output is below the user minimum')
    if gas>max_gas: reasons.append('gas exceeds the user cap')
    return ('HOLD','; '.join(reasons)+'.') if reasons else ('PROCEED','Measured output, input and gas meet the stated constraints on this fork.')


def run(args):
    amount=units(args.amount,18); max_spend=units(args.max_spend,18); rate=units(args.min_rate,6)
    if amount>10*10**18 or max_spend>10*10**18 or not 21000<=args.max_gas<=500000:
        raise Failure('Input out of demo bounds')
    versions={}
    for name,path in [('anvil',args.anvil),('cast',args.cast)]:
        version=subprocess.check_output([path,'--version'],text=True,timeout=5)
        if 'Version: 1.8.3\n' not in version: raise Failure('Foundry 1.8.3 required')
        versions[name]=version.strip()
    url=os.environ.get('TOKYO_RPC_URL','https://eth.drpc.org')
    if not url.startswith('https://'): raise Failure('HTTPS archive endpoint required')
    source=pin(url,args.block,args.block_hash)
    started=time.monotonic()
    with read_proxy(url) as proxy, node(args.anvil,proxy,args.block) as (local,pid):
        if rpc(local,'eth_getBlockByNumber',[hex(args.block),False])['hash']!=source['blockHash']:
            raise Failure('Local fork pin mismatch')
        for address in [WETH,USDC,ROUTER,FACTORY]:
            if call_code:=rpc(local,'eth_getCode',[address,'latest']):
                if call_code=='0x': raise Failure('Missing contract code')
            else: raise Failure('Missing contract code')
        for token,expected in [(WETH,18),(USDC,6)]:
            if int(call(local,token,calldata(args.cast,'decimals()')),16)!=expected:
                raise Failure('Token decimals mismatch')
        pool_raw=call(local,FACTORY,calldata(args.cast,'getPool(address,address,uint24)',WETH,USDC,3000))
        pool='0x'+pool_raw[-40:]
        if int(pool,16)==0: raise Failure('Missing Uniswap pool')
        rpc(local,'anvil_setBalance',[ACTOR,hex(100*10**18)])
        rpc(local,'anvil_impersonateAccount',[ACTOR])
        rpc(local,'anvil_setNextBlockBaseFeePerGas',['0x0'])
        rpc(local,'evm_setNextBlockTimestamp',[source['timestamp']+1])
        setup=[send(local,WETH,calldata(args.cast,'deposit()'),amount)]
        rpc(local,'evm_setNextBlockTimestamp',[source['timestamp']+2])
        setup.append(send(local,WETH,calldata(args.cast,'approve(address,uint256)',ROUTER,amount)))
        if any(x['receipt']['status']!='0x1' for x in setup): raise Failure('Funding/approval setup failed')
        initial=balances(local,args.cast)
        observation=observe(local,args.cast,pool)
        fingerprint=digest(observation)
        baseline=rpc(local,'eth_getBlockByNumber',['latest',False])
        root=baseline['stateRoot']; snap=rpc(local,'evm_snapshot')
        trials=[]
        alternatives=[('proposed',amount,amount*rate//10**18),('reduced',min(amount//2,max_spend),min(amount//2,max_spend)*rate//10**18),('strict-minimum',amount,10**18),('hold',0,0)]
        for name,spend,minimum in alternatives:
            if not rpc(local,'evm_revert',[snap]): raise Failure('Snapshot restore failed')
            snap=rpc(local,'evm_snapshot')
            before=balances(local,args.cast)
            restored=rpc(local,'eth_getBlockByNumber',['latest',False])
            if before!=initial or restored['stateRoot']!=root or restored['hash']!=baseline['hash'] or observe(local,args.cast,pool)!=observation:
                raise Failure('Alternative did not start from identical state')
            rpc(local,'evm_setNextBlockTimestamp',[int(baseline['timestamp'],16)+1])
            rpc(local,'anvil_setNextBlockBaseFeePerGas',['0x0'])
            result=None; gas=0; fee=0; status='hold'
            if name!='hold':
                params=f'({WETH},{USDC},3000,{ACTOR},{int(baseline["timestamp"],16)+300},{spend},{minimum},0)'
                data=calldata(args.cast,'exactInputSingle((address,address,uint24,address,uint256,uint256,uint256,uint160))',params)
                result=send(local,ROUTER,data)
                receipt=result['receipt']; status='success' if receipt['status']=='0x1' else 'revert'
                gas=int(receipt['gasUsed'],16); fee=gas*int(receipt['effectiveGasPrice'],16)
            after=balances(local,args.cast)
            delta={k:str(int(after[k])-int(before[k])) for k in before}
            verdict,reason=decision(status,spend,int(delta['USDC']),gas,minimum,max_spend,args.max_gas)
            trials.append({'id':name,'amountIn':str(spend),'minimumOut':str(minimum),'status':status,'initialStateRoot':root,'initialObservation':observation,'initialStateFingerprint':fingerprint,'initialBlockHash':baseline['hash'],'before':before,'after':after,'delta':delta,'gasUsed':gas,'gasCostWei':str(fee),'execution':result,'verdict':verdict,'reason':reason})
    report={'format':'tokyo-compare/1','mode':'archived-state-local-execution','source':source,'contracts':{'router':ROUTER,'factory':FACTORY,'pool':pool,'WETH':WETH,'USDC':USDC},'decimals':{'ETH':18,'WETH':18,'USDC':6},'constraints':{'amountIn':str(amount),'maxSpend':str(max_spend),'minRateUSDCPerWETH':str(rate),'maxGas':args.max_gas},'setup':setup,'overrides':{'actor':ACTOR,'nativeFundingWei':str(100*10**18),'wrappedWei':str(amount),'approvalWei':str(amount),'gasPriceWei':'2000000000','nextBaseFeeWei':'0','timestamp':'same baseline timestamp + 1 per branch'},'tools':versions,'runtimeSeconds':round(time.monotonic()-started,3),'nodePid':pid,'nodeCleanedUp':True,'trials':trials,'limitations':['Archived state, not historical transaction replay or future prediction.','Artificial local funding and impersonation. Setup gas is separate from trial gas.','Token deltas are not portfolio profit. No price, MEV or gas forecast.','Serial snapshot isolation in one owned node; no concurrent branch sessions.', 'Anvil local block stateRoot is zero/uncomputed; equality is enforced by snapshot restore and observed balances, nonce, allowance, pool slot0 and liquidity, not a local Merkle proof.','Deterministic user constraints, not an AI trading recommendation.']}
    envelope={'report':report,'sha256':digest(report)}
    Path(args.output).write_text(json.dumps(envelope,indent=2)+'\n')
    print(json.dumps({'output':args.output,'hash':envelope['sha256'],'runtimeSeconds':report['runtimeSeconds'],'outcomes':[{k:t[k] for k in ['id','status','gasUsed','delta','verdict']} for t in trials]}))
    return envelope


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--anvil',default='anvil'); p.add_argument('--cast',default='cast')
    p.add_argument('--block',type=int,default=23000000); p.add_argument('--block-hash')
    p.add_argument('--amount',default='0.2'); p.add_argument('--max-spend',default='0.1'); p.add_argument('--min-rate',default='2000'); p.add_argument('--max-gas',type=int,default=200000)
    p.add_argument('--output',default='report.json'); args=p.parse_args()
    def stop(*_): raise Failure('Execution interrupted; owned resources cleaned up')
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGALRM,stop); signal.alarm(240)
    try: run(args)
    except (Failure,OSError,subprocess.SubprocessError) as e:
        print('FAILED: '+str(e) if isinstance(e,Failure) else 'FAILED: local tool unavailable or failed',file=__import__('sys').stderr); raise SystemExit(1)
    finally: signal.alarm(0)

if __name__=='__main__': main()
