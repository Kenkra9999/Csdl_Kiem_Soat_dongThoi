from __future__ import annotations

import argparse
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg

from .db import AuctionClient, STRATEGIES, dsn_for, install, json_text


def parser():
    result = argparse.ArgumentParser(description="Đồ án 19 - thí nghiệm kiểm soát trả giá đồng thời")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="Tạo schema và dữ liệu lần đầu; từ chối ghi đè")
    commands.add_parser("list", help="Liệt kê các phiên đấu giá")
    for command in ("bid", "close"):
        p = commands.add_parser(command)
        p.add_argument("--auction", type=int, required=True)
        p.add_argument("--strategy", choices=STRATEGIES, default="row_lock")
        if command == "bid":
            p.add_argument("--bidder", type=int, required=True)
            p.add_argument("--amount", required=True)
            p.add_argument("--request-id", type=uuid.UUID)
    commands.add_parser("verify", help="Kiểm tra các bất biến CSDL")
    demo = commands.add_parser("scenario", aliases=["demo"], help="Chạy kịch bản nghiệp vụ trên một phiên mới")
    demo.add_argument("--strategy", choices=STRATEGIES, default="row_lock")
    bench = commands.add_parser("benchmark", help="Đo 4 kịch bản × 2 giao thức trên CSDL *_bench riêng")
    bench.add_argument("--workers", type=int, default=12, help="số người gửi đồng thời mỗi đợt")
    bench.add_argument("--waves", type=int, default=10, help="số đợt cho kịch bản 1, 2, 4")
    bench.add_argument("--rounds", type=int, default=3)
    bench.add_argument("--output", default="output/benchmark")
    test = commands.add_parser("test", help="Kiểm thử trên CSDL *_test riêng")
    test.add_argument("--output", default="output/test-results.json")
    commands.add_parser("oql", help="Chạy bản mô phỏng Python của truy vấn đối tượng")
    return result


def demo(strategy):
    from .fixtures import create_auction
    # Additive fixture; never reset the demonstration schema.
    auction_id = create_auction(dsn_for("owner"), seconds=4)
    client = AuctionClient()
    key = uuid.uuid4()
    events = [{"step": "Tạo phiên mới", "auction_id": auction_id, "strategy": strategy}]
    events.append({"step": "Lượt đầu", **client.bid(auction_id, 2, 100, key, strategy)})
    events.append({"step": "Gửi lại cùng UUID", **client.bid(auction_id, 2, 100, key, strategy)})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(client.bid, auction_id, bidder, 110, None, strategy) for bidder in (3, 4)]
        events.extend({"step": "Hai người cùng trả 110", **f.result()} for f in futures)
    events.append({"step": "Đóng sớm", **client.close(auction_id, strategy)})
    time.sleep(4.1)
    events.append({"step": "Đóng khi hết hạn", **client.close(auction_id, strategy)})
    events.append({"step": "Đóng lần nữa", **client.close(auction_id, strategy)})
    events.append({"step": "Kiểm tra bất biến", "checks": client.verify()})
    return events


def main(argv=None):
    # Windows redirected consoles often use cp1258, which lacks many Vietnamese
    # characters. UTF-8 also keeps JSON/text outputs portable for report generation.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        code = 0
        if args.command == "setup":
            result = install()
        elif args.command == "list":
            result = AuctionClient().auctions()
        elif args.command == "bid":
            result = AuctionClient().bid(args.auction, args.bidder, args.amount, args.request_id, args.strategy)
        elif args.command == "close":
            result = AuctionClient().close(args.auction, args.strategy)
        elif args.command == "verify":
            result = AuctionClient().verify()
            code = 0 if result and all(row["passed"] for row in result) else 1
        elif args.command in {"scenario", "demo"}:
            result = demo(args.strategy)
        elif args.command == "benchmark":
            from .benchmark import run_benchmark
            result = run_benchmark(workers=args.workers, waves=args.waves, rounds=args.rounds, output=args.output)
            # Kịch bản 4 CỐ Ý sinh lỗi, nên dùng expectation_met thay cho errors == 0.
            code = 0 if all(row["invariants_passed"] and row["expectation_met"] and not row["exhausted"]
                            for row in result["summaries"]) else 1
        elif args.command == "test":
            from .testing import run_tests
            report = run_tests(args.output)
            code = 0 if report["passed"] else 1
            result = {key: report[key] for key in ("passed", "tests_run", "failures", "errors", "skipped", "elapsed_ms")}
            result["output"] = args.output
        elif args.command == "oql":
            from .objects import object_demo
            result = object_demo()
        print(json_text(result))
        return code
    except (RuntimeError, ValueError, psycopg.Error) as exc:
        # Do not print connection strings or secrets from psycopg connection errors.
        message = exc.diag.message_primary if isinstance(exc, psycopg.Error) and exc.diag.message_primary else str(exc)
        if isinstance(exc, psycopg.OperationalError):
            message = "Không kết nối được PostgreSQL. Kiểm tra service, CSDL, tài khoản và .env."
        print(json_text({"status": "ERROR", "message": message}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
