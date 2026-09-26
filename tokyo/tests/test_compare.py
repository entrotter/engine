import json
from pathlib import Path
import unittest
from unittest.mock import patch
import compare

class Validation(unittest.TestCase):
    def test_amounts(self):
        self.assertEqual(compare.units('0.1',18),10**17)
        self.assertEqual(compare.units('1.000001',6),1000001)
        for value in ['0','-1','NaN','Infinity','1e10','0.0000001','1; echo bad','1 '*100]:
            with self.subTest(value=value),self.assertRaises(compare.Failure): compare.units(value,6)
        for decimals in [-1,19,'18']:
            with self.assertRaises(compare.Failure): compare.units('1',decimals)
    def test_writes_never_reach_upstream(self):
        with patch('compare.rpc') as rpc:
            for method in ['eth_sendTransaction','eth_sendRawTransaction','anvil_setBalance','evm_snapshot','personal_unlockAccount','unknown']:
                with self.assertRaises(compare.Failure):compare.upstream('https://example.org',method)
            rpc.assert_not_called()
    def test_wrong_chain(self):
        with patch('compare.upstream',return_value='0x2'),self.assertRaisesRegex(compare.Failure,'chain'):compare.pin('unused',23000000)
    def test_wrong_hash(self):
        with patch('compare.upstream',side_effect=['0x1',{'number':hex(23000000),'hash':'0x'+'a'*64}]),self.assertRaisesRegex(compare.Failure,'hash mismatch'):compare.pin('unused',23000000,'0x'+'b'*64)
    def test_missing_block(self):
        with patch('compare.upstream',side_effect=['0x1',None]),self.assertRaisesRegex(compare.Failure,'Invalid pinned'):compare.pin('unused',23000000)
    def test_rpc_failure_redacts_endpoint(self):
        with patch('urllib.request.urlopen',side_effect=OSError('https://secret.example/key')):
            with self.assertRaises(compare.Failure) as e: compare.rpc('https://secret.example/key','eth_chainId')
        self.assertNotIn('secret',str(e.exception))
    def test_policy(self):
        self.assertEqual(compare.decision('success',2,50,100,40,1,200)[0],'HOLD')
        self.assertEqual(compare.decision('success',1,50,100,40,1,200)[0],'PROCEED')
        self.assertEqual(compare.decision('success',1,50,201,40,1,200)[0],'HOLD')
        self.assertEqual(compare.decision('success',1,39,100,40,1,200)[0],'HOLD')
        self.assertEqual(compare.decision('revert',1,0,100,40,1,200)[0],'HOLD')
        self.assertEqual(compare.decision('hold',0,0,0,0,1,200)[0],'HOLD')
    def test_recorded_receipts(self):
        r=json.loads((Path(__file__).resolve().parents[1] / 'evidence/example.json').read_text())['report']
        self.assertEqual([t['status'] for t in r['trials']],['success','success','revert','hold'])
        self.assertEqual(len({t['initialStateRoot'] for t in r['trials']}),1)
        for t in r['trials']:
            for k in ['ETH','WETH','USDC']:
                self.assertEqual(int(t['after'][k])-int(t['before'][k]),int(t['delta'][k]))
            self.assertEqual(int(t['delta']['ETH']),-int(t['gasCostWei']))
            if t['execution']:
                receipt=t['execution']['receipt']
                self.assertEqual(int(receipt['gasUsed'],16),t['gasUsed'])
                self.assertEqual(int(receipt['effectiveGasPrice'],16)*t['gasUsed'],int(t['gasCostWei']))

if __name__=='__main__': unittest.main()
