"""Small additive fixtures; destructive resets live only behind disposable_guard."""
from __future__ import annotations

from .db import connect


def create_auction(dsn: str, *, seconds: float = 3600, opens_in: float = -3600,
                   start_price=100, bid_step=10) -> int:
    with connect(dsn) as conn:
        auction_id = conn.execute("""
            INSERT INTO auction.auctions(asset_id,start_price,bid_step,opens_at,closes_at)
            VALUES (1,%s,%s,clock_timestamp()+%s * interval '1 second',
                    clock_timestamp()+%s * interval '1 second') RETURNING id
        """, (start_price, bid_step, opens_in, seconds)).fetchone()["id"]
        conn.execute("""
            INSERT INTO auction.registrations(auction_id,user_id,status)
            SELECT %s,id,'APPROVED' FROM auction.users WHERE id BETWEEN 2 AND 21
        """, (auction_id,))
    return auction_id
