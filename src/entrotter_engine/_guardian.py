"""Internal POSIX process guardian. Its stdin is an owner-lifetime pipe, not commands.

Only evm.py constructs its argv from the trusted installed Anvil executable.
This helper is not an untrusted-code sandbox or a public agent execution API.
"""

import math
import os
import selectors
import signal
import subprocess
import sys
import time


def supervise(command, lifetime):
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    process = None
    deadline = time.monotonic() + lifetime
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        with selectors.DefaultSelector() as selector:
            selector.register(sys.stdin.fileno(), selectors.EVENT_READ)
            while not stopping and process.poll() is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return 124
                for key, _ in selector.select(min(0.1, remaining)):
                    # EOF means the owning process closed the pipe or died. Data is
                    # invalid too: this channel cannot select executable commands.
                    os.read(key.fd, 1)
                    stopping = True
        return process.returncode if process.returncode is not None else 0
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)


def main():
    try:
        lifetime = float(sys.argv[1])
        if (
            not math.isfinite(lifetime)
            or not 0.1 <= lifetime <= 150
            or len(sys.argv) < 3
        ):
            return 2
        return supervise(sys.argv[2:], lifetime)
    except (IndexError, ValueError, OSError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
