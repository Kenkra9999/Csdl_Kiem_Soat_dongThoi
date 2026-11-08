"""Thực nghiệm so sánh hai giao thức trên CÙNG dữ liệu và CÙNG cấu hình.

Đo đúng bốn kịch bản của đề bài (bước 7). Với mỗi vòng (round) và mỗi giao
thức, schema được tạo lại từ seed; danh sách yêu cầu (người trả, số tiền, UUID)
được sinh tất định nên hai giao thức nhận đúng cùng một tải.

  S1 dong_thoi   W người cùng trả CÙNG mức giá tối thiểu, lặp `waves` đợt.
                 Kỳ vọng: mỗi đợt đúng 1 ACCEPTED, W-1 REJECTED (BID_TOO_LOW).
  S2 gui_lai     W bản sao của CÙNG một yêu cầu (cùng UUID, cùng nội dung) gửi
                 đồng thời, lặp `waves` đợt.
                 Kỳ vọng: mỗi đợt 1 ACCEPTED, W-1 REPLAYED, không có lượt trùng.
  S3 dong_phien  W-1 người trả giá liên tục theo đợt trong khi 1 luồng đóng
                 phiên đúng lúc hết hạn.
                 Kỳ vọng: đúng 1 kết quả, người thắng = lượt cao nhất đã chấp
                 nhận, không lượt nào được chấp nhận từ giờ đóng trở đi.
  S4 loi_giua    Trigger thử nghiệm ném lỗi NGAY SAU khi ghi lượt trả giá, trước
                 khi cập nhật giá hiện tại; W người gửi đồng thời, `waves` đợt.
                 Kỳ vọng: mọi yêu cầu lỗi, không còn lượt/nhật ký/giá dở dang.

Mỗi worker giữ MỘT kết nối suốt vòng đo, nên độ trễ là thời gian giao dịch
(gồm chờ khóa, thử lại, backoff), không gồm thời gian mở kết nối TCP/xác thực.
"""
from __future__ import annotations

import csv
import json
import math
import platform
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

START_PRICE, BID_STEP = 100, 10
END_CODES = {"AUCTION_ENDED", "NOT_OPEN"}
SCENARIOS = {
    "dong_thoi": "Nhiều người cùng trả một mức giá",
    "gui_lai": "Gửi lại cùng một yêu cầu",
    "dong_phien": "Trả giá cạnh tranh với đóng phiên",
    "loi_giua": "Lỗi sau khi ghi lượt, trước khi cập nhật giá",
}
FAULT_SQL = """
    CREATE FUNCTION auction.bench_injected_fault() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'INJECTED_AFTER_BID_INSERT'; END $$;
    CREATE TRIGGER bench_fault AFTER INSERT ON auction.bids
    FOR EACH ROW EXECUTE FUNCTION auction.bench_injected_fault();
"""


def percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile: phần tử thứ ceil(q*n) của dãy đã sắp xếp."""
    values = sorted(values)
    return values[max(0, math.ceil(q * len(values)) - 1)] if values else 0.0


def amount_for(wave: int) -> int:
    return START_PRICE + wave * BID_STEP


def request_key(scenario: str, round_id: int, wave: int, worker: int) -> uuid.UUID:
    """UUID tất định: hai giao thức nhận đúng cùng danh sách yêu cầu."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"auction19/bench/{scenario}/{round_id}/{wave}/{worker}")


class Bench:
    """Một vòng đo cho một giao thức: W kết nối giữ suốt bốn kịch bản."""

    def __init__(self, target: str, strategy: str, round_id: int, workers: int, waves: int):
        self.target, self.strategy, self.round_id = target, strategy, round_id
        self.workers, self.waves = workers, waves
        self.client = AuctionClient(target)
        self.connections = [connect(target, autocommit=True) for _ in range(workers)]

    def close(self):
        for conn in self.connections:
            conn.close()

    def bid(self, worker: int, auction_id: int, bidder: int, amount: int, key: uuid.UUID) -> dict:
        started = time.perf_counter()
        try:
            result = self.client.bid(auction_id, bidder, amount, key, self.strategy,
                                     conn=self.connections[worker])
        except psycopg.Error as exc:     # lỗi không thử lại được (vd. lỗi cài cố ý ở S4)
            result = {"status": "ERROR", "code": exc.sqlstate, "message": exc.diag.message_primary,
                      "attempts": 1, "retries": 0,
                      "latency_ms": round((time.perf_counter() - started) * 1000, 3)}
        result.update(bidder_id=bidder, requested_amount=amount, request_id=str(key))
        return result

    def waves_in_parallel(self, plan) -> list[dict]:
        """plan(wave, worker) -> (auction_id, bidder, amount, uuid). Mọi worker
        xuất phát cùng lúc ở mỗi đợt nhờ Barrier, tạo cạnh tranh thật."""
        barrier = threading.Barrier(self.workers)

        def worker(index):
            samples = []
            for wave in range(self.waves):
                barrier.wait(timeout=60)
                sample = self.bid(index, *plan(wave, index))
                samples.append({**sample, "wave": wave})
            return samples

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            return [s for part in pool.map(worker, range(self.workers)) for s in part]

    # ---- S1 ---------------------------------------------------------------
    def dong_thoi(self) -> tuple[list[dict], dict]:
        auction_id = create_auction(self.target, start_price=START_PRICE, bid_step=BID_STEP)
        samples = self.waves_in_parallel(lambda wave, w: (
            auction_id, 2 + w, amount_for(wave), request_key("dong_thoi", self.round_id, wave, w)))
        per_wave = Counter(s["wave"] for s in samples if s["status"] == "ACCEPTED")
        ok = all(per_wave[w] == 1 for w in range(self.waves))
        return samples, {"expectation_met": ok,
                         "expectation": "Mỗi đợt đúng 1 lượt được nhận"}

    # ---- S2 ---------------------------------------------------------------
    def gui_lai(self) -> tuple[list[dict], dict]:
        auction_id = create_auction(self.target, start_price=START_PRICE, bid_step=BID_STEP)
        # Cùng (người, số tiền, UUID) cho cả W worker trong một đợt.
        samples = self.waves_in_parallel(lambda wave, w: (
            auction_id, 2 + wave % 20, amount_for(wave), request_key("gui_lai", self.round_id, wave, 0)))
        with self.connections[0].cursor() as cur:
            stored = cur.execute("SELECT count(*) AS n FROM auction.bids WHERE auction_id=%s",
                                 (auction_id,)).fetchone()["n"]
        counts = Counter(s["status"] for s in samples)
        ok = (stored == self.waves and counts["ACCEPTED"] == self.waves
              and counts["REPLAYED"] == self.waves * (self.workers - 1))
        return samples, {"expectation_met": ok, "stored_bids": stored,
                         "expectation": "Mỗi UUID tạo đúng 1 lượt; các bản sao trả REPLAYED"}

    # ---- S3 ---------------------------------------------------------------
    def dong_phien(self, deadline_s: float = 1.0) -> tuple[list[dict], dict]:
        auction_id = create_auction(self.target, seconds=deadline_s,
                                    start_price=START_PRICE, bid_step=BID_STEP)
        bidders = self.workers - 1
        barrier = threading.Barrier(bidders)
        stop = threading.Event()

        def bidder(index):
            samples, wave = [], 0
            while True:
                barrier.wait(timeout=60)
                if stop.is_set():          # mọi worker cùng thấy cờ sau Barrier
                    return samples
                sample = self.bid(index, auction_id, 2 + index, amount_for(wave),
                                  request_key("dong_phien", self.round_id, wave, index))
                samples.append({**sample, "wave": wave})
                if sample.get("code") in END_CODES:
                    stop.set()
                wave += 1

        def closer():
            conn = self.connections[-1]
            conn.execute("""SELECT pg_sleep(GREATEST(0, extract(epoch FROM closes_at - clock_timestamp())))
                            FROM auction.auctions WHERE id=%s""", (auction_id,))
            started = time.perf_counter()
            while True:
                result = self.client.close(auction_id, self.strategy, conn=conn)
                if result.get("code") != "TOO_EARLY":
                    result["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
                    return result
                time.sleep(0.002)

        with ThreadPoolExecutor(max_workers=self.workers) as pool:
            closing = pool.submit(closer)
            parts = list(pool.map(bidder, range(bidders)))
            closed = closing.result(timeout=120)
        samples = [s for part in parts for s in part]
        accepted = [s for s in samples if s["status"] == "ACCEPTED"]
        top = max(accepted, key=lambda s: s["requested_amount"], default=None)
        with self.connections[0].cursor() as cur:
            row = cur.execute("""
                SELECT (SELECT count(*) FROM auction.results WHERE auction_id=a.id) AS results,
                       (SELECT winning_bid_id FROM auction.results WHERE auction_id=a.id) AS winner,
                       (SELECT count(*) FROM auction.bids WHERE auction_id=a.id
                          AND accepted_at >= a.closes_at) AS late_bids
                FROM auction.auctions a WHERE a.id=%s
            """, (auction_id,)).fetchone()
        ok = (closed["status"] == "CLOSED" and row["results"] == 1 and row["late_bids"] == 0
              and row["winner"] == (top["bid_id"] if top else None))
        return samples, {"expectation_met": ok,
                         "close_status": closed["status"], "close_retries": closed["retries"],
                         "close_latency_ms": closed["latency_ms"],
                         "winning_bid_id": row["winner"], "late_bids": row["late_bids"],
                         "expectation": "1 kết quả, thắng = lượt cao nhất, 0 lượt sau hạn"}

    # ---- S4 ---------------------------------------------------------------
    def loi_giua(self) -> tuple[list[dict], dict]:
        auction_id = create_auction(self.target, start_price=START_PRICE, bid_step=BID_STEP)
        with connect(self.target) as conn:
            conn.execute(FAULT_SQL)
        try:
            samples = self.waves_in_parallel(lambda wave, w: (
                auction_id, 2 + w, START_PRICE, request_key("loi_giua", self.round_id, wave, w)))
        finally:
            with connect(self.target) as conn:
                conn.execute("DROP TRIGGER bench_fault ON auction.bids;"
                             "DROP FUNCTION auction.bench_injected_fault()")
        with self.connections[0].cursor() as cur:
            row = cur.execute("""
                SELECT a.current_price, a.leading_bid_id, a.revision,
                       (SELECT count(*) FROM auction.bids b WHERE b.auction_id=a.id) AS bids,
                       (SELECT count(*) FROM auction.audit_log l WHERE l.auction_id=a.id) AS audits
                FROM auction.auctions a WHERE a.id=%s
            """, (auction_id,)).fetchone()
        ok = (all(s["status"] == "ERROR" for s in samples) and row["bids"] == 0
              and row["audits"] == 0 and row["current_price"] is None and row["revision"] == 0)
        return samples, {"expectation_met": ok, "leftover_bids": row["bids"],
                         "leftover_audit": row["audits"], "revision_after": row["revision"],
                         "expectation": "Mọi yêu cầu lỗi; 0 lượt, 0 nhật ký, giá vẫn NULL"}


def summarize(samples: list[dict], elapsed: float) -> dict:
    counts = Counter(s["status"] for s in samples)
    latencies = [s["latency_ms"] for s in samples] or [0.0]
    return {
        "requests": len(samples), "accepted": counts["ACCEPTED"], "replayed": counts["REPLAYED"],
        "rejected": counts["REJECTED"], "errors": counts["ERROR"], "exhausted": counts["EXHAUSTED"],
        "requests_retried": sum(s.get("retries", 0) > 0 for s in samples),
        "total_retries": sum(s.get("retries", 0) for s in samples),
        "elapsed_ms": round(elapsed * 1000, 3),
        "throughput_requests_s": round(len(samples) / elapsed, 3) if elapsed else 0.0,
        "latency_mean_ms": round(statistics.mean(latencies), 3),
        "latency_p50_ms": percentile(latencies, .50),
        "latency_p95_ms": percentile(latencies, .95),
        "latency_max_ms": max(latencies),
        "rejection_codes": dict(Counter(s.get("code", "") for s in samples if s["status"] == "REJECTED")),
    }


def run_benchmark(*, workers: int = 12, waves: int = 10, rounds: int = 3,
                  output: str = "output/benchmark", dsn: str | None = None) -> dict:
    if workers < 3 or waves < 1 or rounds < 1:
        raise ValueError("workers >= 3, waves >= 1, rounds >= 1")
    target = dsn or dsn_for("bench")
    dbname = disposable_guard(target, "bench")
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    with connect(target) as conn:
        environment = conn.execute("""
            SELECT version() AS postgresql, current_setting('max_connections') AS max_connections,
                   current_setting('shared_buffers') AS shared_buffers,
                   current_setting('synchronous_commit') AS synchronous_commit
        """).fetchone()

    summaries, all_samples = [], []
    for round_id in range(1, rounds + 1):
        # Đảo thứ tự giao thức giữa các vòng để giảm thiên lệch "chạy trước/sau".
        order = ("row_lock", "serializable") if round_id % 2 else ("serializable", "row_lock")
        for strategy in order:
            install(target, reset=True, purpose="bench")       # cùng dữ liệu xuất phát
            bench = Bench(target, strategy, round_id, workers, waves)
            try:
                for scenario in SCENARIOS:
                    began = time.perf_counter()
                    samples, extra = getattr(bench, scenario)()
                    elapsed = time.perf_counter() - began
                    checks = bench.client.verify()
                    summary = {"round": round_id, "strategy": strategy, "scenario": scenario,
                               "workers": workers, **summarize(samples, elapsed),
                               "invariants_passed": all(c["passed"] for c in checks), **extra}
                    summaries.append(summary)
                    all_samples.extend({**s, "round": round_id, "strategy": strategy,
                                        "scenario": scenario} for s in samples)
            finally:
                bench.close()

    report = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": dbname,
        "environment": {**environment, "python": platform.python_version(),
                        "os": platform.platform(), "psycopg": psycopg.__version__},
        "scenarios": SCENARIOS,
        "method": ("Mỗi vòng × giao thức: tạo lại schema từ seed; UUID/người/số tiền sinh tất định nên "
                   "hai giao thức nhận cùng danh sách yêu cầu; Barrier cho mọi worker xuất phát cùng lúc; "
                   "thứ tự giao thức đảo giữa các vòng."),
        "latency_definition": ("Từ lúc gọi tới khi COMMIT xong, gồm chờ khóa, mọi lần thử lại và backoff; "
                               "mỗi worker giữ một kết nối nên KHÔNG gồm thời gian mở kết nối."),
        "percentile_definition": "Nearest rank ceil(q*n), q=0.50 và 0.95",
        "limitation": "Máy cục bộ; thứ tự thực thi phụ thuộc bộ lập lịch HĐH. Không suy ra ưu thế tốc độ phổ quát.",
        "summaries": summaries,
        "samples_file": "requests.csv",       # từng yêu cầu nằm ở CSV, không lặp trong JSON
    }
    (output_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    columns = ["round", "strategy", "scenario", "workers", "requests", "accepted", "replayed",
               "rejected", "errors", "exhausted", "requests_retried", "total_retries",
               "elapsed_ms", "throughput_requests_s", "latency_mean_ms", "latency_p50_ms",
               "latency_p95_ms", "latency_max_ms", "invariants_passed", "expectation_met"]
    with (output_dir / "summary.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)
    sample_columns = ["round", "strategy", "scenario", "wave", "bidder_id", "requested_amount",
                      "status", "code", "attempts", "retries", "latency_ms", "request_id"]
    with (output_dir / "requests.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=sample_columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_samples)
    return {"status": "MEASURED", "output": str(output_dir.resolve()), "summaries": summaries}
