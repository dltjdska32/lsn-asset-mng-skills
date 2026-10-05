"""Command-line inspection surface for the deterministic runtime skeleton."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Sequence

from investment_stack.execution import Availability, ModeRequest, RuntimeServices, execute_mode
from investment_stack.execution.host import open_configured_host
from investment_stack.invariants import validate_runtime_invariants
from investment_stack.pipelines import FixedPipelinePlanner
from investment_stack.routing import RequestMode, RequestRouter, RoutingError


def _persisted_report_sections(workspace: Path, run_id: str) -> list[dict[str, Any]]:
    """Return stored report lines. CLI output does not recompute prices."""
    from investment_stack.execution.host import open_run_database

    try:
        rows = open_run_database(workspace, run_id).fetch_phase6_context()["report_sections"]
    except (OSError, KeyError, ValueError, sqlite3.Error):
        return []
    sections: list[dict[str, Any]] = []
    for row in rows:
        try:
            metadata = json.loads(row["metadata_json"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if not isinstance(metadata, dict):
            continue
        lines = metadata.get("lines")
        sections.append({
            "section_name": row["section_name"],
            "section_status": row["section_status"],
            "title": metadata.get("title"),
            "lines": list(lines) if isinstance(lines, list) else [],
        })
    return sections


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
    execute.add_argument("--run-workspace", type=Path)
    execute.add_argument("--personal-db", type=Path)
    execute.add_argument("--live-providers", action="store_true")
    execute.add_argument("--web-research-bundle", type=Path)
    execute.add_argument("--market-captures", type=Path)
    execute.add_argument("--instrument-registry", type=Path)
    execute.add_argument("--offline-captures", action="store_true")
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
            if payload.get("refresh_market_bodies") is True and args.run_workspace is not None and args.personal_db is not None:
                from investment_stack.execution.host import open_run_database
                from investment_stack.execution.quote_refresh import refresh_requested_quotes

                refresh_requested_quotes(open_run_database(args.run_workspace, args.run_id), payload)
            services = runtime_services
            if services is None and (args.run_workspace or args.personal_db):
                if args.run_workspace is None or args.personal_db is None:
                    parser.error("configured execute host requires both --run-workspace and --personal-db")
                services = open_configured_host(args.run_workspace, args.run_id, args.personal_db,
                    live_providers=args.live_providers, web_research_bundle=args.web_research_bundle,
                    market_captures=args.market_captures, instrument_registry=args.instrument_registry,
                    offline_captures=args.offline_captures)
            result = execute_mode(request, services or RuntimeServices())
            payload_out = result.as_dict()
            if args.run_workspace is not None and args.personal_db is not None:
                payload_out["report_sections"] = _persisted_report_sections(args.run_workspace, args.run_id)
            _emit(payload_out, as_json=args.json)
            return 0 if result.availability in {Availability.COMPLETE, Availability.PARTIAL} else 3
    except (RoutingError, ValueError) as exc:
        parser.error(str(exc))
    return 2

