from __future__ import annotations
import argparse
import json
import os
import sys
from .api import EngineServer
from .artifact import write_report
from .export_budget import ExportBudget
from .runner import run, run_native, load
from .evm import ExecutionError
from .rpc import RPCError


def main(argv=None):
    p = argparse.ArgumentParser(description="Entrotter local simulation engine")
    s = p.add_subparsers(dest="command", required=True)
    s.add_parser("exports", help="Inspect shared export quota and charged paths")
    r = s.add_parser("run")
    r.add_argument("scenario")
    r.add_argument("-o", "--output", required=True)
    a = s.add_parser("serve")
    a.add_argument("--port", type=int, default=8787)
    a.add_argument("--output", default="artifacts")
    for command in (r, a):
        mode = command.add_mutually_exclusive_group()
        mode.add_argument(
            "--isolated",
            dest="isolated",
            action="store_true",
            default=True,
            help="Use the configured bounded local Docker worker (default)",
        )
        mode.add_argument(
            "--native",
            dest="isolated",
            action="store_false",
            help="Trusted development only: bypass whole-process Docker resource limits",
        )
    args = p.parse_args(argv)
    try:
        if args.command == "exports":
            print(json.dumps(ExportBudget().snapshot(), indent=2))
            return 0
        if args.command == "run":
            executor = run if args.isolated else run_native
            result = executor(load(args.scenario))
            write_report(result, args.output)
            print(
                json.dumps(
                    {
                        "artifact_id": result["artifact_id"],
                        "mode": result["mode"],
                        "output": args.output,
                    }
                )
            )
        else:
            server = EngineServer(
                args.port,
                token=os.getenv("ENTROTTER_API_TOKEN", ""),
                output=args.output,
                isolated=args.isolated,
            )
            print(
                f"Local engine: http://127.0.0.1:{server.server_port}. Do not expose this port.",
                flush=True,
            )
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        return 0
    except (ValueError, OSError, ExecutionError, RPCError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
