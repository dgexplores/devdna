import asyncio

import httpx2

from devdna.load_smoke import run_load, summarize


def test_load_summary_calculates_success_and_percentiles() -> None:
    summary = summarize(
        durations=[0.010, 0.020, 0.030, 0.040],
        statuses=[200, 200, 503, 204],
        elapsed=0.100,
    )

    assert summary.requests == 4
    assert summary.successful == 3
    assert summary.failed == 1
    assert summary.error_rate == 0.25
    assert summary.requests_per_second == 40
    assert summary.p50_ms == 20
    assert summary.p95_ms == 40


def test_load_runner_uses_bounded_request_count() -> None:
    calls = 0

    def respond(_: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(200)

    summary = asyncio.run(
        run_load(
            "https://devdna.test/health/live",
            requests=12,
            concurrency=3,
            timeout=1,
            transport=httpx2.MockTransport(respond),
        )
    )

    assert calls == 12
    assert summary.successful == 12
    assert summary.failed == 0
