"""DevDNA command-line interface.

Talks to a running DevDNA API (local Docker stack or staging) and exposes the
whole product from the terminal:

    devdna analyze octocat --role python_backend_developer --wait
    devdna report ANALYSIS_ID
    devdna jd ANALYSIS_ID --text-file senior-backend.txt
    devdna readme ANALYSIS_ID --style badges --out README.md

Configuration comes from the environment:
    DEVDNA_API_URL   base URL of the API        (default http://localhost:8000)
    DEVDNA_API_KEY   client.secret bearer key   (required when the API enforces keys)

Exit codes: 0 success, 1 API/analysis error, 2 usage error.
"""

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx2

DEFAULT_API_URL = "http://localhost:8000"
POLL_INTERVAL_SECONDS = 2.5
DEFAULT_WAIT_TIMEOUT_SECONDS = 180.0
ROLES = ("python_backend_developer", "frontend_react_developer")
README_STYLES = ("minimal", "badges", "centered")

LINE = "─" * 62


class CliError(Exception):
    """An expected failure with a terminal-friendly message."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="devdna",
        description="Evidence-based GitHub developer intelligence, from your terminal.",
    )
    parser.add_argument(
        "--api-url",
        default=os.environ.get("DEVDNA_API_URL", DEFAULT_API_URL),
        help="Base URL of the DevDNA API (default: %(default)s)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("DEVDNA_API_KEY", ""),
        help="Bearer key as client.secret when the API enforces keys",
    )
    parser.add_argument("--json", action="store_true", help="Print raw JSON responses")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser("analyze", help="Start an analysis for a GitHub username")
    analyze.add_argument("username", help="Public GitHub username")
    analyze.add_argument(
        "--role",
        default=ROLES[0],
        choices=ROLES,
        help="Role rubric to evaluate against (default: %(default)s)",
    )
    analyze.add_argument(
        "--wait",
        action="store_true",
        help="Poll until the report is ready, then print it",
    )
    analyze.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_WAIT_TIMEOUT_SECONDS,
        help="Seconds to wait with --wait before giving up (default: %(default)s)",
    )

    status = subparsers.add_parser("status", help="Show one analysis status snapshot")
    status.add_argument("analysis_id")

    report = subparsers.add_parser("report", help="Print the evidence-backed report")
    report.add_argument("analysis_id")

    readme = subparsers.add_parser("readme", help="Profile README draft (Markdown)")
    readme.add_argument("analysis_id")
    readme.add_argument("--style", default="minimal", choices=README_STYLES)
    readme.add_argument("--out", help="Write to a file instead of stdout")

    learning = subparsers.add_parser("learning", help="Evidence-gap learning plan")
    learning.add_argument("analysis_id")

    jd = subparsers.add_parser("jd", help="Compare a job description with saved evidence")
    jd.add_argument("analysis_id")
    group = jd.add_mutually_exclusive_group(required=True)
    group.add_argument("--text", help="Job description text")
    group.add_argument("--text-file", help="File containing the job description")

    cv = subparsers.add_parser("cv", help="Align an uploaded CV with saved evidence")
    cv.add_argument("analysis_id")
    cv.add_argument("file", help="Path to a .pdf or .docx CV")

    subparsers.add_parser("history", help="List analyses owned by the API client")

    subparsers.add_parser("health", help="API readiness check")

    return parser


def request_json(
    api_url: str,
    method: str,
    path: str,
    *,
    api_key: str = "",
    json_body: dict[str, Any] | None = None,
    data: dict[str, str] | None = None,
    files: dict[str, Any] | None = None,
    expected: tuple[int, ...] = (200,),
) -> tuple[int, Any]:
    url = f"{api_url.rstrip('/')}{path}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = httpx2.request(
            method,
            url,
            headers=headers,
            json=json_body,
            data=data,
            files=files,
            timeout=30.0,
        )
    except httpx2.HTTPError as error:
        raise CliError(f"Cannot reach the DevDNA API at {api_url}: {error}") from error
    if response.status_code not in expected:
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict) and isinstance(body.get("detail"), str):
                detail = body["detail"]
        except ValueError:
            detail = response.text[:200]
        suffix = f": {detail}" if detail else ""
        raise CliError(f"{method} {path} failed ({response.status_code}){suffix}")
    if response.status_code == 204 or not response.content:
        return response.status_code, None
    try:
        return response.status_code, response.json()
    except ValueError as error:
        raise CliError(f"{method} {path} returned invalid JSON") from error


def wait_for_report(
    api_url: str,
    analysis_id: str,
    *,
    api_key: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "queued"
    while time.monotonic() < deadline:
        _, payload = request_json(api_url, "GET", f"/v1/analyses/{analysis_id}", api_key=api_key)
        assert isinstance(payload, dict)
        last_status = str(payload.get("status", ""))
        if last_status in {"completed", "partial", "failed"}:
            return payload
        print(f"  {last_status}…", file=sys.stderr)
        time.sleep(POLL_INTERVAL_SECONDS)
    raise CliError(f"Timed out after {timeout_seconds:.0f}s waiting; analysis is {last_status}")


def print_analysis_summary(payload: dict[str, Any]) -> None:
    print(LINE)
    print(f"  {payload.get('github_username', '?')}  ·  {payload.get('target_role', '?')}")
    print(f"  id:     {payload.get('id')}")
    print(f"  status: {payload.get('status')}")
    error_message = payload.get("error_message")
    if error_message:
        print(f"  note:   {error_message}")
    print(LINE)


def print_report(report: dict[str, Any], *, full: bool = True) -> None:
    print(LINE)
    print(
        f"  ROLE FIT  {report.get('alignment_label')}  —  "
        f"{report.get('requirements_met')}/{report.get('requirements_total')} verified"
    )
    collection_status = report.get("collection_status")
    if collection_status == "partial":
        print(f"  warning: partial inspection — {report.get('warning') or 'data incomplete'}")
    print(LINE)

    strengths = report.get("strengths") or []
    print(f"\nVERIFIED STRENGTHS ({len(strengths)})")
    for strength in strengths:
        sources = ", ".join(
            f"{source['repository']}/{source['path']}" for source in strength.get("sources", [])
        )
        print(f"  + {strength['title']}")
        print(f"      {strength.get('summary', '')}")
        if sources:
            print(f"      evidence: {sources}")

    gaps = report.get("gaps") or []
    print(f"\nEVIDENCE GAPS ({len(gaps)})")
    for gap in gaps:
        print(f"  - {gap['title']}")
        print(f"      {gap.get('explanation', '')}")

    actions = report.get("actions") or []
    if full and actions:
        print(f"\nPRIORITIZED ACTIONS ({len(actions)})")
        for action in actions:
            needed = "; ".join(action.get("evidence_needed", []))
            print(f"  {action.get('priority')}. {action['title']}")
            print(f"      requirement: {str(action.get('requirement', '')).replace('_', ' ')}")
            print(f"      publish: {needed}")


def print_learning(plan: dict[str, Any]) -> None:
    print(LINE)
    print("  LEARNING PLAN")
    print(LINE)
    for item in plan.get("recommendations", []):
        kind = str(item.get("kind", "")).replace("_", " ")
        print(f"\n[{item.get('priority')}] {kind}: {item.get('title')}")
        print(f"    why: {item.get('rationale', '')}")
        outcomes = item.get("learning_outcomes") or []
        if outcomes:
            print("    learn:")
            for outcome in outcomes:
                print(f"      - {outcome}")
        project = item.get("project_brief")
        if project:
            print(f"    build: {project}")
        evidence_items = item.get("evidence_to_publish") or []
        if evidence_items:
            print("    publish as evidence:")
            for entry in evidence_items:
                print(f"      - {entry}")


def print_jd_alignment(alignment: dict[str, Any]) -> None:
    print(LINE)
    verified = alignment.get("verified_count", 0)
    considered = alignment.get("requirements_considered", 0)
    print(f"  JD FIT  {verified}/{considered} demands verified by public evidence")
    print(f"  {alignment.get('suggested_summary', '')}")
    print(LINE)

    skills = alignment.get("skills", [])
    verified_skills = [skill for skill in skills if skill.get("status") == "verified"]
    missing_skills = [skill for skill in skills if skill.get("status") == "unverified"]

    print(f"\nVERIFIED DEMANDS ({len(verified_skills)})")
    for skill in verified_skills:
        sources = ", ".join(
            f"{source['repository']}/{source['path']}"
            for source in skill.get("evidence_sources", [])[:3]
        )
        print(f"  + {skill['skill']}  (demanded {skill.get('mentions', 1)}×)")
        if sources:
            print(f"      proof: {sources}")

    print(f"\nPREPARATION BACKLOG ({len(missing_skills)})")
    for position, skill in enumerate(missing_skills, start=1):
        print(f"  {position}. {skill['skill']}  (demanded {skill.get('mentions', 1)}×)")


def run_command(args: argparse.Namespace) -> int:
    api_url = args.api_url
    api_key = args.api_key
    raw_json = args.json

    def emit(payload: Any) -> None:
        if raw_json:
            print(json.dumps(payload, indent=2))
        else:
            print(json.dumps(payload, indent=2))

    if args.command == "health":
        _, payload = request_json(api_url, "GET", "/health/ready", expected=(200, 503))
        assert isinstance(payload, dict)
        ready = payload.get("status") == "ready"
        if raw_json:
            emit(payload)
        else:
            checks = payload.get("checks")
            if isinstance(checks, dict):
                for name, state_value in checks.items():
                    print(f"  {name:<10} {state_value}")
            else:
                print(f"  status: {payload.get('status')}")
            print("API ready" if ready else "API degraded")
        return 0 if ready else 1

    if args.command == "analyze":
        created_status, created = request_json(
            api_url,
            "POST",
            "/v1/analyses",
            api_key=api_key,
            json_body={"github_username": args.username, "target_role": args.role},
            expected=(202,),
        )
        assert isinstance(created, dict)
        analysis_id = str(created["id"])
        if not args.wait:
            if raw_json:
                emit(created)
            else:
                print_analysis_summary(created)
                print(f"\nNext: devdna report {analysis_id}  (or re-run with --wait)")
            return 0
        final = wait_for_report(
            api_url,
            analysis_id,
            api_key=api_key,
            timeout_seconds=args.timeout,
        )
        if raw_json:
            emit(final)
        print_analysis_summary(final)
        if final.get("status") == "failed":
            print("\nThe analysis failed; see the note above.", file=sys.stderr)
            return 1
        report_status, report = request_json(
            api_url, "GET", f"/v1/analyses/{analysis_id}/report", api_key=api_key
        )
        assert isinstance(report, dict)
        if not raw_json:
            print_report(report)
        return 0

    if args.command == "status":
        _, payload = request_json(
            api_url, "GET", f"/v1/analyses/{args.analysis_id}", api_key=api_key
        )
        emit(payload)
        if not raw_json:
            assert isinstance(payload, dict)
            print_analysis_summary(payload)
        return 0

    if args.command == "report":
        _, report = request_json(
            api_url, "GET", f"/v1/analyses/{args.analysis_id}/report", api_key=api_key
        )
        if raw_json:
            emit(report)
        else:
            assert isinstance(report, dict)
            print_report(report)
        return 0

    if args.command == "readme":
        path = f"/v1/analyses/{args.analysis_id}/readme?style={args.style}"
        _, draft = request_json(api_url, "GET", path, api_key=api_key)
        assert isinstance(draft, dict)
        markdown = str(draft.get("markdown", ""))
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                handle.write(markdown)
            print(f"Wrote {len(markdown)} characters to {args.out} (style={args.style})")
        elif raw_json:
            emit(draft)
        else:
            print(markdown)
        return 0

    if args.command == "learning":
        _, plan = request_json(
            api_url, "GET", f"/v1/analyses/{args.analysis_id}/learning", api_key=api_key
        )
        if raw_json:
            emit(plan)
        else:
            assert isinstance(plan, dict)
            print_learning(plan)
        return 0

    if args.command == "jd":
        if args.text_file:
            try:
                with open(args.text_file, encoding="utf-8") as handle:
                    text = handle.read()
            except OSError as error:
                raise CliError(f"Cannot read {args.text_file}: {error}") from error
        else:
            text = args.text or ""
        _, alignment = request_json(
            api_url,
            "POST",
            f"/v1/analyses/{args.analysis_id}/jd-alignment",
            api_key=api_key,
            json_body={"jd_text": text},
            expected=(200,),
        )
        if raw_json:
            emit(alignment)
        else:
            assert isinstance(alignment, dict)
            print_jd_alignment(alignment)
        return 0

    if args.command == "cv":
        try:
            with open(args.file, "rb") as binary_handle:
                content = binary_handle.read()
        except OSError as error:
            raise CliError(f"Cannot read {args.file}: {error}") from error
        filename = os.path.basename(args.file)
        _, alignment = request_json(
            api_url,
            "POST",
            f"/v1/analyses/{args.analysis_id}/cv-alignment",
            api_key=api_key,
            files={"file": (filename, content)},
            expected=(200,),
        )
        if raw_json:
            emit(alignment)
        else:
            assert isinstance(alignment, dict)
            print(LINE)
            print(f"  CV ALIGNMENT  {filename}")
            print(f"  {alignment.get('suggested_summary', '')}")
            print(LINE)
            groups = [
                ("Verified by GitHub", "verified"),
                ("CV-only, unverified", "self_reported_unverified"),
            ]
            for label, status_value in groups:
                matched = [
                    skill["skill"]
                    for skill in alignment.get("skills", [])
                    if skill.get("status") == status_value
                ]
                print(f"\n{label} ({len(matched)}): {', '.join(matched) or 'none'}")
        return 0

    if args.command == "history":
        _, history = request_json(api_url, "GET", "/v1/analyses", api_key=api_key)
        if raw_json:
            emit(history)
        else:
            items = history if isinstance(history, list) else []
            print(LINE)
            print(f"  HISTORY  ({len(items)})")
            print(LINE)
            for item in items:
                assert isinstance(item, dict)
                print(
                    f"  {item.get('github_username', '?'):<20} "
                    f"{item.get('target_role', '?'):<28} {item.get('status', '?')}"
                )
                print(f"    {item.get('id')}")
        return 0

    raise CliError(f"Unknown command: {args.command}")  # pragma: no cover


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_command(args)
    except CliError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # Downstream consumers (head, less) closing the pipe are not errors.
        with open(os.devnull, "w") as devnull:
            sys.stdout = devnull
            print("", end="")
        return 0


if __name__ == "__main__":
    sys.exit(main())
