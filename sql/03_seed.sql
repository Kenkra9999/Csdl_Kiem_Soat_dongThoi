-- Dữ liệu giả lập. ON CONFLICT không ghi đè lượt trả giá bạn đã demo.
BEGIN;
INSERT INTO auction.users(id,full_name,email) VALUES
(1,'Nguyễn Minh An','seller01@example.test'),
(2,'Trần Bảo Bình','bidder02@example.test'),
(3,'Lê Hải Châu','bidder03@example.test'),
(4,'Phạm Đức Dũng','bidder04@example.test') ON CONFLICT(id) DO NOTHING;
INSERT INTO auction.users(id,full_name,email)
SELECT i,'Người tham gia '||i,'bidder'||i||'@example.test' FROM generate_series(5,21) i
ON CONFLICT(id) DO NOTHING;
INSERT INTO auction.categories(id,parent_id,name) VALUES
(1,NULL,'Tài sản đấu giá'),(2,1,'Nghệ thuật'),(3,2,'Tranh sơn dầu'),
(4,1,'Sưu tầm'),(5,4,'Tiền xu'),(6,1,'Điện tử'),(7,6,'Máy ảnh')
ON CONFLICT(id) DO NOTHING;
INSERT INTO auction.assets(id,seller_id,category_id,kind,title,description) VALUES
(1,1,3,'ARTWORK','Tranh Bình minh trên biển','Tranh giả lập để demo trả giá đồng thời'),
(2,1,5,'COLLECTIBLE','Bộ tiền xu kỷ niệm','Dữ liệu giả lập, không định giá thương mại'),
(3,1,7,'ELECTRONIC','Máy ảnh Mirrorless A','Tài sản giả lập để demo phiên chưa mở'),
(4,1,3,'ARTWORK','Tranh Phố mùa thu','Phiên lịch sử đã bán thành công'),
(5,2,7,'ELECTRONIC','Ống kính 50mm','Người dùng 2 là người bán ở phiên này'),
(6,1,5,'COLLECTIBLE','Tem bưu chính cổ','Phiên đóng không có người trả giá')
ON CONFLICT(id) DO NOTHING;
INSERT INTO auction.artworks(asset_id,artist,material,creation_year) VALUES
(1,'Họa sĩ giả lập A','Sơn dầu',2024),(4,'Họa sĩ giả lập B','Sơn dầu',2023)
ON CONFLICT(asset_id) DO NOTHING;
INSERT INTO auction.collectibles(asset_id,origin,rarity,production_year) VALUES
(2,'Bộ sưu tập giả lập','Hiếm',1990),(6,'Bộ sưu tập giả lập','Phổ thông',1980)
ON CONFLICT(asset_id) DO NOTHING;
INSERT INTO auction.electronics(asset_id,brand,model,serial_number,condition) VALUES
(3,'DemoCam','M100','DEMO-CAM-003','Đã sử dụng, hoạt động tốt'),
(5,'DemoLens','50F18','DEMO-LENS-005','Mới') ON CONFLICT(asset_id) DO NOTHING;
INSERT INTO auction.auctions(id,asset_id,start_price,bid_step,opens_at,closes_at,status,current_price,leading_bid_id) VALUES
(1,1,1000000,50000,clock_timestamp()-interval '1 day',clock_timestamp()+interval '7 days','OPEN',NULL,NULL),
(2,2,500000,25000,clock_timestamp()-interval '2 days',clock_timestamp()-interval '1 hour','OPEN',NULL,NULL),
(3,3,5000000,100000,clock_timestamp()+interval '1 day',clock_timestamp()+interval '3 days','OPEN',NULL,NULL),
(4,4,2000000,250000,clock_timestamp()-interval '4 days',clock_timestamp()-interval '3 days','CLOSED',2500000,3),
(5,6,100000,10000,clock_timestamp()-interval '3 days',clock_timestamp()-interval '2 days','CLOSED',NULL,NULL),
(6,5,2000000,100000,clock_timestamp()-interval '1 day',clock_timestamp()+interval '7 days','OPEN',NULL,NULL)
ON CONFLICT(id) DO NOTHING;
INSERT INTO auction.registrations(auction_id,user_id,status)
SELECT a.id,u.id,'APPROVED' FROM auction.auctions a CROSS JOIN auction.users u
WHERE u.id BETWEEN 2 AND 21 ON CONFLICT(auction_id,user_id) DO NOTHING;
-- Người dùng 1 tham gia phiên do người dùng 2 bán: vai trò gắn với phiên.
INSERT INTO auction.registrations(auction_id,user_id) VALUES(6,1) ON CONFLICT DO NOTHING;
INSERT INTO auction.bids(id,auction_id,bidder_id,amount,request_id,accepted_at) VALUES
(1,4,2,2000000,'19000000-0000-0000-0000-000000000001',clock_timestamp()-interval '3 days 12 hours'),
(2,4,3,2250000,'19000000-0000-0000-0000-000000000002',clock_timestamp()-interval '3 days 11 hours'),
(3,4,4,2500000,'19000000-0000-0000-0000-000000000003',clock_timestamp()-interval '3 days 10 hours')
ON CONFLICT(id) DO NOTHING;
INSERT INTO auction.results(auction_id,winning_bid_id,closed_at) VALUES
(4,3,clock_timestamp()-interval '3 days'),(5,NULL,clock_timestamp()-interval '2 days')
ON CONFLICT(auction_id) DO NOTHING;
INSERT INTO auction.audit_log(auction_id,action,actor_id,details,occurred_at)
SELECT b.auction_id,'BID_ACCEPTED',b.bidder_id,
    jsonb_build_object('bid_id',b.id,'amount',b.amount,'request_id',b.request_id,'source','seed'),b.accepted_at
FROM auction.bids b WHERE b.id IN(1,2,3)
AND NOT EXISTS(SELECT 1 FROM auction.audit_log l WHERE l.action='BID_ACCEPTED' AND l.details->>'bid_id'=b.id::text);
INSERT INTO auction.audit_log(auction_id,action,details,occurred_at)
SELECT r.auction_id,'AUCTION_CLOSED',jsonb_build_object('winning_bid_id',r.winning_bid_id,'source','seed'),r.closed_at
FROM auction.results r WHERE r.auction_id IN(4,5)
AND NOT EXISTS(SELECT 1 FROM auction.audit_log l WHERE l.action='AUCTION_CLOSED' AND l.auction_id=r.auction_id);
SELECT setval(pg_get_serial_sequence('auction.users','id'),(SELECT max(id) FROM auction.users));
SELECT setval(pg_get_serial_sequence('auction.categories','id'),(SELECT max(id) FROM auction.categories));
SELECT setval(pg_get_serial_sequence('auction.assets','id'),(SELECT max(id) FROM auction.assets));
SELECT setval(pg_get_serial_sequence('auction.auctions','id'),(SELECT max(id) FROM auction.auctions));
SELECT setval(pg_get_serial_sequence('auction.bids','id'),(SELECT max(id) FROM auction.bids));
COMMIT;
