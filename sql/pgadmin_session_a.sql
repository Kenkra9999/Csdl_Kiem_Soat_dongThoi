-- Mở hai Query Tool nối CÙNG auction19_demo. Chọn/chạy TỪNG KHỐI.
-- Dùng phiên 1, nếu đã có giá cao thì điều chỉnh amount theo truy vấn đầu.
SELECT id,start_price,bid_step,current_price,closes_at FROM auction.auctions WHERE id=1;

-- A1: giữ khóa phiên 8 giây để nhìn thấy B chờ. COMMIT sau khi hàm kết thúc.
BEGIN ISOLATION LEVEL READ COMMITTED;
SELECT id FROM auction.auctions WHERE id=1 FOR UPDATE;
SELECT pg_sleep(8);
SELECT auction.place_bid(1,2,1000000,'19000000-1111-4111-8111-000000000001','row_lock');
COMMIT;

-- A2: replay cùng UUID và payload, không tạo thêm bid.
SELECT auction.place_bid(1,2,1000000,'19000000-1111-4111-8111-000000000001','row_lock');
SELECT * FROM auction.verify_invariants();
