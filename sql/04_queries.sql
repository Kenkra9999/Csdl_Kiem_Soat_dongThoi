-- Q1. Phiên đang thực sự nhận giá và sắp kết thúc trong 24 giờ.
SELECT a.id,x.title,a.current_price,a.start_price,a.closes_at,
       a.closes_at-clock_timestamp() AS time_remaining
FROM auction.auctions a JOIN auction.assets x ON x.id=a.asset_id
WHERE a.status='OPEN' AND a.opens_at<=clock_timestamp()
  AND a.closes_at>clock_timestamp() AND a.closes_at<=clock_timestamp()+interval '24 hours'
ORDER BY a.closes_at;

-- Q2. Người dẫn đầu (LEFT JOIN giữ cả phiên chưa có lượt trả).
SELECT a.id,x.title,u.full_name AS leading_bidder,b.amount,a.status
FROM auction.auctions a JOIN auction.assets x ON x.id=a.asset_id
LEFT JOIN auction.bids b ON b.id=a.leading_bid_id
LEFT JOIN auction.users u ON u.id=b.bidder_id ORDER BY a.id;

-- Q3. Lịch sử và mức tăng: hàm cửa sổ LAG, ROW_NUMBER.
SELECT b.auction_id,row_number() OVER w AS bid_order,u.full_name,b.amount,
       b.amount-lag(b.amount) OVER w AS increase_from_previous,b.accepted_at,b.request_id
FROM auction.bids b JOIN auction.users u ON u.id=b.bidder_id
WINDOW w AS(PARTITION BY b.auction_id ORDER BY b.id)
ORDER BY b.auction_id,b.id;

-- Q4. Số người đăng ký/đã thực sự trả giá; không nhân bản qua JOIN N:M.
SELECT a.id,
 (SELECT count(*) FROM auction.registrations r WHERE r.auction_id=a.id AND r.status='APPROVED') AS registered_count,
 (SELECT count(DISTINCT bidder_id) FROM auction.bids b WHERE b.auction_id=a.id) AS actual_bidder_count,
 (SELECT count(*) FROM auction.bids b WHERE b.auction_id=a.id) AS bid_count
FROM auction.auctions a ORDER BY a.id;

-- Q5. Tỷ lệ thành công = phiên đóng có người thắng / mọi phiên đã đóng.
SELECT count(*) AS closed_count,count(*) FILTER(WHERE r.winning_bid_id IS NOT NULL) AS successful_count,
       round(100.0*count(*) FILTER(WHERE r.winning_bid_id IS NOT NULL)/nullif(count(*),0),2) AS success_percent
FROM auction.auctions a JOIN auction.results r ON r.auction_id=a.id WHERE a.status='CLOSED';

-- Q6. Tổng hợp cây danh mục (mọi mức): cặp ancestor-descendant.
WITH RECURSIVE category_closure(ancestor_id,descendant_id,depth) AS (
 SELECT id,id,0 FROM auction.categories
 UNION ALL
 SELECT p.ancestor_id,c.id,p.depth+1 FROM category_closure p
 JOIN auction.categories c ON c.parent_id=p.descendant_id
)
SELECT c.id,c.name,count(DISTINCT x.id) AS asset_count,count(DISTINCT a.id) AS auction_count,
       count(DISTINCT r.auction_id) FILTER(WHERE r.winning_bid_id IS NOT NULL) AS successful_count,
       coalesce(sum(b.amount),0) AS winning_value
FROM auction.categories c JOIN category_closure t ON t.ancestor_id=c.id
LEFT JOIN auction.assets x ON x.category_id=t.descendant_id
LEFT JOIN auction.auctions a ON a.asset_id=x.id
LEFT JOIN auction.results r ON r.auction_id=a.id
LEFT JOIN auction.bids b ON b.id=r.winning_bid_id
GROUP BY c.id,c.name ORDER BY c.id;

-- Q7. Bộ lọc động qua tham số typed, không nối chuỗi SQL/không SQL injection.
SELECT * FROM auction.auction_report('OPEN',1,1000000);
SELECT * FROM auction.auction_report(NULL,2,NULL);

-- Q8. Xếp hạng người trả giá; COUNT DISTINCT và DENSE_RANK.
SELECT u.id,u.full_name,count(b.id) AS accepted_bid_count,count(DISTINCT b.auction_id) AS joined_auctions,
       dense_rank() OVER(ORDER BY count(b.id) DESC) AS activity_rank
FROM auction.users u JOIN auction.bids b ON b.bidder_id=u.id GROUP BY u.id,u.full_name ORDER BY activity_rank,u.id;

-- Q9. Giá thắng là giá lượt thắng, phân biệt rõ giá khởi điểm và giá hiện tại.
SELECT a.id,x.title,a.start_price,a.current_price,b.amount AS winning_price,u.full_name AS winner,r.closed_at
FROM auction.results r JOIN auction.auctions a ON a.id=r.auction_id
JOIN auction.assets x ON x.id=a.asset_id LEFT JOIN auction.bids b ON b.id=r.winning_bid_id
LEFT JOIN auction.users u ON u.id=b.bidder_id ORDER BY a.id;

-- Q10. Chẩn đoán chờ khóa (chỉ thấy đầy đủ câu lệnh nếu role có quyền pg_monitor).
SELECT pid,application_name,state,wait_event_type,wait_event,pg_blocking_pids(pid) AS blocking_pids
FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid();

-- Q11. Kế hoạch truy vấn: dữ liệu nhỏ có thể chọn Seq Scan, đó không phải lỗi.
EXPLAIN(ANALYZE,BUFFERS)
SELECT * FROM auction.bids WHERE auction_id=4 ORDER BY amount DESC,id DESC LIMIT 1;
