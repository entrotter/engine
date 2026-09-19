"""Two distinct transports: read-only upstream and private local Anvil."""
from __future__ import annotations
import json
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
from urllib.error import URLError, HTTPError

class RPCError(RuntimeError):
    pass

class RPCRejected(RPCError):
    """An explicit JSON-RPC rejection, distinct from a transport timeout."""
    pass

READ_ONLY = {"eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_getBalance",
             "eth_getCode", "eth_getTransactionReceipt", "eth_call"}
LOCAL = READ_ONLY | {"web3_clientVersion", "eth_sendTransaction", "eth_getTransactionCount",
                    "anvil_setBalance", "anvil_setCode", "anvil_impersonateAccount",
                    "anvil_stopImpersonatingAccount", "evm_mine", "evm_setNextBlockTimestamp"}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

class RPC:
    def __init__(self, url: str, *, local: bool = False, timeout: float = 10):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise RPCError("RPC requires an HTTP(S) URL")
        if parsed.username or parsed.password or parsed.fragment:
            raise RPCError("RPC credentials must not use URL user-info; fragments are unsupported")
        if local and (parsed.scheme != "http" or parsed.hostname != "127.0.0.1"):
            raise RPCError("Write-capable RPC must be a loopback Anvil instance owned by this run")
        self.url, self.local, self.timeout = url, local, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.next_id = 0

    def call(self, method: str, params: list | None = None):
        if method not in (LOCAL if self.local else READ_ONLY):
            raise RPCError("RPC method is not allowed on this transport")
        self.next_id += 1
        req_id = self.next_id
        body = json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or []}).encode()
        req = Request(self.url, body, {"Content-Type": "application/json",
                                      "User-Agent": "Entrotter/0.1.0"}, method="POST")
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                raw = response.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                raise RPCError("RPC response too large")
            result = json.loads(raw)
            if not isinstance(result, dict) or result.get("id") != req_id:
                raise RPCError("Invalid RPC response")
            if "error" in result:
                # Never propagate upstream messages: they may contain an API key/URL.
                code = result["error"].get("code") if isinstance(result["error"], dict) else None
                raise RPCRejected(f"RPC rejected {method} (code {code})")
            if "result" not in result:
                raise RPCError("RPC response has no result")
            return result["result"]
        except RPCError:
            raise
        except (URLError, HTTPError, TimeoutError, OSError, ValueError) as e:
            raise RPCError(f"RPC request failed for {method}; check connectivity and archive access") from None
