"""Command-line inspection surface for the deterministic runtime skeleton."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
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
    except (RoutingError, ValueError) as exc:
        parser.error(str(exc))
    return 2

