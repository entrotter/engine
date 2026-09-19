from __future__ import annotations
import argparse
import json
import os
import sys
from .api import EngineServer
from .artifact import write_report
from .runner import run, load
from .evm import ExecutionError
from .rpc import RPCError

def main(argv=None):
    p = argparse.ArgumentParser(description="Entrotter local simulation engine")
    s = p.add_subparsers(dest="command", required=True)
    r = s.add_parser("run"); r.add_argument("scenario"); r.add_argument("-o", "--output", required=True)
    a = s.add_parser("serve"); a.add_argument("--port", type=int, default=8787); a.add_argument("--output", default="artifacts")
    r.add_argument("--isolated", action="store_true", help="Use the configured bounded local Docker worker")
    a.add_argument("--isolated", action="store_true", help="Run API experiments in the bounded local Docker worker")
    args = p.parse_args(argv)
    try:
        if args.command == "run":
            if args.isolated:
                from .isolated import run_isolated
                executor = run_isolated
            else:
                executor = run
            result = executor(load(args.scenario)); write_report(result, args.output)
            print(json.dumps({"artifact_id": result["artifact_id"], "mode": result["mode"], "output": args.output}))
        else:
            server = EngineServer(args.port, token=os.getenv("ENTROTTER_API_TOKEN", ""), output=args.output, isolated=args.isolated)
            print(f"Local engine: http://127.0.0.1:{server.server_port}. Do not expose this port.", flush=True)
            try: server.serve_forever()
            except KeyboardInterrupt: pass
            finally: server.server_close()
        return 0
    except (ValueError, OSError, ExecutionError, RPCError) as e:
        print(f"Error: {e}", file=sys.stderr); return 1

if __name__ == "__main__":
    raise SystemExit(main())
