"""Benchmarks behind the numbers in the README.

    python -m pomorie.bench latency --rate 20 --seconds 60   # live load through the API
    python -m pomorie.bench dbt                              # stage timings + test pass rate

Latency is measured end to end: from the API accepting a report (received_at, set by the
API) to the case being routed (processed_at, set by Postgres when the processor writes
the report). Both clocks are on the same machine.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from pomorie.contracts import categories
from pomorie.db import connect
from pomorie.generator.world import build_world
from pomorie.reference.paths import REPO_ROOT


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def latency(api: str, rate: float, seconds: float, seed: int = 7) -> dict[str, Any]:
    rng = random.Random(seed)
    world = build_world(42)
    with httpx.Client(base_url=api, timeout=10) as client:
        reporters = [
            client.post(
                "/reporters", json={"display_name": "bench", "email": f"bench{i}@example.org"}
            ).json()["reporter_id"]
            for i in range(50)
        ]

    def send(_: int) -> tuple[str, float]:
        lat, lon = world.point_near(rng, "street")
        report = {
            "reporter_id": rng.choice(reporters),
            "category": rng.choice(categories()),
            "lat": lat,
            "lon": lon,
            "accuracy_m": 8,
        }
        start = time.perf_counter()
        response = httpx.post(f"{api}/reports", data={"report": json.dumps(report)}, timeout=10)
        response.raise_for_status()
        return response.json()["event_id"], (time.perf_counter() - start) * 1000

    total = int(rate * seconds)
    sent: list[tuple[str, float]] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = []
        for i in range(total):
            # Open-loop load: requests are scheduled at a fixed rate, not after each reply.
            delay = started + i / rate - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            futures.append(pool.submit(send, i))
        sent = [f.result() for f in futures]
    elapsed = time.perf_counter() - started

    event_ids = [event_id for event_id, _ in sent]
    deadline = time.monotonic() + 60
    with connect(autocommit=True) as conn:
        while True:
            rows = conn.execute(
                "SELECT extract(epoch FROM processed_at - received_at) * 1000"
                " FROM ops.reports WHERE report_id = ANY(%s)",
                [event_ids],
            ).fetchall()
            if len(rows) == len(event_ids) or time.monotonic() > deadline:
                break
            time.sleep(1)
    e2e = [float(r[0]) for r in rows]
    api_ms = [ms for _, ms in sent]
    return {
        "requests": total,
        "target_rate_per_s": rate,
        "achieved_rate_per_s": round(total / elapsed, 1),
        "routed": len(e2e),
        "api_ms": {
            "p50": round(_percentile(api_ms, 0.5), 1),
            "p95": round(_percentile(api_ms, 0.95), 1),
        },
        "submitted_to_routed_ms": {
            "p50": round(_percentile(e2e, 0.5), 1),
            "p95": round(_percentile(e2e, 0.95), 1),
            "p99": round(_percentile(e2e, 0.99), 1),
            "mean": round(statistics.fmean(e2e), 1),
        }
        if e2e
        else None,
    }


def dbt_results() -> dict[str, Any]:
    """Summarise dbt/target/run_results.json from the last ``dbt build``."""
    results = json.loads((REPO_ROOT / "dbt" / "target" / "run_results.json").read_text("utf-8"))
    nodes = results["results"]
    tests = [n for n in nodes if n["unique_id"].startswith("test.")]
    models = [n for n in nodes if n["unique_id"].startswith(("model.", "snapshot."))]
    slowest = sorted(models, key=lambda n: n["execution_time"], reverse=True)[:5]
    return {
        "elapsed_s": round(results["elapsed_time"], 1),
        "models_and_snapshots": len(models),
        "tests": len(tests),
        "tests_passed": sum(n["status"] == "pass" for n in tests),
        "test_pass_rate": round(sum(n["status"] == "pass" for n in tests) / len(tests), 4),
        "slowest_models_s": {
            n["unique_id"].split(".")[-1]: round(n["execution_time"], 2) for n in slowest
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a benchmark and print JSON.")
    sub = parser.add_subparsers(dest="command", required=True)
    lat = sub.add_parser("latency", help="live load through the API")
    lat.add_argument("--api", default="http://localhost:8000")
    lat.add_argument("--rate", type=float, default=20)
    lat.add_argument("--seconds", type=float, default=60)
    sub.add_parser("dbt", help="summarise the last dbt build")
    args = parser.parse_args()
    if args.command == "latency":
        result = latency(args.api, args.rate, args.seconds)
    else:
        result = dbt_results()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
