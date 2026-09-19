"""Loopback-only development API. Not an Internet-facing multi-tenant server."""

from __future__ import annotations
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import socket
import threading
import time
from pathlib import Path
from .store import ArtifactStore, StoreBusy, StoreFull
from .models import ValidationError
from .rpc import RPCError
from .evm import ExecutionError
from .runner import run, run_native

MAX_BODY = 262144
MAX_CONNECTIONS = 8
MAX_CONNECTION_SECONDS = 240
MAX_REJECTION_SECONDS = 0.1
MAX_REJECTION_BYTES = MAX_BODY + 65536


class EngineServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def __init__(
        self,
        port: int = 8787,
        *,
        token: str = "",
        output: str | Path = "artifacts",
        isolated: bool = True,
    ):
        self.token, self.output = token, Path(output).resolve()
        self.store = ArtifactStore(self.output)
        self.slot = threading.BoundedSemaphore(1)
        self.connections = threading.BoundedSemaphore(MAX_CONNECTIONS)
        # This switch belongs to the trusted operator, never to request JSON.
        self.runner = run if isolated else run_native
        super().__init__(("127.0.0.1", port), Handler)

    def process_request(self, request, client_address):
        if not self.connections.acquire(blocking=False):
            try:
                deadline = time.monotonic() + MAX_REJECTION_SECONDS
                request.settimeout(MAX_REJECTION_SECONDS)
                body = b'{"error":"connection_limit"}'
                response = (
                    "HTTP/1.1 503 Service Unavailable\r\nContent-Type: application/json\r\n"
                    f"Content-Length: {len(body)}\r\nConnection: close\r\n"
                    "Cache-Control: no-store\r\nRetry-After: 1\r\n\r\n"
                ).encode() + body
                request.sendall(response)
                # A client can still be writing its POST body. Closing with
                # unread bytes can reset TCP and hide the already-sent 503.
                # Half-close our output, then discard bounded pending input;
                # never admit work or create another handler for this socket.
                request.shutdown(socket.SHUT_WR)
                remaining_bytes = MAX_REJECTION_BYTES
                while remaining_bytes:
                    remaining_time = deadline - time.monotonic()
                    if remaining_time <= 0:
                        break
                    request.settimeout(remaining_time)
                    chunk = request.recv(min(65536, remaining_bytes))
                    if not chunk:
                        break
                    remaining_bytes -= len(chunk)
            except OSError:
                pass
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.connections.release()
            raise

    def process_request_thread(self, request, client_address):
        def expire():
            try:
                request.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(MAX_CONNECTION_SECONDS, expire)
        timer.daemon = True
        try:
            timer.start()
            super().process_request_thread(request, client_address)
        finally:
            timer.cancel()
            if timer.ident is not None:
                timer.join()
            self.connections.release()


class Handler(BaseHTTPRequestHandler):
    server: EngineServer
    server_version = "Entrotter/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            # A disconnected/expired client is normal and must not emit a
            # traceback or keep its connection slot after bounded work ends.
            return

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
            self.reply(403, {"error": "host_not_allowed"})
            return False
        if self.headers.get("Origin") is not None:
            self.reply(403, {"error": "browser_origin_not_allowed"})
            return False
        if self.server.token and not hmac.compare_digest(
            self.headers.get("Authorization", ""), "Bearer " + self.server.token
        ):
            self.reply(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == "/health":
            self.reply(
                200, {"status": "ok", "version": "0.1.0", "scope": "local-development"}
            )
            return
        match = re.fullmatch(r"/v1/runs/([0-9a-f]{64})", self.path)
        if match:
            try:
                data = self.server.store.get(match[1])
            except FileNotFoundError:
                self.reply(404, {"error": "not_found"})
                return
            except (OSError, ValueError, RecursionError):
                self.reply(500, {"error": "invalid_stored_artifact"})
                return
            self.reply(200, data)
            return
        self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if not self.authorized():
            return
        if self.path != "/v1/runs":
            self.reply(404, {"error": "not_found"})
            return
        if self.headers.get_content_type() != "application/json":
            self.reply(415, {"error": "content_type_must_be_json"})
            return
        if self.headers.get("Transfer-Encoding"):
            self.reply(400, {"error": "chunked_requests_not_supported"})
            return
        lengths = self.headers.get_all("Content-Length", [])
        try:
            if len(lengths) != 1:
                raise ValueError()
            size = int(lengths[0])
            if not 0 < size <= MAX_BODY:
                raise ValueError()
        except ValueError:
            self.reply(413, {"error": "body_limit_256_kib"})
            return
        if not self.server.slot.acquire(blocking=False):
            self.reply(429, {"error": "engine_busy_retry_later"})
            return
        try:
            data = self.rfile.read(size)
            if len(data) != size:
                raise ValidationError("Incomplete request body")
            scenario = json.loads(data)
            result = self.server.runner(scenario)
            self.server.store.put(result)
            self.reply(201, result)
        except StoreFull:
            self.reply(
                507,
                {
                    "error": "artifact_store_full",
                    "hint": "Export or remove saved reports locally before retrying.",
                },
            )
        except StoreBusy:
            self.reply(503, {"error": "artifact_store_busy"})
        except (
            ValidationError,
            json.JSONDecodeError,
            UnicodeDecodeError,
            RecursionError,
        ):
            self.reply(400, {"error": "invalid_scenario"})
        except (ExecutionError, RPCError):
            self.reply(
                422,
                {
                    "error": "execution_failed",
                    "hint": "Check the configured runtime, resource limits, archive RPC and pinned source. No fallback was used.",
                },
            )
        except ValueError:
            self.reply(500, {"error": "invalid_stored_artifact"})
        except (OSError, TimeoutError):
            self.reply(500, {"error": "io_or_timeout_error"})
        finally:
            self.server.slot.release()
