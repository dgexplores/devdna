import argparse
import asyncio
import json
import math
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx2


@dataclass(frozen=True)
class LoadSummary:
    requests: int
    successful: int
    failed: int
    error_rate: float
    requests_per_second: float
    p50_ms: float
    p95_ms: float
    max_ms: float


def summarize(durations: list[float], statuses: list[int], elapsed: float) -> LoadSummary:
    ordered = sorted(durations)

    def percentile(fraction: float) -> float:
        index = max(0, math.ceil(len(ordered) * fraction) - 1)
        return ordered[index] * 1000

    successful = sum(200 <= code < 400 for code in statuses)
    return LoadSummary(
        requests=len(statuses),
        successful=successful,
        failed=len(statuses) - successful,
        error_rate=(len(statuses) - successful) / len(statuses),
        requests_per_second=len(statuses) / elapsed,
        p50_ms=percentile(0.50),
        p95_ms=percentile(0.95),
        max_ms=ordered[-1] * 1000,
    )


async def run_load(
    url: str,
    requests: int,
    concurrency: int,
    timeout: float,
    *,
    transport: httpx2.AsyncBaseTransport | None = None,
) -> LoadSummary:
    semaphore = asyncio.Semaphore(concurrency)

    async with httpx2.AsyncClient(timeout=timeout, transport=transport) as client:

        async def make_request() -> tuple[int, float]:
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    return response.status_code, time.perf_counter() - started
                except httpx2.HTTPError:
                    return 0, time.perf_counter() - started

        started = time.perf_counter()
        results = await asyncio.gather(*(make_request() for _ in range(requests)))
        elapsed = max(time.perf_counter() - started, 0.000_001)
    statuses, durations = zip(*results, strict=True)
    return summarize(list(durations), list(statuses), elapsed)


def positive_integer(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bounded DevDNA read-path load smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:8000/health/live")
    parser.add_argument("--requests", type=positive_integer, default=200)
    parser.add_argument("--concurrency", type=positive_integer, default=20)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--max-error-rate", type=float, default=0.0)
    parser.add_argument("--max-p95-ms", type=float, default=500.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.concurrency > args.requests:
        raise SystemExit("--concurrency cannot exceed --requests")
    summary = asyncio.run(
        run_load(
            args.url,
            args.requests,
            args.concurrency,
            args.timeout,
        )
    )
    payload: dict[str, Any] = asdict(summary)
    print(json.dumps(payload, sort_keys=True))
    if summary.error_rate > args.max_error_rate or summary.p95_ms > args.max_p95_ms:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
