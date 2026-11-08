from __future__ import annotations

import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import psycopg

from auction_lab.db import AuctionClient, connect, disposable_guard, dsn_for, install
from auction_lab.fixtures import create_auction
from auction_lab.objects import object_demo


class AuctionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = dsn_for("test")
        disposable_guard(cls.dsn, "test")
        install(cls.dsn, reset=True, purpose="test")
        cls.client = AuctionClient(cls.dsn)

    def setUp(self):
        self.auction = create_auction(self.dsn)

    def assert_invariants(self):
        checks = self.client.verify()
        self.assertTrue(checks, "Không có kiểm tra bất biến")
        self.assertTrue(all(c["passed"] for c in checks), checks)

    def expire(self, auction_id=None):
        with connect(self.dsn) as conn:
            conn.execute("UPDATE auction.auctions SET closes_at=clock_timestamp() WHERE id=%s",
                         (auction_id or self.auction,))

    def test_01_first_bid_and_price_step(self):
        result = self.client.bid(self.auction, 2, 100)
        self.assertEqual(result["status"], "ACCEPTED", result)
        for amount, code in [(100, "BID_TOO_LOW"), (115, "INVALID_INCREMENT")]:
            result = self.client.bid(self.auction, 3, amount)
            self.assertEqual(result.get("code"), code, result)
        self.assertEqual(self.client.bid(self.auction, 3, 120)["status"], "ACCEPTED")
        self.assert_invariants()

    def test_02_replay_same_uuid_does_not_duplicate(self):
        key = uuid.uuid4()
        first = self.client.bid(self.auction, 2, 100, key)
        replay = self.client.bid(self.auction, 2, 100, key)
        self.assertEqual(replay["status"], "REPLAYED", replay)
        self.assertEqual(first["bid_id"], replay["bid_id"])
        with connect(self.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) n FROM auction.bids WHERE request_id=%s", (key,)).fetchone()["n"], 1)

    def test_03_uuid_payload_conflict(self):
        key = uuid.uuid4()
        self.client.bid(self.auction, 2, 100, key)
        result = self.client.bid(self.auction, 3, 110, key)
        self.assertEqual(result["code"], "IDEMPOTENCY_CONFLICT", result)

    def test_04_replay_after_close(self):
        key = uuid.uuid4()
        first = self.client.bid(self.auction, 2, 100, key)
        self.expire()
        self.assertEqual(self.client.close(self.auction)["status"], "CLOSED")
        replay = self.client.bid(self.auction, 2, 100, key)
        self.assertEqual(replay["status"], "REPLAYED", replay)
        self.assertEqual(first["bid_id"], replay["bid_id"])

    def test_05_seller_cannot_bid(self):
        self.assertEqual(self.client.bid(self.auction, 1, 100)["code"], "SELLER_CANNOT_BID")

    def test_06_unregistered_cannot_bid(self):
        with connect(self.dsn) as conn:
            conn.execute("DELETE FROM auction.registrations WHERE auction_id=%s AND user_id=2", (self.auction,))
        self.assertEqual(self.client.bid(self.auction, 2, 100)["code"], "NOT_REGISTERED")

    def test_07_not_started_and_ended(self):
        future = create_auction(self.dsn, seconds=7200, opens_in=3600)
        self.assertEqual(self.client.bid(future, 2, 100)["code"], "NOT_STARTED")
        self.expire()
        self.assertEqual(self.client.bid(self.auction, 2, 100)["code"], "AUCTION_ENDED")

    def test_08_close_too_early(self):
        result = self.client.close(self.auction)
        self.assertEqual(result["code"], "TOO_EARLY", result)

    def test_09_close_without_bids_and_repeat(self):
        self.expire()
        first, second = self.client.close(self.auction), self.client.close(self.auction)
        self.assertEqual(first["status"], "CLOSED", first)
        self.assertEqual(second["status"], "REPLAYED", second)
        with connect(self.dsn) as conn:
            rows = conn.execute("SELECT * FROM auction.results WHERE auction_id=%s", (self.auction,)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertIsNone(rows[0]["winning_bid_id"])

    def test_10_concurrent_equal_price_one_acceptance(self):
        for strategy in ("row_lock", "serializable"):
            with self.subTest(strategy=strategy):
                auction_id = create_auction(self.dsn)
                barrier = threading.Barrier(8)
                def submit(bidder):
                    barrier.wait(timeout=20)
                    return self.client.bid(auction_id, bidder, 100, strategy=strategy)
                with ThreadPoolExecutor(max_workers=8) as pool:
                    results = list(pool.map(submit, range(2, 10)))
                self.assertEqual(sum(r["status"] == "ACCEPTED" for r in results), 1, results)
                self.assertEqual(sum(r["status"] == "REJECTED" for r in results), 7, results)
        self.assert_invariants()

    def test_11_concurrent_duplicate_request(self):
        for strategy in ("row_lock", "serializable"):
            with self.subTest(strategy=strategy):
                auction_id = create_auction(self.dsn)
                key = uuid.uuid4()
                barrier = threading.Barrier(6)
                def submit(_):
                    barrier.wait(timeout=20)
                    return self.client.bid(auction_id, 2, 100, key, strategy)
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(submit, range(6)))
                self.assertEqual(sum(r["status"] == "ACCEPTED" for r in results), 1, results)
                self.assertEqual(sum(r["status"] == "REPLAYED" for r in results), 5, results)
                self.assertEqual(len({r["bid_id"] for r in results}), 1)

    def test_12_concurrent_cross_auction_uuid_conflict(self):
        for strategy in ("row_lock", "serializable"):
            auction_ids = [create_auction(self.dsn), create_auction(self.dsn)]
            key = uuid.uuid4()
            barrier = threading.Barrier(2)
            def submit(auction_id):
                barrier.wait(timeout=20)
                return self.client.bid(auction_id, 2, 100, key, strategy)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(submit, auction_ids))
            self.assertEqual(sum(r["status"] == "ACCEPTED" for r in results), 1, results)
            self.assertEqual(sum(r.get("code") == "IDEMPOTENCY_CONFLICT" for r in results), 1, results)
        self.assert_invariants()

    def test_13_bid_close_race_and_unique_winner(self):
        for strategy in ("row_lock", "serializable"):
            with self.subTest(strategy=strategy):
                auction_id = create_auction(self.dsn)
                self.client.bid(auction_id, 2, 100, strategy=strategy)
                self.expire(auction_id)
                barrier = threading.Barrier(6)
                def submit(index):
                    barrier.wait(timeout=20)
                    return (self.client.close(auction_id, strategy) if index % 2 else
                            self.client.bid(auction_id, 3, 110, strategy=strategy))
                with ThreadPoolExecutor(max_workers=6) as pool:
                    results = list(pool.map(submit, range(6)))
                self.assertEqual(sum(r["status"] == "CLOSED" for r in results), 1, results)
                with connect(self.dsn) as conn:
                    row = conn.execute("""SELECT count(*) n, min(winning_bid_id) winner FROM auction.results WHERE auction_id=%s""", (auction_id,)).fetchone()
                    self.assertEqual(row["n"], 1)
                    self.assertIsNotNone(row["winner"])
                    self.assertEqual(conn.execute("SELECT count(*) n FROM auction.bids WHERE auction_id=%s", (auction_id,)).fetchone()["n"], 1)
        self.assert_invariants()

    def test_14_lock_wait_crosses_deadline(self):
        auction_id = create_auction(self.dsn, seconds=1.0)
        with connect(self.dsn) as holder:
            holder.execute("SELECT id FROM auction.auctions WHERE id=%s FOR UPDATE", (auction_id,))
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.client.bid, auction_id, 2, 100)
                # Confirm the bid is really blocked before crossing its deadline.
                blocked = False
                limit = time.monotonic() + 4
                while time.monotonic() < limit:
                    with connect(self.dsn) as monitor:
                        blocked = monitor.execute("""
                            SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                            WHERE datname=current_database() AND pid<>pg_backend_pid()
                              AND application_name='auction19_lab' AND wait_event_type='Lock') AS blocked
                        """).fetchone()["blocked"]
                    if blocked:
                        break
                    time.sleep(.02)
                self.assertTrue(blocked, "Không quan sát được lượt trả chờ khóa")
                time.sleep(1.05)
                holder.commit()
                result = future.result(timeout=20)
        self.assertEqual(result["code"], "AUCTION_ENDED", result)

    def test_15_fault_after_insert_rolls_back_everything(self):
        key = uuid.uuid4()
        with connect(self.dsn) as conn:
            conn.execute("""
                CREATE FUNCTION auction.test_injected_fault() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'INJECTED_AFTER_BID_INSERT'; END $$;
                CREATE TRIGGER test_fault AFTER INSERT ON auction.bids
                FOR EACH ROW EXECUTE FUNCTION auction.test_injected_fault();
            """)
        try:
            with self.assertRaises(psycopg.Error) as captured:
                self.client.bid(self.auction, 2, 100, key)
            self.assertIn("INJECTED_AFTER_BID_INSERT", str(captured.exception))
        finally:
            with connect(self.dsn) as conn:
                conn.execute("DROP TRIGGER test_fault ON auction.bids; DROP FUNCTION auction.test_injected_fault()")
        with connect(self.dsn) as conn:
            self.assertEqual(conn.execute("SELECT count(*) n FROM auction.bids WHERE request_id=%s", (key,)).fetchone()["n"], 0)
            auction = conn.execute("SELECT current_price,leading_bid_id FROM auction.auctions WHERE id=%s", (self.auction,)).fetchone()
            self.assertIsNone(auction["current_price"])
            self.assertIsNone(auction["leading_bid_id"])
        self.assertEqual(self.client.bid(self.auction, 2, 100, key)["status"], "ACCEPTED")
        self.assert_invariants()

    def test_16_serializable_requires_correct_isolation(self):
        with connect(self.dsn) as conn:
            try:
                result = conn.execute("SELECT auction.place_bid(%s::bigint,2::bigint,100::numeric,%s::uuid,'serializable') result", (self.auction, uuid.uuid4())).fetchone()["result"]
            except psycopg.Error as exc:
                self.assertIsNotNone(exc.sqlstate)
            else:
                self.assertEqual(result["status"], "REJECTED", result)

    def test_17_real_serialization_failure_retries_whole_transaction(self):
        barrier = threading.Barrier(2)
        thread_state = threading.local()
        def operation(conn):
            conn.execute("SELECT revision FROM auction.auctions WHERE id=%s", (self.auction,)).fetchone()
            if not getattr(thread_state, "crossed", False):
                thread_state.crossed = True
                barrier.wait(timeout=20)
            conn.execute("UPDATE auction.auctions SET revision=revision+1 WHERE id=%s", (self.auction,))
            return {"status": "ACCEPTED", "code": "RETRY_PROBE"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.client._run, operation, "serializable") for _ in range(2)]
            results = [f.result(timeout=30) for f in futures]
        self.assertTrue(all(r["status"] == "ACCEPTED" for r in results), results)
        self.assertGreaterEqual(sum(r["retries"] for r in results), 1, results)
        with connect(self.dsn) as conn:
            self.assertEqual(conn.execute("SELECT revision FROM auction.auctions WHERE id=%s", (self.auction,)).fetchone()["revision"], 2)

    def test_18_dynamic_report_filters(self):
        with connect(self.dsn) as conn:
            rows = conn.execute("SELECT * FROM auction.auction_report(%s::text,%s::bigint,%s::numeric)", ("OPEN", None, None)).fetchall()
            self.assertTrue(rows)
            empty = conn.execute("SELECT * FROM auction.auction_report(%s::text,%s::bigint,%s::numeric)", ("OPEN' OR 1=1 --", None, None)).fetchall()
            self.assertEqual(empty, [])

    def test_19_invalid_amount(self):
        result = self.client.bid(self.auction, 2, "-10")
        self.assertIn(result["code"], {"INVALID_AMOUNT", "BID_TOO_LOW"}, result)
        self.assertEqual(result["status"], "REJECTED")

    def test_20_missing_auction(self):
        self.assertEqual(self.client.bid(99999999, 2, 100)["code"], "AUCTION_NOT_FOUND")

    def test_21_all_final_invariants(self):
        self.assert_invariants()

    def test_22_category_cycle_is_rejected(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.dsn) as conn:
                parent = conn.execute("INSERT INTO auction.categories(name) VALUES ('test-cycle-parent') RETURNING id").fetchone()["id"]
                child = conn.execute("INSERT INTO auction.categories(parent_id,name) VALUES (%s,'test-cycle-child') RETURNING id", (parent,)).fetchone()["id"]
                conn.execute("UPDATE auction.categories SET parent_id=%s WHERE id=%s", (child, parent))

    def test_23_total_subtype_is_enforced_at_commit(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.dsn) as conn:
                conn.execute("""INSERT INTO auction.assets(seller_id,category_id,kind,title)
                             SELECT seller_id,category_id,'ARTWORK','Missing subtype test'
                             FROM auction.assets WHERE id=1""")

    def test_24_disjoint_subtype_is_enforced(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.dsn) as conn:
                conn.execute("INSERT INTO auction.collectibles(asset_id,origin,rarity) VALUES (1,'test','test')")

    def test_25_history_is_immutable(self):
        bid = self.client.bid(self.auction, 2, 100)
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.dsn) as conn:
                conn.execute("DELETE FROM auction.bids WHERE id=%s", (bid["bid_id"],))
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.dsn) as conn:
                conn.execute("UPDATE auction.audit_log SET details='{}'::jsonb WHERE auction_id=%s", (self.auction,))

    def test_26_app_role_cannot_bypass_functions(self):
        from psycopg.conninfo import conninfo_to_dict, make_conninfo
        source = os.getenv("APP_DATABASE_URL")
        if not source:
            self.skipTest("APP_DATABASE_URL chưa cấu hình")
        app_dsn = make_conninfo(source, dbname=conninfo_to_dict(self.dsn)["dbname"])
        client = AuctionClient(app_dsn)
        self.assertEqual(client.bid(self.auction, 2, 100)["status"], "ACCEPTED")
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            with connect(app_dsn) as conn:
                conn.execute("UPDATE auction.auctions SET current_price=0 WHERE id=%s", (self.auction,))
        self.assertTrue(all(c["passed"] for c in client.verify()))

    def test_27_business_rejection_is_not_cached(self):
        key = uuid.uuid4()
        with connect(self.dsn) as conn:
            conn.execute("UPDATE auction.registrations SET status='REVOKED' WHERE auction_id=%s AND user_id=2", (self.auction,))
        self.assertEqual(self.client.bid(self.auction, 2, 100, key)["code"], "NOT_REGISTERED")
        with connect(self.dsn) as conn:
            conn.execute("UPDATE auction.registrations SET status='APPROVED' WHERE auction_id=%s AND user_id=2", (self.auction,))
        self.assertEqual(self.client.bid(self.auction, 2, 100, key)["status"], "ACCEPTED")

    def test_28_mixed_protocols_still_one_equal_price_winner(self):
        barrier = threading.Barrier(6)
        def submit(index):
            barrier.wait(timeout=20)
            return self.client.bid(self.auction, 2+index, 100,
                                   strategy="row_lock" if index % 2 else "serializable")
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(submit, range(6)))
        self.assertEqual(sum(r["status"] == "ACCEPTED" for r in results), 1, results)
        self.assertEqual(sum(r["status"] == "REJECTED" for r in results), 5, results)
        self.assert_invariants()

    def test_29_nonfinite_and_fractional_cents_rejected(self):
        for amount in ("NaN", "Infinity", "-Infinity", "100.001"):
            with self.subTest(amount=amount):
                self.assertEqual(self.client.bid(self.auction, 2, amount)["code"], "INVALID_AMOUNT")

    def test_30_subtype_primary_key_move_cannot_orphan_old_asset(self):
        with self.assertRaises(psycopg.errors.CheckViolation):
            with connect(self.dsn) as conn:
                replacement = conn.execute("""
                    INSERT INTO auction.assets(seller_id,category_id,kind,title)
                    SELECT seller_id,category_id,kind,'Subtype move regression'
                    FROM auction.assets WHERE id=1 RETURNING id
                """).fetchone()["id"]
                conn.execute("UPDATE auction.artworks SET asset_id=%s WHERE asset_id=1", (replacement,))

    def test_31_category_edit_rejects_repeatable_read_snapshot(self):
        with self.assertRaises(psycopg.Error) as captured:
            with connect(self.dsn, autocommit=True) as conn:
                with conn.transaction():
                    conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                    conn.execute("INSERT INTO auction.categories(name) VALUES ('Repeatable read mutation regression')")
        self.assertEqual(captured.exception.sqlstate, "25001")

    def test_32_close_waits_for_predeadline_uncommitted_bid(self):
        """A valid bid holding the write right wins even if COMMIT follows cutoff."""
        for strategy in ("row_lock", "serializable"):
            with self.subTest(strategy=strategy):
                auction_id = create_auction(self.dsn, seconds=2.0)
                bid_ready = threading.Event()
                release_bid = threading.Event()
                close_started = threading.Event()
                accepted = {}

                def held_bid():
                    try:
                        with connect(self.dsn, autocommit=True) as conn:
                            with conn.transaction():
                                conn.execute("SET TRANSACTION ISOLATION LEVEL " +
                                             ("SERIALIZABLE" if strategy == "serializable" else "READ COMMITTED"))
                                result = conn.execute("""
                                    SELECT auction.place_bid(%s::bigint,2::bigint,
                                        100::numeric,%s::uuid,%s::text) AS result
                                """, (auction_id, uuid.uuid4(), strategy)).fetchone()["result"]
                                accepted.update(result)
                                bid_ready.set()
                                if not release_bid.wait(timeout=15):
                                    raise TimeoutError("Test không giải phóng giao dịch trả giá")
                        return result
                    finally:
                        bid_ready.set()

                def closing():
                    close_started.set()
                    return self.client.close(auction_id, strategy)

                with ThreadPoolExecutor(max_workers=2) as pool:
                    bid_future = pool.submit(held_bid)
                    close_future = None
                    try:
                        self.assertTrue(bid_ready.wait(timeout=10))
                        if bid_future.done():
                            bid_future.result()  # Surface an early database failure.
                        self.assertEqual(accepted.get("status"), "ACCEPTED", accepted)
                        # Use the server clock to cross the exact cutoff while the
                        # accepted bid remains uncommitted and holds the row lock.
                        with connect(self.dsn) as monitor:
                            monitor.execute("""
                                SELECT pg_sleep(GREATEST(0,extract(epoch FROM
                                    (closes_at-clock_timestamp()))))
                                FROM auction.auctions WHERE id=%s
                            """, (auction_id,)).fetchone()
                        close_future = pool.submit(closing)
                        self.assertTrue(close_started.wait(timeout=5))
                        blocked = False
                        limit = time.monotonic() + 5
                        while time.monotonic() < limit:
                            with connect(self.dsn) as monitor:
                                blocked = monitor.execute("""
                                    SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                                    WHERE datname=current_database() AND pid<>pg_backend_pid()
                                      AND application_name='auction19_lab'
                                      AND wait_event_type='Lock'
                                      AND query LIKE 'SELECT auction.close_auction%%') AS blocked
                                """).fetchone()["blocked"]
                            if blocked:
                                break
                            if close_future.done():
                                break
                            time.sleep(.02)
                        self.assertTrue(blocked, "Đóng phiên phải chờ giao dịch trả giá chưa commit")
                        self.assertFalse(close_future.done())
                    finally:
                        release_bid.set()
                    committed_bid = bid_future.result(timeout=20)
                    closed = close_future.result(timeout=20)
                self.assertEqual(closed["status"], "CLOSED", closed)
                self.assertEqual(closed["winning_bid_id"], committed_bid["bid_id"])
                if strategy == "serializable":
                    # Its first snapshot predates the bid commit; the competing
                    # UPDATE must fail serialization, then retry the whole close.
                    self.assertGreaterEqual(closed["retries"], 1, closed)
                with connect(self.dsn) as conn:
                    winner = conn.execute("SELECT winning_bid_id FROM auction.results WHERE auction_id=%s", (auction_id,)).fetchone()
                    self.assertEqual(winner["winning_bid_id"], committed_bid["bid_id"])
                self.assert_invariants()


    def test_33_equal_amount_is_blocked_by_candidate_key(self):
        """Ngay cả khi đi vòng qua place_bid, CSDL không nhận hai lượt cùng giá/phiên."""
        self.assertEqual(self.client.bid(self.auction, 2, 100)["status"], "ACCEPTED")
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with connect(self.dsn) as conn:
                conn.execute("""
                    INSERT INTO auction.bids(auction_id,bidder_id,amount,request_id)
                    VALUES (%s,3,100,%s)
                """, (self.auction, uuid.uuid4()))

    def test_34_one_open_auction_per_asset(self):
        with connect(self.dsn) as conn:
            asset_id = conn.execute("SELECT asset_id FROM auction.auctions WHERE id=%s",
                                    (self.auction,)).fetchone()["asset_id"]
        insert = """
            INSERT INTO auction.auctions(asset_id,start_price,bid_step,opens_at,closes_at)
            VALUES (%s,100,10,clock_timestamp(),clock_timestamp()+interval '1 hour') RETURNING id
        """
        with self.assertRaises(psycopg.errors.UniqueViolation):
            with connect(self.dsn) as conn:
                conn.execute(insert, (asset_id,))
        # Sau khi phiên cũ đóng, tài sản được đưa ra đấu giá lại.
        self.expire()
        self.assertEqual(self.client.close(self.auction)["status"], "CLOSED")
        with connect(self.dsn) as conn:
            self.assertIsNotNone(conn.execute(insert, (asset_id,)).fetchone()["id"])
        self.assert_invariants()

    def test_35_dynamic_report_combines_category_tree_and_price(self):
        def ids(*args):
            with connect(self.dsn) as conn:
                return {row["auction_id"] for row in conn.execute(
                    "SELECT * FROM auction.auction_report(%s::text,%s::bigint,%s::numeric)", args)}
        everything = ids(None, None, None)
        self.assertEqual(ids(None, 1, None), everything)          # gốc = cả cây
        self.assertIn(3, ids(None, 6, None))                      # Điện tử > Máy ảnh
        self.assertNotIn(1, ids(None, 6, None))                   # tranh không thuộc nhánh điện tử
        closed = ids("CLOSED", None, None)
        self.assertTrue({4, 5} <= closed and 1 not in closed, closed)
        self.assertEqual(ids(None, None, 10**9), set())           # không phiên nào >= 1 tỷ
        self.assertEqual(ids("CLOSED", 2, 2_000_000), {4})        # 3 bộ lọc cùng lúc

    def test_36_upgrade_script_is_idempotent(self):
        upgrade = (Path(__file__).resolve().parents[1] / "sql" / "07_nang_cap.sql").read_text(encoding="utf-8")
        with connect(self.dsn, autocommit=True) as conn:
            conn.execute(upgrade)
            conn.execute(upgrade)
            present = conn.execute("""
                SELECT to_regclass('auction.auctions_one_open_per_asset') IS NOT NULL AS idx,
                       EXISTS(SELECT 1 FROM pg_constraint WHERE conname='bids_auction_id_amount_key') AS uniq
            """).fetchone()
        self.assertTrue(present["idx"] and present["uniq"], present)


class PurePythonTests(unittest.TestCase):
    def test_disposable_guard_protects_demo(self):
        for dsn in ("postgresql://x@localhost/auction19_demo", "dbname=postgres"):
            with self.assertRaises(ValueError):
                disposable_guard(dsn, "test")

    def test_disposable_guard_accepts_test_suffix(self):
        self.assertEqual(disposable_guard("dbname=safe_auction_test", "test"), "safe_auction_test")

    def test_object_queries(self):
        result = object_demo()
        self.assertEqual(result["artwork_auction_ids"], [1])
        self.assertEqual(result["auction_1_leader"]["amount"], "120")
        self.assertIsNone(result["empty_auction_leader"])
