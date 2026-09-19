"""Loopback-only development API. Not an Internet-facing multi-tenant server."""
from __future__ import annotations
from contextlib import contextmanager
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
from pathlib import Path
from .artifact import verify, write_report
from .models import ValidationError
from .rpc import RPCError
from .evm import ExecutionError
from .runner import run

MAX_BODY = 262144

class EngineServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(self, port: int = 8787, *, token: str = "", output: str | Path = "artifacts", isolated: bool = False):
        super().__init__(("127.0.0.1", port), Handler)
        self.token, self.output = token, Path(output).resolve()
        self.slot = threading.BoundedSemaphore(1)
        if isolated:
            from .isolated import run_isolated
            self.runner = run_isolated
        else:
            self.runner = run

class Handler(BaseHTTPRequestHandler):
    server: EngineServer
    server_version = "Entrotter/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *args):
        # Avoid logging payloads, paths, or credentials.
        return

    def reply(self, status: int, data: dict):
        raw = json.dumps(data, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection = True

    def authorized(self) -> bool:
        port = self.server.server_port
        if self.headers.get("Host") not in {f"127.0.0.1:{port}", f"localhost:{port}"}:
            self.reply(403, {"error": "host_not_allowed"}); return False
        if self.headers.get("Origin") is not None:
            self.reply(403, {"error": "browser_origin_not_allowed"}); return False
        if self.server.token and not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer "+self.server.token):
            self.reply(401, {"error": "unauthorized"}); return False
        return True

    def do_GET(self):
        if not self.authorized(): return
        if self.path == "/health":
            self.reply(200, {"status": "ok", "version": "0.1.0", "scope": "local-development"}); return
        match = re.fullmatch(r"/v1/runs/([0-9a-f]{64})", self.path)
        if match:
            path = self.server.output / (match[1]+".json")
            if not path.is_file():
                self.reply(404, {"error": "not_found"}); return
            try:
                data = json.loads(path.read_bytes())
                if not verify(data): raise ValueError("invalid artifact")
            except (OSError, ValueError):
                self.reply(500, {"error": "invalid_stored_artifact"}); return
            self.reply(200, data); return
        self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized(): return
        if self.path != "/v1/runs":
            self.reply(404, {"error": "not_found"}); return
        if self.headers.get_content_type() != "application/json":
            self.reply(415, {"error": "content_type_must_be_json"}); return
        if self.headers.get("Transfer-Encoding"):
            self.reply(400, {"error": "chunked_requests_not_supported"}); return
        lengths = self.headers.get_all("Content-Length", [])
        try:
            if len(lengths) != 1: raise ValueError()
            size = int(lengths[0])
            if not 0 < size <= MAX_BODY: raise ValueError()
        except ValueError:
            self.reply(413, {"error": "body_limit_256_kib"}); return
        if not self.server.slot.acquire(blocking=False):
            self.reply(429, {"error": "engine_busy_retry_later"}); return
        try:
            data = self.rfile.read(size)
            if len(data) != size: raise ValidationError("Incomplete request body")
            scenario = json.loads(data)
            result = self.server.runner(scenario)
            write_report(result, self.server.output / (result["artifact_id"]+".json"))
            self.reply(201, result)
        except (ValidationError, json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            self.reply(400, {"error": "invalid_scenario"})
        except (ExecutionError, RPCError):
            self.reply(422, {"error": "execution_failed", "hint": "Check the configured runtime, resource limits, archive RPC and pinned source. No fallback was used."})
        except (OSError, TimeoutError):
            self.reply(500, {"error": "io_or_timeout_error"})
        finally:
            self.server.slot.release()
