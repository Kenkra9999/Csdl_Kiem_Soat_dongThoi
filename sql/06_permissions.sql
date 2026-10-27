-- Chạy bằng chủ sở hữu schema. Role auction19_app do bước cấu hình máy tạo,
-- mật khẩu nằm riêng trong .env, không có trong mã nguồn Git.
BEGIN;
REVOKE ALL ON SCHEMA auction FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA auction FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA auction FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auction FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA auction FROM auction19_app;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA auction FROM auction19_app;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auction FROM auction19_app;
GRANT USAGE ON SCHEMA auction TO auction19_app;
GRANT SELECT ON ALL TABLES IN SCHEMA auction TO auction19_app;
GRANT EXECUTE ON FUNCTION auction.place_bid(bigint,bigint,numeric,uuid,text) TO auction19_app;
GRANT EXECUTE ON FUNCTION auction.close_auction(bigint,text) TO auction19_app;
GRANT EXECUTE ON FUNCTION auction.auction_report(text,bigint,numeric) TO auction19_app;
GRANT EXECUTE ON FUNCTION auction.verify_invariants() TO auction19_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA auction REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
COMMIT;
