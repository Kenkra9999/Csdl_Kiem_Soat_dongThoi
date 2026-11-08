"""Read models and bounded actions for the local auction interface.

No schema or business rule is duplicated here: bids and closing always use the
existing AuctionClient and PostgreSQL functions. The only owner operation is an
additive experiment fixture in the explicitly guarded *_test database.
"""
from __future__ import annotations

import json
import re
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from psycopg.types.json import set_json_loads

from .db import AuctionClient, ROOT, STRATEGIES, connect, disposable_guard, dsn_for, install
from .fixtures import create_auction


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def json_default(value):
    if isinstance(value, Decimal):
        return format(value, 'f')
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    raise TypeError(f'Unsupported JSON value: {type(value).__name__}')


def encoded_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=json_default).encode('utf-8')


def precise_connect(dsn):
    connection = connect(dsn)
    set_json_loads(lambda value: json.loads(value, parse_float=Decimal), connection)
    return connection


class ExactMoneyClient(AuctionClient):
    """Retain AuctionClient's transaction path with a connection-local decoder."""
    def _run(self, operation, strategy, conn=None):
        def precise_operation(connection):
            set_json_loads(lambda value: json.loads(value, parse_float=Decimal), connection)
            return operation(connection)
        result = super()._run(precise_operation, strategy, conn)
        for key in ('amount', 'minimum', 'winning_price'):
            if result.get(key) is not None:
                result[key] = format(result[key], 'f') if isinstance(result[key], Decimal) else str(result[key])
        return result


def positive_integer(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 9223372036854775807:
        raise ApiError('INVALID_INPUT', f'{field} phải là số nguyên dương hợp lệ.')
    return value


def strategy_from(payload: dict) -> str:
    strategy = payload.get('strategy', 'row_lock')
    if strategy not in STRATEGIES:
        raise ApiError('INVALID_INPUT', 'Chọn cơ chế khóa dòng hoặc SERIALIZABLE.')
    return strategy


# Aggregates are independent correlated subqueries: joining registrations and
# bids directly would multiply both counts when there are several of each.
AUCTION_SELECT = """
SELECT a.id,a.asset_id,x.title,x.description,x.kind,c.name AS category_name,
       seller.full_name AS seller_name,a.status,
       CASE WHEN a.status='CLOSED' THEN 'CLOSED'
            WHEN clock_timestamp()<a.opens_at THEN 'UPCOMING'
            WHEN clock_timestamp()>=a.closes_at THEN 'ENDED' ELSE 'LIVE' END AS state,
       a.start_price,a.bid_step,a.current_price,
       CASE WHEN a.current_price IS NULL THEN a.start_price
            ELSE a.current_price+a.bid_step END AS minimum_bid,
       a.opens_at,a.closes_at,a.leading_bid_id,leader.bidder_id AS leading_bidder_id,
       leading_user.full_name AS leading_bidder_name,
       (SELECT count(*) FROM auction.registrations rg
        WHERE rg.auction_id=a.id AND rg.status='APPROVED') AS participant_count,
       (SELECT count(*) FROM auction.bids b WHERE b.auction_id=a.id) AS bid_count,
       result.winning_bid_id,winning_bid.amount AS winning_price,
       winner.full_name AS winner_name
FROM auction.auctions a JOIN auction.assets x ON x.id=a.asset_id
JOIN auction.categories c ON c.id=x.category_id
JOIN auction.users seller ON seller.id=x.seller_id
LEFT JOIN auction.bids leader ON leader.id=a.leading_bid_id
LEFT JOIN auction.users leading_user ON leading_user.id=leader.bidder_id
LEFT JOIN auction.results result ON result.auction_id=a.id
LEFT JOIN auction.bids winning_bid ON winning_bid.id=result.winning_bid_id
LEFT JOIN auction.users winner ON winner.id=winning_bid.bidder_id
"""


class AuctionWebService:
    def __init__(self, app_dsn: str | None = None, test_dsn: str | None = None,
                 web_root: Path | None = None, result_root: Path | None = None):
        self.app_dsn = app_dsn or dsn_for('app')
        self.test_dsn = test_dsn  # Resolve lazily: ordinary pages need no test DB.
        self.client = ExactMoneyClient(self.app_dsn)
        self.web_root = (web_root or ROOT / 'web').resolve()
        self.result_root = (result_root or ROOT / 'output').resolve()
        self.csrf_token = secrets.token_urlsafe(32)
        self.experiment_lock = threading.Lock()

    def health(self):
        with precise_connect(self.app_dsn) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            exists = conn.execute("SELECT to_regprocedure('auction.place_bid(bigint,bigint,numeric,uuid,text)') IS NOT NULL AS ready").fetchone()
            if not exists['ready']:
                raise RuntimeError('CSDL chưa cài đặt. Chạy python -m auction_lab setup trước.')

    @staticmethod
    def server_time(conn):
        return conn.execute('SELECT clock_timestamp() AS now').fetchone()['now']

    def bootstrap(self):
        with precise_connect(self.app_dsn) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            return {
                'server_time': self.server_time(conn),
                'users': conn.execute('SELECT id,full_name FROM auction.users ORDER BY id').fetchall(),
                'categories': conn.execute('SELECT id,parent_id,name FROM auction.categories ORDER BY id').fetchall(),
                'summary': conn.execute("""
                    SELECT (SELECT count(*) FROM auction.auctions) AS total_auctions,
                           (SELECT count(*) FROM auction.auctions WHERE status='OPEN'
                            AND opens_at<=clock_timestamp() AND closes_at>clock_timestamp()) AS live_auctions,
                           (SELECT count(*) FROM auction.auctions WHERE status='CLOSED') AS closed_auctions,
                           (SELECT count(*) FROM auction.bids) AS total_bids
                """).fetchone(),
                'csrf_token': self.csrf_token,
            }

    def auctions(self, query: dict):
        search = query.get('search', '').strip()
        state, kind, sort = query.get('state', 'ALL'), query.get('kind', 'ALL'), query.get('sort', 'ending')
        if len(search) > 200:
            raise ApiError('INVALID_INPUT', 'Từ khóa tìm kiếm tối đa 200 ký tự.')
        if state not in {'ALL', 'LIVE', 'UPCOMING', 'ENDED', 'CLOSED'}:
            raise ApiError('INVALID_INPUT', 'Trạng thái phiên không hợp lệ.')
        if kind not in {'ALL', 'ARTWORK', 'COLLECTIBLE', 'ELECTRONIC'}:
            raise ApiError('INVALID_INPUT', 'Loại tài sản không hợp lệ.')
        order = {'ending': "CASE state WHEN 'LIVE' THEN 0 WHEN 'UPCOMING' THEN 1 WHEN 'ENDED' THEN 2 ELSE 3 END,closes_at,id",
                 'newest': 'id DESC', 'price': 'coalesce(current_price,start_price) DESC,id DESC'}.get(sort)
        if not order:
            raise ApiError('INVALID_INPUT', 'Cách sắp xếp không hợp lệ.')
        # ORDER BY is selected from a fixed map; all user data is bound.
        with precise_connect(self.app_dsn) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            rows = conn.execute('SELECT * FROM (' + AUCTION_SELECT + """
                ) q WHERE (%s='ALL' OR state=%s) AND (%s='ALL' OR kind=%s)
                AND (%s='' OR strpos(lower(title),lower(%s))>0
                     OR strpos(lower(category_name),lower(%s))>0)
                ORDER BY """ + order, (state, state, kind, kind, search, search, search)).fetchall()
            return {'items': rows, 'server_time': self.server_time(conn)}

    def detail(self, auction_id: int):
        with precise_connect(self.app_dsn) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            auction = conn.execute(AUCTION_SELECT + ' WHERE a.id=%s', (auction_id,)).fetchone()
            if auction is None:
                raise ApiError('NOT_FOUND', 'Không tìm thấy phiên đấu giá.', 404)
            return {
                'auction': auction,
                'bids': conn.execute("""
                    SELECT b.id,b.bidder_id,u.full_name AS bidder_name,b.amount,b.request_id,b.accepted_at
                    FROM auction.bids b JOIN auction.users u ON u.id=b.bidder_id
                    WHERE b.auction_id=%s ORDER BY b.id DESC
                """, (auction_id,)).fetchall(),
                'participants': conn.execute("""
                    SELECT u.id,u.full_name FROM auction.registrations r JOIN auction.users u ON u.id=r.user_id
                    WHERE r.auction_id=%s AND r.status='APPROVED' ORDER BY u.id
                """, (auction_id,)).fetchall(),
                'audit': conn.execute("""
                    SELECT l.id,l.action,u.full_name AS actor_name,l.occurred_at,l.details
                    FROM auction.audit_log l LEFT JOIN auction.users u ON u.id=l.actor_id
                    WHERE l.auction_id=%s ORDER BY l.id DESC
                """, (auction_id,)).fetchall(),
                'server_time': self.server_time(conn),
            }

    def bid(self, auction_id: int, payload: dict):
        bidder = positive_integer(payload.get('bidder_id'), 'Người tham gia')
        amount = payload.get('amount')
        if not isinstance(amount, str) or not re.fullmatch(r'-?\d{1,18}(?:\.\d{1,8})?', amount):
            raise ApiError('INVALID_INPUT', 'Giá trả phải là chuỗi số thập phân hợp lệ.')
        try:
            value = Decimal(amount)
        except InvalidOperation:
            raise ApiError('INVALID_INPUT', 'Giá trả không hợp lệ.') from None
        if not value.is_finite():
            raise ApiError('INVALID_INPUT', 'Giá trả phải là số hữu hạn.')
        try:
            key = uuid.UUID(payload.get('request_id', ''))
        except (ValueError, TypeError, AttributeError):
            raise ApiError('INVALID_INPUT', 'Mã yêu cầu UUID không hợp lệ.') from None
        return self.client.bid(auction_id, bidder, amount, key, strategy_from(payload))

    def close(self, auction_id: int, payload: dict):
        return self.client.close(auction_id, strategy_from(payload))

    def checks(self):
        return {'checks': self.client.verify(), 'checked_at': datetime.now(timezone.utc)}

    def latest_experiments(self):
        tests_path = self.result_root / 'test-results.json'
        bench_path = self.result_root / 'benchmark/results.json'
        output = {}
        for label, path, keys in (
            ('tests', tests_path, ('passed', 'tests_run', 'failures', 'errors', 'skipped', 'elapsed_ms', 'measured_at_utc')),
            ('benchmark', bench_path, ('measured_at_utc', 'environment', 'summaries')),
        ):
            try:
                raw = json.loads(path.read_text(encoding='utf-8-sig'))
                output[label] = {key: raw[key] for key in keys if key in raw}
            except (FileNotFoundError, OSError, ValueError):
                output[label] = None
        return output

    def race(self, payload: dict):
        strategy = strategy_from(payload)
        workers = payload.get('workers', 8)
        if isinstance(workers, bool) or not isinstance(workers, int) or not 2 <= workers <= 12:
            raise ApiError('INVALID_INPUT', 'Số người tham gia thực nghiệm phải từ 2 đến 12.')
        if not self.experiment_lock.acquire(blocking=False):
            raise ApiError('EXPERIMENT_BUSY', 'Một thực nghiệm đang chạy. Vui lòng đợi hoàn tất.', 409)
        started = time.perf_counter()
        try:
            dsn = self.test_dsn or dsn_for('test')
            database = disposable_guard(dsn, 'test')
            with connect(dsn) as conn:
                present = conn.execute("SELECT to_regnamespace('auction') IS NOT NULL AS present").fetchone()['present']
            if not present:
                install(dsn)
            auction_id = create_auction(dsn, seconds=3600)
            barrier = threading.Barrier(workers)
            client = ExactMoneyClient(dsn)
            def submit(index):
                barrier.wait(timeout=30)
                return {'bidder_id': index + 2,
                        **client.bid(auction_id, index + 2, '100', uuid.uuid4(), strategy)}
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(submit, range(workers)))
            return {
                'strategy': strategy, 'workers': workers, 'auction_id': auction_id, 'database': database,
                'accepted': sum(r['status'] == 'ACCEPTED' for r in results),
                'rejected': sum(r['status'] == 'REJECTED' for r in results),
                'replayed': sum(r['status'] == 'REPLAYED' for r in results),
                'retries': sum(r['retries'] for r in results),
                'latency_ms': round((time.perf_counter()-started)*1000, 3),
                'results': results, 'checks': client.verify(),
                'message': f'{workers} người cùng trả 100 trong CSDL thực nghiệm riêng; CSDL vận hành không bị thay đổi.',
            }
        finally:
            self.experiment_lock.release()
