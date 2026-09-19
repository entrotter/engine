"""Container entrypoint for bounded JSON-only experiments; never imports supplied code."""

import signal
import sys

from entrotter_engine.artifact import canonical
from entrotter_engine.worker_protocol import MAX_AGENT_INPUT, execute_request

MAX_OUTPUT = 8 * 1024 * 1024


def expired(signum, frame):
    raise TimeoutError("Worker lifetime exceeded")


def main():
    signal.signal(signal.SIGALRM, expired)
    signal.signal(signal.SIGTERM, expired)
    signal.setitimer(signal.ITIMER_REAL, 180)
    try:
        raw = sys.stdin.buffer.read(MAX_AGENT_INPUT + 1)
        if not raw or len(raw) > MAX_AGENT_INPUT:
            raise ValueError("Worker input limit exceeded")
        result = execute_request(raw)
        output = canonical(result)
        if len(output) > MAX_OUTPUT:
            raise ValueError("Worker output limit exceeded")
        sys.stdout.buffer.write(output)
        sys.stdout.buffer.flush()
        return 0
    except BaseException:
        # Neither provider diagnostics nor private input belong in process logs.
        sys.stdout.write('{"error":"isolated_execution_failed"}')
        sys.stdout.flush()
        return 1
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)


if __name__ == "__main__":
    raise SystemExit(main())
