"""Fixed internal archive bridge; no public entrypoint or user-selected code."""

from __future__ import annotations

from collections import OrderedDict
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import re
import selectors
import signal
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entrotter_engine.rpc import NoRedirect, RPC, transport_code

MAX_REQUEST = 4096
MAX_RESPONSE = 4 * 1024 * 1024
MAX_CACHE = 8 * 1024 * 1024
MAX_ENTRY = 1024 * 1024
MAX_ENTRIES = 1024
MAX_REQUESTS = 4096
MAX_HANDLERS = 4
MAX_ADMISSION_WAIT = 0.1
METHODS = frozenset(
    {
        "eth_chainId",
        "eth_gasPrice",
        "eth_getBlockByNumber",
        "eth_getBalance",
        "eth_getCode",
        "eth_getTransactionCount",
        "eth_getStorageAt",
        "eth_getTransactionReceipt",
    }
)
STATE = METHODS - {
    "eth_chainId",
    "eth_gasPrice",
    "eth_getBlockByNumber",
    "eth_getTransactionReceipt",
}
HEX = re.compile(r"0x[0-9a-fA-F]+")
HASH = re.compile(r"0x[0-9a-fA-F]{64}")
ADDRESS = re.compile(r"0x[0-9a-fA-F]{40}")
CODES = frozenset(
    {
        "invalid_request",
        "invalid_response",
        "response_too_large",
        "timeout",
        "http_error",
        "connection_error",
        "tls_error",
        "transport_error",
        "rejected",
        "limit",
        "unsupported",
    }
)


class BridgeFailure(Exception):
    def __init__(self, code):
        self.code = code if code in CODES else "transport_error"


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    return json.loads(
        raw,
        object_pairs_hook=unique_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError()),
    )


def result_bytes(raw, request_id):
    """Keep the provider's exact JSON result token, with no provider error text."""
    text = raw.decode("utf-8")
    response = decode(text)
    if (
        not isinstance(response, dict)
        or response.get("jsonrpc") != "2.0"
        or type(response.get("id")) is not type(request_id)
        or response.get("id") != request_id
    ):
        raise BridgeFailure("invalid_response")
    if "error" in response:
        raise BridgeFailure("rejected")
    if set(response) != {"jsonrpc", "id", "result"}:
        raise BridgeFailure("invalid_response")
    decoder = json.JSONDecoder()
    pos = text.index("{") + 1
    while True:
        while text[pos].isspace() or text[pos] == ",":
            pos += 1
        key, end = decoder.raw_decode(text, pos)
        pos = end
        while text[pos].isspace():
            pos += 1
        if text[pos] != ":":
            raise BridgeFailure("invalid_response")
        pos += 1
        while text[pos].isspace():
            pos += 1
        start = pos
        _, pos = decoder.raw_decode(text, pos)
        if key == "result":
            return text[start:pos].encode("utf-8"), response["result"]


def request_fields(request):
    if (
        not isinstance(request, dict)
        or not {"jsonrpc", "id", "method"} <= set(request)
        or not set(request) <= {"jsonrpc", "id", "method", "params"}
    ):
        raise BridgeFailure("invalid_request")
    rid, method, params = request["id"], request["method"], request.get("params")
    if request["jsonrpc"] != "2.0" or not (
        type(rid) is int and 0 <= rid < 2**63 or type(rid) is str and len(rid) <= 64
    ):
        raise BridgeFailure("invalid_request")
    if type(method) is not str or method not in METHODS:
        raise BridgeFailure("unsupported")
    if params is None and method in {"eth_chainId", "eth_gasPrice"}:
        params = []
    if not isinstance(params, list):
        raise BridgeFailure("invalid_request")
    if method in {"eth_chainId", "eth_gasPrice"}:
        valid = not params
    elif method == "eth_getTransactionReceipt":
        valid = (
            len(params) == 1
            and isinstance(params[0], str)
            and HASH.fullmatch(params[0]) is not None
        )
    elif method == "eth_getBlockByNumber":
        valid = len(params) == 2 and type(params[1]) is bool and valid_block(params[0])
    else:
        valid = (
            len(params) == (3 if method == "eth_getStorageAt" else 2)
            and isinstance(params[0], str)
            and ADDRESS.fullmatch(params[0]) is not None
            and valid_block(params[-1])
        )
        if method == "eth_getStorageAt":
            valid = (
                valid
                and isinstance(params[1], str)
                and len(params[1]) <= 66
                and HEX.fullmatch(params[1]) is not None
            )
    if not valid:
        raise BridgeFailure("invalid_request")
    return rid, method, params


def valid_block(value):
    return type(value) is str and (
        value in {"latest", "pending", "earliest", "safe", "finalized"}
        or len(value) <= 66
        and HEX.fullmatch(value)
    )


def error_reply(rid, code):
    number = -32601 if code == "unsupported" else -32000
    return json.dumps(
        {"jsonrpc": "2.0", "id": rid, "error": {"code": number, "message": code}},
        separators=(",", ":"),
    ).encode()


class Bridge:
    def __init__(self, url, parent, deadline):
        RPC(url)  # Same URL/credential policy, but no ordinary method expansion.
        self.url, self.parent, self.deadline = url, parent, deadline
        self.opener = build_opener(ProxyHandler({}), NoRedirect())
        self.lock = threading.Lock()
        self.cache = OrderedDict()
        self.pending: dict[bytes, threading.Event] = {}
        self.bytes = 0
        self.stats = {
            "requests": 0,
            "upstream": 0,
            "hits": 0,
            "entries": 0,
            "bytes": 0,
            "uncached": 0,
            "errors": 0,
            "refused_handlers": 0,
        }

    def reply(self, request):
        supplied_id = request.get("id") if isinstance(request, dict) else None
        rid = (
            supplied_id
            if (
                type(supplied_id) is int
                and 0 <= supplied_id < 2**63
                or type(supplied_id) is str
                and len(supplied_id) <= 64
            )
            else None
        )
        try:
            with self.lock:
                if (
                    self.stats["requests"] >= MAX_REQUESTS
                    or time.monotonic() >= self.deadline
                ):
                    raise BridgeFailure("limit")
                self.stats["requests"] += 1
            rid, method, params = request_fields(request)
            value = self.read(rid, method, params)
            return (
                b'{"jsonrpc":"2.0","id":'
                + json.dumps(rid).encode()
                + b',"result":'
                + value
                + b"}"
            )
        except BridgeFailure as failure:
            self.increment("errors")
            return error_reply(rid, failure.code)
        except (ValueError, RecursionError, UnicodeError, HTTPException):
            self.increment("errors")
            return error_reply(rid, "invalid_response")
        except (URLError, HTTPError, TimeoutError, OSError) as failure:
            self.increment("errors")
            return error_reply(rid, transport_code(failure))

    def read(self, rid, method, params):
        key = json.dumps([method, params], separators=(",", ":")).encode()
        pinned = method in STATE and params[-1] == self.parent["block_hash"]
        header = method == "eth_getBlockByNumber" and params[0] == hex(
            self.parent["block_number"]
        )
        owner = None
        try:
            while True:
                with self.lock:
                    if time.monotonic() >= self.deadline:
                        raise BridgeFailure("limit")
                    if key in self.cache:
                        self.stats["hits"] += 1
                        return self.cache[key]
                    if pinned or header:
                        waiting = self.pending.get(key)
                        if waiting is None:
                            # The fixed server admits at most four handlers. Keep
                            # pending keys independently bounded for internal callers.
                            if len(self.pending) >= MAX_HANDLERS:
                                raise BridgeFailure("limit")
                            owner = threading.Event()
                            self.pending[key] = owner
                            self.stats["upstream"] += 1
                            break
                    else:
                        self.stats["upstream"] += 1
                        break
                # Eligible waiters never hold the global lock. Only a successfully
                # cached response is shared; errors and non-cacheable results wake
                # waiters to make their own first actual upstream request.
                remaining = self.deadline - time.monotonic()
                if remaining <= 0 or not waiting.wait(remaining):
                    raise BridgeFailure("limit")
            value, parsed = self.fetch(rid, method, params)
            if header and (
                not isinstance(parsed, dict)
                or parsed.get("hash") != self.parent["block_hash"]
            ):
                raise BridgeFailure("invalid_response")
            cost = len(key) + len(value)
            with self.lock:
                if (
                    (pinned or header)
                    and parsed is not None
                    and len(value) <= MAX_ENTRY
                    and self.bytes + cost <= MAX_CACHE
                    and len(self.cache) < MAX_ENTRIES
                ):
                    self.cache[key] = value
                    self.bytes += cost
                    self.stats["entries"], self.stats["bytes"] = (
                        len(self.cache),
                        self.bytes,
                    )
                else:
                    self.stats["uncached"] += 1
            return value
        finally:
            if owner is not None:
                with self.lock:
                    if self.pending.get(key) is owner:
                        del self.pending[key]
                    owner.set()

    def increment(self, key):
        # Fixed finite telemetry, including rejected connections after call cap.
        with self.lock:
            self.stats[key] = min(MAX_CACHE, self.stats[key] + 1)

    def snapshot(self):
        with self.lock:
            return dict(self.stats)

    def fetch(self, rid, method, params):
        body = json.dumps(
            {"jsonrpc": "2.0", "id": rid, "method": method, "params": params}
        ).encode()
        req = Request(
            self.url,
            body,
            {"Content-Type": "application/json", "User-Agent": "Entrotter/0.1.0"},
            method="POST",
        )
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise BridgeFailure("limit")
        with self.opener.open(req, timeout=min(10, remaining)) as response:
            expected = getattr(response, "length", None)
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise BridgeFailure("response_too_large")
        if type(expected) is int and len(raw) != expected:
            raise BridgeFailure("invalid_response")
        return result_bytes(raw, rid)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = MAX_HANDLERS

    def __init__(self, bridge, token):
        self.bridge, self.token = bridge, token
        self.slots = threading.BoundedSemaphore(MAX_HANDLERS)
        super().__init__(("127.0.0.1", 0), Handler)

    def process_request(self, request, address):
        # The accepting thread can hold one socket briefly while a completed
        # handler releases its slot. No fifth handler or unbounded wait queue is
        # created; sustained pressure still closes the connection without I/O.
        remaining = self.bridge.deadline - time.monotonic()
        if remaining <= 0 or not self.slots.acquire(
            timeout=min(MAX_ADMISSION_WAIT, remaining)
        ):
            self.bridge.increment("refused_handlers")
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            self.shutdown_request(request)
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def handle_error(self, request, address):
        # Provider/request errors must never invoke traceback formatting.
        self.bridge.increment("errors")


class Handler(BaseHTTPRequestHandler):
    server: Server

    def log_message(self, *args):
        pass

    def setup(self):
        self.request.settimeout(
            max(0.001, min(3, self.server.bridge.deadline - time.monotonic()))
        )
        super().setup()

    def do_POST(self):
        try:
            if (
                self.path != "/" + self.server.token
                or self.headers.get("Origin") is not None
                or self.headers.get("Transfer-Encoding") is not None
            ):
                self.send_error(403)
                return
            length = self.headers.get("Content-Length", "")
            if (
                not length.isascii()
                or not length.isdecimal()
                or not 0 < int(length) <= MAX_REQUEST
            ):
                self.send_error(413)
                return
            raw = self.rfile.read(int(length))
            if len(raw) != int(length):
                raise ValueError()
            request = decode(raw)
            if isinstance(request, list):
                if not 0 < len(request) <= 8:
                    raise ValueError()
                pieces = []
                output_length = 2
                for item in request:
                    piece = self.server.bridge.reply(item)
                    output_length += len(piece) + 1
                    if output_length > MAX_RESPONSE:
                        raise ValueError()
                    pieces.append(piece)
                body = b"[" + b",".join(pieces) + b"]"
            else:
                body = self.server.bridge.reply(request)
            if len(body) > MAX_RESPONSE:
                body = error_reply(None, "response_too_large")
        except (ValueError, RecursionError, UnicodeError, OSError):
            body = error_reply(None, "invalid_request")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    config = sys.stdin.buffer.readline(16386)
    if len(config) > 16385 or not config.endswith(b"\n"):
        raise ValueError()
    value = decode(config)
    if not isinstance(value, dict) or set(value) != {
        "url",
        "parent",
        "deadline",
        "token",
    }:
        raise ValueError()
    parent, deadline, token = value["parent"], value["deadline"], value["token"]
    if (
        not isinstance(parent, dict)
        or type(parent.get("block_number")) is not int
        or not 0 <= parent["block_number"] < 2**64
        or not isinstance(parent.get("block_hash"), str)
        or not HASH.fullmatch(parent["block_hash"])
        or parent["block_hash"] != parent["block_hash"].lower()
        or type(deadline) not in {int, float}
        or not math.isfinite(deadline)
        or not 0 < deadline - time.monotonic() <= 150
        or type(token) is not str
        or not re.fullmatch(r"[0-9a-f]{32}", token)
    ):
        raise ValueError()
    bridge = Bridge(value["url"], parent, deadline)
    server = Server(bridge, token)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
    )
    thread.start()
    print(
        json.dumps({"version": 1, "port": server.server_port, "token": token}),
        flush=True,
    )
    with selectors.DefaultSelector() as selector:
        selector.register(sys.stdin, selectors.EVENT_READ)
        while not stop.is_set() and time.monotonic() < deadline:
            if selector.select(0.1):
                break  # Parent ownership pipe closed or received data.
    server.shutdown()
    server.server_close()
    print(json.dumps(bridge.snapshot(), separators=(",", ":")), flush=True)
    # Bound blocked DNS/read handlers by killing this owned process, not leaving
    # detached threads in the caller. The parent independently reaps this PID.
    os._exit(0)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        os._exit(1)  # No configuration, provider text or traceback output.
