"""Small additive fixtures; destructive resets live only behind disposable_guard."""
from __future__ import annotations

from .db import connect


def create_auction(dsn: str, *, seconds: float = 3600, opens_in: float = -3600,
                   start_price=100, bid_step=10) -> int:
    """Tạo một phiên mới trên một tài sản MỚI và duyệt người dùng 2..21.

    Mỗi phiên cần tài sản riêng vì CSDL cấm một tài sản nằm trong hai phiên
    đang mở (chỉ mục auctions_one_open_per_asset). Tài sản là tác phẩm nghệ
    thuật của người bán 1; tài sản + lớp con được chèn trong cùng giao dịch để
    trigger kiểm tra chuyên biệt hóa (DEFERRED) thấy đủ cả hai khi COMMIT.
    """
    with connect(dsn) as conn:
        asset_id = conn.execute("""
            INSERT INTO auction.assets(seller_id, category_id, kind, title, description)
            VALUES (1, 3, 'ARTWORK', 'Tài sản thử nghiệm', 'Tạo tự động cho kịch bản/kiểm thử')
            RETURNING id
        """).fetchone()["id"]
        conn.execute("""
            INSERT INTO auction.artworks(asset_id, artist, material)
            VALUES (%s, 'Họa sĩ giả lập', 'Sơn dầu')
        """, (asset_id,))
        auction_id = conn.execute("""
            INSERT INTO auction.auctions(asset_id, start_price, bid_step, opens_at, closes_at)
            VALUES (%s, %s, %s,
                    clock_timestamp() + %s * interval '1 second',
                    clock_timestamp() + %s * interval '1 second')
            RETURNING id
        """, (asset_id, start_price, bid_step, opens_in, seconds)).fetchone()["id"]
        conn.execute("""
            INSERT INTO auction.registrations(auction_id, user_id, status)
            SELECT %s, id, 'APPROVED' FROM auction.users WHERE id BETWEEN 2 AND 21
        """, (auction_id,))
    return auction_id
