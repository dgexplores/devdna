import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx2 as httpx2_lib
import pytest

from devdna import cli

ANALYSIS_ID = "11111111-2222-3333-4444-555555555555"


def monkeypatch_setattr(target: object, name: str, value: Any) -> None:
    """setattr without mypy signature checks (test transport injection)."""
    setattr(target, name, value)


class FakeApi:
    """Programmable stand-in for the DevDNA API used by the CLI."""

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, str]] = []

    def _handler(self) -> Callable[[httpx2_lib.Request], httpx2_lib.Response]:
        def handler(request: httpx2_lib.Request) -> httpx2_lib.Response:
            key = (request.method, request.url.path)
            self.calls.append(key)
            payload = self.responses.get(key)
            if payload is None:
                return httpx2_lib.Response(404, json={"detail": "not found"})
            status, body = payload
            return httpx2_lib.Response(status, json=body)

        return handler

    def call(self, argv: list[str], monkeypatch: pytest.MonkeyPatch | None) -> int:
        handler = self._handler()

        def fake_request(method: str, url: str, **kwargs: Any) -> httpx2_lib.Response:
            kwargs.pop("timeout", None)
            request = httpx2_lib.Request(method, url, **kwargs)
            response = handler(request)
            response.request = request
            return response

        original_request = httpx2_lib.request
        monkeypatch_setattr(httpx2_lib, "request", fake_request)
        try:
            return cli.main(argv)
        finally:
            monkeypatch_setattr(httpx2_lib, "request", original_request)


def completed_analysis() -> dict[str, Any]:
    return {
        "id": ANALYSIS_ID,
        "github_username": "octocat",
        "target_role": "python_backend_developer",
        "status": "completed",
        "error_message": None,
    }


def report_payload() -> dict[str, Any]:
    return {
        "alignment_label": "Foundational role alignment",
        "requirements_met": 1,
        "requirements_total": 7,
        "collection_status": "completed",
        "warning": None,
        "strengths": [
            {
                "title": "Project documentation",
                "summary": "Docs are present.",
                "sources": [{"repository": "octocat/backend", "path": "README.md"}],
            }
        ],
        "gaps": [{"title": "Automated testing", "explanation": "No tests found."}],
        "actions": [
            {
                "priority": 1,
                "title": "Add a test suite",
                "requirement": "automated_testing",
                "evidence_needed": ["tests directory with runnable tests"],
            }
        ],
    }


def test_health_reports_ready(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi({("GET", "/health/ready"): (200, {"status": "ready", "checks": {}})})
    exit_code = api.call(["--api-url", "http://test", "health"], None)
    capsys.readouterr()
    assert exit_code == 0


def test_health_reports_degraded(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi({("GET", "/health/ready"): (503, {"status": "not_ready"})})
    exit_code = api.call(["--api-url", "http://test", "--json", "health"], None)
    output = capsys.readouterr().out
    assert exit_code == 1
    assert json.loads(output)["status"] == "not_ready"


def test_analyze_wait_prints_report(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeApi(
        {
            ("POST", "/v1/analyses"): (202, {**completed_analysis(), "status": "queued"}),
            ("GET", f"/v1/analyses/{ANALYSIS_ID}"): (
                200,
                {**completed_analysis(), "status": "completed"},
            ),
            ("GET", f"/v1/analyses/{ANALYSIS_ID}/report"): (200, report_payload()),
        }
    )
    monkeypatch.setattr(cli, "POLL_INTERVAL_SECONDS", 0)
    exit_code = api.call(
        ["--api-url", "http://test", "analyze", "octocat", "--wait", "--timeout", "5"],
        monkeypatch,
    )
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "ROLE FIT" in output
    assert "VERIFIED STRENGTHS (1)" in output
    assert "+ Project documentation" in output


def test_jd_command_posts_text_and_renders_backlog(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jd_file = tmp_path / "jd.txt"
    jd_file.write_text("Requires Python, FastAPI, Docker.", encoding="utf-8")
    alignment = {
        "verified_count": 1,
        "requirements_considered": 3,
        "suggested_summary": "Partial fit.",
        "skills": [
            {
                "skill": "Python",
                "mentions": 1,
                "status": "verified",
                "evidence_sources": [{"repository": "octocat/backend", "path": "pyproject.toml"}],
            },
            {"skill": "FastAPI", "mentions": 1, "status": "unverified", "evidence_sources": []},
            {
                "skill": "Container delivery",
                "mentions": 1,
                "status": "unverified",
                "evidence_sources": [],
            },
        ],
    }
    api = FakeApi({("POST", f"/v1/analyses/{ANALYSIS_ID}/jd-alignment"): (200, alignment)})
    exit_code = api.call(
        ["--api-url", "http://test", "jd", ANALYSIS_ID, "--text-file", str(jd_file)],
        monkeypatch,
    )
    assert exit_code == 0
    assert any(key[1].endswith("/jd-alignment") for key in api.calls)
    output = capsys.readouterr().out
    assert "JD FIT" in output
    assert "PREPARATION BACKLOG (2)" in output
    assert "FastAPI" in output


def test_readme_writes_markdown_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    draft = {"markdown": "# Hello\n\nEvidence-backed.", "style": "badges"}
    api = FakeApi({("GET", f"/v1/analyses/{ANALYSIS_ID}/readme"): (200, draft)})
    target = tmp_path / "README.md"
    exit_code = api.call(
        [
            "--api-url",
            "http://test",
            "readme",
            ANALYSIS_ID,
            "--style",
            "badges",
            "--out",
            str(target),
        ],
        monkeypatch,
    )
    assert exit_code == 0
    assert target.read_text(encoding="utf-8").startswith("# Hello")


def test_cv_command_renders_verified_split(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    cv_file = tmp_path / "cv.docx"
    cv_file.write_bytes(b"PK")
    alignment = {
        "source_filename": "cv.docx",
        "suggested_summary": "Mostly verified.",
        "skills": [
            {"skill": "Python", "status": "verified"},
            {"skill": "Kubernetes", "status": "self_reported_unverified"},
        ],
    }
    api = FakeApi({("POST", f"/v1/analyses/{ANALYSIS_ID}/cv-alignment"): (200, alignment)})
    exit_code = api.call(
        ["--api-url", "http://test", "cv", ANALYSIS_ID, str(cv_file)],
        monkeypatch,
    )
    assert exit_code == 0
    assert "CV ALIGNMENT" in capsys.readouterr().out


def test_api_failure_returns_exit_code_one(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeApi({})
    exit_code = api.call(["--api-url", "http://test", "report", ANALYSIS_ID], None)
    capsys.readouterr()
    assert exit_code == 1


def test_json_flag_prints_raw_payload(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeApi({("GET", f"/v1/analyses/{ANALYSIS_ID}"): (200, completed_analysis())})
    exit_code = api.call(
        ["--api-url", "http://test", "--json", "status", ANALYSIS_ID],
        monkeypatch,
    )
    assert exit_code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["github_username"] == "octocat"


def test_history_lists_analyses(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    api = FakeApi({("GET", "/v1/analyses"): (200, [completed_analysis()])})
    exit_code = api.call(["--api-url", "http://test", "history"], monkeypatch)
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "HISTORY  (1)" in output
    assert "octocat" in output
