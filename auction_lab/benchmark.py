"""Measured comparison, equal database seed + request list + worker configuration."""
from __future__ import annotations

import csv
import json
import platform
import random
import statistics
import threading
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import psycopg

from .db import AuctionClient, connect, disposable_guard, dsn_for, install
from .fixtures import create_auction


def percentile(values: list[float], q: float) -> float:
    values = sorted(values)
    if not values:
        return 0.0
    # nearest-rank percentile, explicitly documented in the resulting metadata
    import math
    return values[max(0, math.ceil(q * len(values)) - 1)]


def workload(requests: int) -> list[tuple]:
    data = []
    for index in range(requests):
        # Every 5th request resends the immediately previous payload and UUID.
        source = index - 1 if index % 5 == 4 else index
        data.append((2 + source % 20, 100 + source * 10,
                     uuid.uuid5(uuid.NAMESPACE_URL, f"auction19/benchmark/{source}")))
    random.Random(19019).shuffle(data)
    return data


def run_benchmark(*, workers: int = 12, requests: int = 60, rounds: int = 3,
                  output: str = "output/benchmark", dsn: str | None = None) -> dict:
    if workers < 2 or requests < workers or rounds < 1:
        raise ValueError("workers >= 2, requests >= workers, rounds >= 1")
    target = dsn or dsn_for("bench")
    dbname = disposable_guard(target, "bench")
    request_list = workload(requests)
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    summaries, all_samples = [], []
    with connect(target) as conn:
        environment = conn.execute("""
            SELECT version() AS postgresql, current_setting('max_connections') AS max_connections,
                   current_setting('shared_buffers') AS shared_buffers,
                   current_setting('synchronous_commit') AS synchronous_commit
        """).fetchone()
    for round_id in range(1, rounds + 1):
        # Alternate order to reduce systematic warm-cache/order bias.
        order = ("row_lock", "serializable") if round_id % 2 else ("serializable", "row_lock")
        for strategy in order:
            install(target, reset=True, purpose="bench")
            auction_id = create_auction(target)
            barrier = threading.Barrier(workers)
            client = AuctionClient(target)

            def worker(worker_id):
                samples = []
                barrier.wait(timeout=30)
                for position in range(worker_id, len(request_list), workers):
                    bidder, amount, request_id = request_list[position]
                    started = time.perf_counter()
                    try:
                        result = client.bid(auction_id, bidder, amount, request_id, strategy)
                    except psycopg.Error as exc:
                        result = {"status": "ERROR", "code": exc.sqlstate,
                                  "message": exc.diag.message_primary,
                                  "attempts": 1, "retries": 0,
                                  "latency_ms": round((time.perf_counter() - started) * 1000, 3)}
                    result.update(round=round_id, strategy=strategy, position=position,
                                  bidder_id=bidder, requested_amount=amount)
                    samples.append(result)
                return samples

            began = time.perf_counter()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                parts = list(pool.map(worker, range(workers)))
            elapsed = time.perf_counter() - began
            samples = [sample for part in parts for sample in part]
            counts = Counter(s["status"] for s in samples)
            latencies = [s["latency_ms"] for s in samples]
            checks = client.verify()
            summary = {
                "round": round_id, "strategy": strategy, "workers": workers,
                "requests": requests, "accepted": counts["ACCEPTED"],
                "replayed": counts["REPLAYED"], "rejected": counts["REJECTED"],
                "exhausted": counts["EXHAUSTED"], "errors": counts["ERROR"],
                "requests_retried": sum(s["retries"] > 0 for s in samples),
                "total_retries": sum(s["retries"] for s in samples),
                "elapsed_ms": round(elapsed * 1000, 3),
                "throughput_requests_s": round(requests / elapsed, 3),
                "latency_mean_ms": round(statistics.mean(latencies), 3),
                "latency_p50_ms": percentile(latencies, .50),
                "latency_p95_ms": percentile(latencies, .95),
                "latency_max_ms": max(latencies),
                "invariants_passed": all(c["passed"] for c in checks),
                "rejection_codes": dict(Counter(s.get("code", "") for s in samples if s["status"] == "REJECTED")),
            }
            summaries.append(summary)
            all_samples.extend(samples)
    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": dbname, "environment": {**environment, "python": platform.python_version(),
                                              "os": platform.platform(), "psycopg": psycopg.__version__},
        "method": "Equal fresh schema/seed, fixed shuffle seed 19019, same UUID/payload list and worker count; barrier starts workers; strategy order alternates per round.",
        "latency_definition": "End-to-end per request including connection, transaction, commit, all retries and backoff; queue wait before a worker begins is excluded.",
        "percentile_definition": "Nearest rank ceil(q*n), q=0.50 and 0.95",
        "limitation": "Local machine, connections are opened per attempt; measured timing and accepted order vary with OS scheduling. No claim of universal performance superiority.",
        "summaries": summaries, "samples": sorted(all_samples, key=lambda s: (s["round"], s["strategy"], s["position"])),
    }
    (output_dir / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    columns = [key for key in summaries[0] if key != "rejection_codes"]
    with (output_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows({key: row[key] for key in columns} for row in summaries)
    sample_columns = ["round", "strategy", "position", "bidder_id", "requested_amount", "status", "code", "attempts", "retries", "latency_ms", "request_id"]
    with (output_dir / "requests.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=sample_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_samples)
    return {"status": "MEASURED", "output": str(output_dir.resolve()), "summaries": summaries}
