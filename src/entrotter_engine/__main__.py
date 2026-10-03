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
    t = s.add_parser(
        "trace-run", help="Replay an original signed transaction prefix in owned Anvil"
    )
    t.add_argument("plan")
    t.add_argument("-o", "--output", required=True)
    c = s.add_parser(
        "trace-observe",
        help="Export fixed owned Aave/WETH views with bounded trace replay",
    )
    c.add_argument("plan")
    c.add_argument("-o", "--output", required=True)
    position = s.add_parser(
        "trace-position",
        help="Compare fixed Aave account views on owned historical branches",
    )
    position.add_argument("plan")
    position.add_argument("-o", "--output", required=True)
    a = s.add_parser("serve")
    a.add_argument("--port", type=int, default=8787)
    a.add_argument("--output", default="artifacts")
    for command in (r, t, c, position, a):
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
        elif args.command == "trace-position":
            from .consumer_observations import ObservationStopped
            from .position_observations import (
                load_plan,
                run_position,
                run_position_native,
                write_position,
            )

            try:
                position_executor = (
                    run_position if args.isolated else run_position_native
                )
                result = position_executor(load_plan(args.plan))
            except ObservationStopped as stop:
                print("Error: Owned account observation stopped", file=sys.stderr)
                return 124 if stop.code == "deadline" else 130
            write_position(result, args.output)
            print(
                json.dumps(
                    {
                        "artifact_id": result["artifact_id"],
                        "classification": result["classification"],
                        "output": args.output,
                    }
                )
            )
        elif args.command == "trace-observe":
            from .consumer_observations import (
                ObservationStopped,
                run_trace_observed,
                run_trace_observed_native,
                write_observed_trace,
            )
            from .trace import load_trace

            try:
                observed_executor = (
                    run_trace_observed if args.isolated else run_trace_observed_native
                )
                result = observed_executor(load_trace(args.plan))
            except ObservationStopped as stop:
                print("Error: Owned consumer observation stopped", file=sys.stderr)
                return 124 if stop.code == "deadline" else 130
            write_observed_trace(result, args.output)
            print(
                json.dumps(
                    {
                        "artifact_id": result["artifact_id"],
                        "trace_artifact_id": result["trace_artifact_id"],
                        "complete_price_views": result["classification"][
                            "complete_price_views"
                        ],
                        "output": args.output,
                    }
                )
            )
        elif args.command == "trace-run":
            from .trace import load_trace, run_trace, run_trace_native, write_trace

            trace_executor = run_trace if args.isolated else run_trace_native
            result = trace_executor(load_trace(args.plan))
            write_trace(result, args.output)
            print(
                json.dumps(
                    {
                        "artifact_id": result["artifact_id"],
                        "execution_kind": result["execution_kind"],
                        "baseline_verified": result["baseline_verified"],
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
