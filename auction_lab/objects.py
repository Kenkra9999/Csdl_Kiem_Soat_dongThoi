"""Object model and executable Python equivalents of the OQL in docs.

PostgreSQL does not execute ODMG OQL. This module is an explicitly labelled
Python simulation; it does not pretend SQL or comprehensions are an OQL engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class TaiSan:
    ma: int
    ten: str


@dataclass(frozen=True)
class TacPhamNgheThuat(TaiSan):
    hoa_si: str


@dataclass(frozen=True)
class DoSuuTam(TaiSan):
    xuat_xu: str


@dataclass(frozen=True)
class ThietBiDienTu(TaiSan):
    hang: str


@dataclass(frozen=True)
class NguoiThamGia:
    ma: int
    ho_ten: str


@dataclass(frozen=True)
class LuotTraGia:
    ma: int
    nguoi_tra: NguoiThamGia
    gia: Decimal


@dataclass(frozen=True)
class KetQuaDauGia:
    luot_thang: LuotTraGia | None


@dataclass
class PhienDauGia:
    ma: int
    tai_san: TaiSan
    nguoi_ban: NguoiThamGia
    luot_tra: list[LuotTraGia] = field(default_factory=list)
    ket_qua: KetQuaDauGia | None = None

    def nguoi_dan_dau(self):
        return max(self.luot_tra, key=lambda bid: bid.gia, default=None)


def object_demo() -> dict:
    seller = NguoiThamGia(1, "Người bán mẫu")
    bidders = [NguoiThamGia(2, "An"), NguoiThamGia(3, "Bình")]
    auctions = [
        PhienDauGia(1, TacPhamNgheThuat(1, "Tranh mùa thu", "Họa sĩ mẫu"), seller,
                    [LuotTraGia(1, bidders[0], Decimal("100")), LuotTraGia(2, bidders[1], Decimal("120"))]),
        PhienDauGia(2, ThietBiDienTu(2, "Máy ảnh", "Hãng mẫu"), bidders[0]),
        PhienDauGia(3, DoSuuTam(3, "Tem cổ", "Việt Nam"), seller),
    ]
    art = [p for p in auctions if isinstance(p.tai_san, TacPhamNgheThuat)]
    leader = auctions[0].nguoi_dan_dau()
    return {"engine": "Python simulation of object queries; not an ODMG OQL runtime",
            "artwork_auction_ids": [p.ma for p in art],
            "auction_1_history": [{"bid": b.ma, "bidder": b.nguoi_tra.ho_ten, "amount": str(b.gia)} for b in auctions[0].luot_tra],
            "auction_1_leader": {"name": leader.nguoi_tra.ho_ten, "amount": str(leader.gia)},
            "empty_auction_leader": auctions[2].nguoi_dan_dau(),
            "user_2_roles": "Người trả giá ở phiên 1, người bán ở phiên 2"}
