"""Paired private Anvil branches. Historical-state execution, NOT future market replay."""
from __future__ import annotations
import os
import shutil
import socket
import subprocess
import time
from .rpc import RPC, RPCError, RPCRejected
from .artifact import VERSION, seal

class ExecutionError(RuntimeError):
    pass

class AnvilSession:
    def __init__(self, source: dict | None = None, rpc_url: str | None = None):
        self.source, self.rpc_url, self.process = source, rpc_url, None
        self.rpc = None

    def __enter__(self):
        binary = shutil.which("anvil")
        if not binary:
            raise ExecutionError("Anvil is not installed. Install Foundry, then retry. No fallback simulation was used.")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        args = [binary, "--host", "127.0.0.1", "--port", str(port), "--chain-id", "31337",
                "--no-mining", "--silent"]
        if self.source:
            args += ["--fork-url", self.rpc_url, "--fork-block-number", str(self.source["block_number"])]
        else:
            args += ["--timestamp", "1700000000", "--hardfork", "cancun"]
        self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL, start_new_session=True)
        self.rpc = RPC(f"http://127.0.0.1:{port}", local=True, timeout=10)
        deadline = time.monotonic() + 25
        try:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise ExecutionError("Anvil exited at startup. Check version, port and archive RPC settings.")
                try:
                    version = str(self.rpc.call("web3_clientVersion"))
                    if "anvil" not in version.lower() or self.rpc.call("eth_chainId") != hex(31337):
                        raise ExecutionError("Local RPC identity or chain ID did not match Anvil")
                    self.version = version
                    return self
                except RPCError:
                    time.sleep(.1)
            raise ExecutionError("Anvil startup timed out")
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exc):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

def resolve_source(scenario: dict) -> tuple[dict | None, str | None]:
    if scenario["mode"] == "evm-local":
        return None, None
    url = os.environ.get("ENTROTTER_RPC_URL")
    if not url:
        raise ExecutionError("Set ENTROTTER_RPC_URL to an archive-capable RPC. No fork was performed.")
    rpc = RPC(url)
    spec = scenario["source"]
    if int(rpc.call("eth_chainId"), 16) != spec["chain_id"]:
        raise ExecutionError("Upstream chain ID differs from the scenario")
    block = rpc.call("eth_getBlockByNumber", [hex(spec["block_number"]), False])
    if not block or int(block["number"], 16) != spec["block_number"]:
        raise ExecutionError("Requested historical block is unavailable")
    if "block_hash" in spec and block["hash"].lower() != spec["block_hash"].lower():
        raise ExecutionError("Pinned block hash does not match provider; possible wrong source or reorg")
    return {"chain_id": spec["chain_id"], "block_number": spec["block_number"],
            "block_hash": block["hash"], "timestamp": int(block["timestamp"], 16)}, url

def run_branch(scenario: dict, branch: str, source: dict | None, url: str | None) -> dict:
    deadline = time.monotonic() + 120
    with AnvilSession(source, url) as session:
        rpc = session.rpc
        head = rpc.call("eth_getBlockByNumber", ["latest", False])
        if source and (head["hash"].lower() != source["block_hash"].lower()):
            raise ExecutionError("Fork head does not match the resolved source block")
        timestamp, start_block = int(head["timestamp"], 16), int(head["number"], 16)
        actor = scenario["actor"].lower()
        rpc.call("anvil_setBalance", [actor, hex(int(scenario["actor_balance_wei"]))])
        for addr, code in scenario.get("local_contracts", {}).items():
            rpc.call("anvil_setCode", [addr, code])
        rpc.call("anvil_impersonateAccount", [actor])
        initial = int(rpc.call("eth_getBalance", [actor, "latest"]), 16)
        receipts, total_gas, failed, rejected = [], 0, 0, 0
        for i, slot in enumerate(scenario["steps"]):
            if time.monotonic() > deadline:
                raise ExecutionError("Execution budget exceeded")
            action = slot[branch]
            record = {"step": i, "action": action, "status": "noop", "gas_used": "0"}
            rpc.call("evm_setNextBlockTimestamp", [timestamp + 12*(i+1)])
            tx_hash = None
            if action is not None:
                tx = {"from": actor, "to": action["to"], "value": hex(int(action.get("value_wei", "0"))),
                      "data": action.get("data", "0x"), "gas": hex(action.get("gas", 21000))}
                try:
                    tx_hash = rpc.call("eth_sendTransaction", [tx])
                except RPCRejected:
                    record["status"] = "rejected"
                    rejected += 1
            rpc.call("evm_mine")
            if tx_hash is not None:
                receipt = rpc.call("eth_getTransactionReceipt", [tx_hash])
                if receipt is None:
                    raise ExecutionError("No receipt after mining; refusing a partial success report")
                ok = int(receipt["status"], 16) == 1
                used = int(receipt["gasUsed"], 16)
                total_gas += used
                failed += int(not ok)
                record.update({"status": "success" if ok else "reverted", "gas_used": str(used),
                               "transaction_hash": tx_hash, "receipt": receipt})
            record["actor_balance_wei"] = str(int(rpc.call("eth_getBalance", [actor, "latest"]), 16))
            receipts.append(record)
        final = int(rpc.call("eth_getBalance", [actor, "latest"]), 16)
        rpc.call("anvil_stopImpersonatingAccount", [actor])
        return {"tool_version": session.version, "start_block": start_block,
                "start_timestamp": timestamp, "trace": receipts,
                "metrics": {"initial_balance_wei": str(initial), "final_balance_wei": str(final),
                            "balance_delta_wei": str(final-initial), "gas_used": str(total_gas),
                            "reverted_transactions": failed, "rejected_transactions": rejected}}

def run_evm(scenario: dict) -> dict:
    source, url = resolve_source(scenario)
    baseline = run_branch(scenario, "baseline", source, url)
    candidate = run_branch(scenario, "candidate", source, url)
    return seal({"schema_version": VERSION, "engine_version": VERSION,
                 "mode": scenario["mode"], "scenario": scenario, "source": source,
                 "local_chain_id": 31337, "baseline": baseline, "candidate": candidate,
                 "comparison": {"final_balance_delta_wei": str(int(candidate["metrics"]["final_balance_wei"])-int(baseline["metrics"]["final_balance_wei"]))},
                 "assumptions": ["Paired isolated Anvil instances start from the same source state.",
                                 "Actor native balance is overridden equally and account impersonation is local only.",
                                 "This re-executes supplied actions, not subsequent historical blocks or market responses.",
                                 "Each slot mines one block at a fixed 12-second interval. Transaction order is supplied.",
                                 "Native balance change is not profit or portfolio valuation; token balances are not tracked.",
                                 "No LLM agent, MEV, mempool, external price or bridge model is provided."]})
