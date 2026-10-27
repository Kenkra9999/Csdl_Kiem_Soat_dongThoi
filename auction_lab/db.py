"""Connection, atomic operations and bounded whole-transaction retries.

Credentials stay in .env/environment. A failed serialization is retried from BEGIN,
never from the last statement; the same UUID is kept throughout all attempts.
"""
from __future__ import annotations

import json
import os
import random
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Callable

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
STRATEGIES = ("row_lock", "serializable")
RETRYABLE = {"40001", "40P01"}


def dsn_for(purpose: str = "app") -> str:
    key = {"app": "APP_DATABASE_URL", "owner": "DATABASE_URL",
           "test": "TEST_DATABASE_URL", "bench": "BENCH_DATABASE_URL"}[purpose]
    value = os.getenv(key)
    if purpose == "app" and not value:
        value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError(f"Chưa cấu hình {key}. Sao chép .env.example thành .env và điền kết nối.")
    return value


def connect(dsn: str | None = None, *, autocommit: bool = False):
    return psycopg.connect(dsn or dsn_for(), row_factory=dict_row,
                           autocommit=autocommit, connect_timeout=10,
                           application_name="auction19_lab")


def disposable_guard(dsn: str, purpose: str) -> str:
    """Only allow schema reset in an explicitly named disposable database."""
    name = conninfo_to_dict(dsn).get("dbname", "")
    if purpose not in {"test", "bench"} or not name.endswith("_" + purpose):
        raise ValueError(f"Từ chối xóa schema: CSDL phải có hậu tố _{purpose}.")
    demo = os.getenv("DATABASE_URL")
    if demo and conninfo_to_dict(demo).get("dbname") == name:
        raise ValueError("CSDL thực nghiệm không được trùng CSDL demo.")
    return name


def install(dsn: str | None = None, *, reset: bool = False,
            purpose: str | None = None) -> dict:
    """Install once, or explicitly recreate only a guarded disposable schema."""
    target = dsn or dsn_for("owner")
    if reset:
        disposable_guard(target, purpose or "")
    # Each SQL file contains its own explicit BEGIN/COMMIT boundary.
    with connect(target, autocommit=True) as conn:
        exists = conn.execute("SELECT to_regnamespace('auction') IS NOT NULL AS present").fetchone()["present"]
        if exists and not reset:
            raise RuntimeError("Schema auction đã tồn tại. Không ghi đè dữ liệu; dùng lệnh list/verify.")
        if reset:
            conn.execute("DROP SCHEMA IF EXISTS auction CASCADE")
        for filename in ("01_schema.sql", "02_functions.sql", "03_seed.sql"):
            conn.execute((ROOT / "sql" / filename).read_text(encoding="utf-8"))
        role_exists = conn.execute("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='auction19_app') AS present").fetchone()["present"]
        permissions = ROOT / "sql" / "06_permissions.sql"
        if role_exists and permissions.exists():
            conn.execute(permissions.read_text(encoding="utf-8"))
    return {"status": "INSTALLED", "database": conninfo_to_dict(target).get("dbname")}


class AuctionClient:
    def __init__(self, dsn: str | None = None, *, max_attempts: int = 12,
                 base_backoff: float = 0.005):
        self.dsn = dsn or dsn_for()
        if max_attempts < 1 or base_backoff < 0:
            raise ValueError("max_attempts >= 1 và base_backoff >= 0")
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff

    def _run(self, operation: Callable, strategy: str) -> dict:
        if strategy not in STRATEGIES:
            raise ValueError("strategy phải là row_lock hoặc serializable")
        begin = time.perf_counter()
        last_code = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with connect(self.dsn, autocommit=True) as conn:
                    with conn.transaction():
                        conn.execute("SET TRANSACTION ISOLATION LEVEL " +
                                     ("SERIALIZABLE" if strategy == "serializable" else "READ COMMITTED"))
                        conn.execute("SET LOCAL lock_timeout = '15s'")
                        conn.execute("SET LOCAL statement_timeout = '20s'")
                        result = operation(conn)
                # Success is counted only after COMMIT returns successfully.
                result = dict(result)
                result.update(attempts=attempt, retries=attempt - 1,
                              latency_ms=round((time.perf_counter() - begin) * 1000, 3))
                return result
            except psycopg.Error as exc:
                last_code = exc.sqlstate
                if exc.sqlstate not in RETRYABLE:
                    raise
                if attempt < self.max_attempts:
                    delay = min(self.base_backoff * (2 ** (attempt - 1)), 0.25)
                    time.sleep(delay * random.uniform(0.5, 1.5))
        return {"status": "EXHAUSTED", "code": last_code, "attempts": self.max_attempts,
                "retries": self.max_attempts - 1,
                "latency_ms": round((time.perf_counter() - begin) * 1000, 3)}

    def bid(self, auction_id: int, bidder_id: int, amount,
            request_id=None, strategy: str = "row_lock") -> dict:
        request_id = uuid.UUID(str(request_id)) if request_id else uuid.uuid4()
        amount = Decimal(str(amount))
        result = self._run(lambda conn: conn.execute(
            "SELECT auction.place_bid(%s::bigint,%s::bigint,%s::numeric,%s::uuid,%s::text) AS result",
            (auction_id, bidder_id, amount, request_id, strategy)).fetchone()["result"], strategy)
        result["request_id"] = str(request_id)
        return result

    def close(self, auction_id: int, strategy: str = "row_lock") -> dict:
        return self._run(lambda conn: conn.execute(
            "SELECT auction.close_auction(%s::bigint,%s::text) AS result",
            (auction_id, strategy)).fetchone()["result"], strategy)

    def verify(self) -> list[dict]:
        with connect(self.dsn) as conn:
            return conn.execute("SELECT * FROM auction.verify_invariants()").fetchall()

    def auctions(self) -> list[dict]:
        with connect(self.dsn) as conn:
            return conn.execute("""
                SELECT a.id, x.title, a.status, a.start_price, a.bid_step,
                       a.current_price, a.leading_bid_id, a.opens_at, a.closes_at,
                       count(b.id) AS accepted_bids
                FROM auction.auctions a JOIN auction.assets x ON x.id=a.asset_id
                LEFT JOIN auction.bids b ON b.auction_id=a.id
                GROUP BY a.id,x.title ORDER BY a.id
            """).fetchall()


def json_text(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)
