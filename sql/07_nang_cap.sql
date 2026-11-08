-- =====================================================================
-- ĐỀ TÀI 19 - 07_nang_cap.sql: NÂNG CẤP CSDL ĐÃ CÀI BẢN CŨ
-- Dùng cho auction19_demo đã có dữ liệu (không xóa, không cài lại).
-- Chạy bằng tài khoản sở hữu schema (auction19_owner), theo thứ tự:
--   1. sql/07_nang_cap.sql      (tệp này, chạy lại nhiều lần vẫn an toàn)
--   2. sql/01_schema.sql        (thay trigger/hàm kiểm tra bằng bản dễ đọc)
--   3. sql/02_functions.sql     (thay place_bid/close_auction/báo cáo)
--   4. sql/06_permissions.sql   (nếu có tài khoản auction19_app)
-- CSDL mới cài bằng "python -m auction_lab setup" KHÔNG cần tệp này.
-- =====================================================================
BEGIN;

-- 1. Khóa ứng viên (auction_id, amount) cho lượt trả giá.
--    Dữ liệu cũ luôn tăng nghiêm ngặt trong mỗi phiên nên không thể trùng.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'bids_auction_id_amount_key'
                     AND conrelid = 'auction.bids'::regclass) THEN
        ALTER TABLE auction.bids
            ADD CONSTRAINT bids_auction_id_amount_key UNIQUE (auction_id, amount);
    END IF;
END $$;
-- Chỉ mục cũ (auction_id, amount DESC, id DESC) nay trùng chức năng với khóa trên.
DROP INDEX IF EXISTS auction.bids_auction_price_idx;

-- 2. Một tài sản không được nằm trong hai phiên đang mở.
--    Nếu dữ liệu cũ đã vi phạm (ví dụ do chạy lệnh scenario bản cũ bị ngắt),
--    chỉ báo danh sách để xử lý tay, không tự sửa dữ liệu nghiệp vụ.
DO $$
DECLARE
    v_conflicts text;
BEGIN
    SELECT string_agg(format('tài sản %s: phiên %s', asset_id, auction_ids), '; ')
    INTO v_conflicts
    FROM (SELECT asset_id, string_agg(id::text, ',' ORDER BY id) AS auction_ids
          FROM auction.auctions WHERE status = 'OPEN'
          GROUP BY asset_id HAVING count(*) > 1) d;

    IF v_conflicts IS NOT NULL THEN
        RAISE WARNING 'Chưa tạo auctions_one_open_per_asset vì có nhiều phiên mở cho cùng tài sản: %. '
                      'Đóng các phiên thừa bằng auction.close_auction khi đã hết hạn rồi chạy lại tệp này.',
                      v_conflicts;
    ELSE
        CREATE UNIQUE INDEX IF NOT EXISTS auctions_one_open_per_asset
            ON auction.auctions(asset_id) WHERE status = 'OPEN';
    END IF;
END $$;

-- 3. txid_current() thuộc nhóm hàm đã lỗi thời trong PostgreSQL 18.
ALTER TABLE auction.audit_log
    ALTER COLUMN transaction_id SET DEFAULT (pg_current_xact_id()::text)::bigint;

COMMIT;
