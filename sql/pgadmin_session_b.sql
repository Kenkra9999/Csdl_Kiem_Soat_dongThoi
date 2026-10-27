-- Chạy trong lúc A đang pg_sleep(8). Cùng giá chỉ một yêu cầu được chấp nhận.
BEGIN ISOLATION LEVEL READ COMMITTED;
SELECT auction.place_bid(1,3,1000000,'19000000-2222-4222-8222-000000000001','row_lock');
COMMIT;
-- Kết quả dự kiến: BID_TOO_LOW sau khi chờ A COMMIT.
SELECT * FROM auction.bids WHERE auction_id=1 ORDER BY id;

-- Demo riêng SERIALIZABLE: bắt buộc BEGIN như dưới. Khi 40001, ROLLBACK
-- và chạy LẠI TOÀN BỘ giao dịch với cùng UUID; client Python tự làm việc này.
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT auction.place_bid(1,4,1050000,'19000000-3333-4333-8333-000000000001','serializable');
COMMIT;

-- Phiên 2 đã hết giờ: đóng rồi gọi lại để chứng minh chỉ một kết quả.
SELECT auction.close_auction(2,'row_lock');
SELECT auction.close_auction(2,'row_lock');
SELECT * FROM auction.results WHERE auction_id=2;
