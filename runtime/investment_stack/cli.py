"""Command-line inspection surface for the deterministic runtime skeleton."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Sequence

from investment_stack.execution import Availability, ModeRequest, RuntimeServices, execute_mode
from investment_stack.invariants import validate_runtime_invariants
from investment_stack.pipelines import FixedPipelinePlanner
from investment_stack.routing import RequestMode, RequestRouter, RoutingError


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, list):
                print(f"{key}:")
                for item in value:
                    print(f"  - {item}")
            else:
                print(f"{key}: {value}")
        return
    print(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="investment-stack")
    subparsers = parser.add_subparsers(dest="command", required=True)

    route = subparsers.add_parser("route", help="route request text and show its fixed pipeline")
    route.add_argument("text")
    route.add_argument("--mode", choices=[mode.value for mode in RequestMode])
    route.add_argument("--json", action="store_true")

    plan = subparsers.add_parser("plan", help="show the fixed pipeline for a request mode")
    plan.add_argument("mode", choices=[mode.value for mode in RequestMode])
    plan.add_argument("--json", action="store_true")

    check = subparsers.add_parser("check", help="validate implemented architecture invariants")
    check.add_argument("--project-root", type=Path)
    check.add_argument("--json", action="store_true")
    execute = subparsers.add_parser("execute", help="execute a fixed request-mode pipeline from JSON on stdin")
    execute.add_argument("--mode", required=True, choices=[mode.value for mode in RequestMode])
    execute.add_argument("--run-id", required=True)
    execute.add_argument("--refresh-replay", action="store_true")
    execute.add_argument("--json", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None, *, runtime_services: RuntimeServices | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    planner = FixedPipelinePlanner()

    try:
        if args.command == "route":
            decision = RequestRouter().route(args.text, mode_hint=args.mode)
            payload = {**decision.as_dict(), "pipeline": planner.plan(decision.mode).as_dict()["steps"]}
            _emit(payload, as_json=args.json)
            return 0
        if args.command == "plan":
            _emit(planner.plan(args.mode).as_dict(), as_json=args.json)
            return 0
        if args.command == "check":
            results = validate_runtime_invariants(args.project_root)
            payload = {
                "passed": all(result.passed for result in results),
                "results": [result.as_dict() for result in results],
            }
            _emit(payload, as_json=args.json)
            return 0 if payload["passed"] else 1
        if args.command == "execute":
            try:
                payload = json.load(sys.stdin)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                parser.error(f"execute input on stdin must be a JSON object: {type(exc).__name__}")
            if not isinstance(payload, dict):
                parser.error("execute input on stdin must be a JSON object")
            request = ModeRequest(args.run_id, RequestMode.parse(args.mode), payload, refresh_replay=args.refresh_replay)
            result = execute_mode(request, runtime_services or RuntimeServices())
            _emit(result.as_dict(), as_json=args.json)
            return 0 if result.availability in {Availability.COMPLETE, Availability.PARTIAL} else 3
    except (RoutingError, ValueError) as exc:
        parser.error(str(exc))
    return 2

