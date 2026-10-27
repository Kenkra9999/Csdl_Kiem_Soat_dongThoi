BEGIN;
-- Gọi trong transaction riêng; SERIALIZABLE phải retry TOÀN transaction từ client.
CREATE OR REPLACE FUNCTION auction.place_bid(
    p_auction_id bigint,p_bidder_id bigint,p_amount numeric,p_request_id uuid,
    p_strategy text DEFAULT 'row_lock'
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,auction AS $$
DECLARE
    v_a auction.auctions%ROWTYPE; v_old auction.bids%ROWTYPE;
    v_seller bigint; v_bid_id bigint; v_time timestamptz;
    v_min numeric; v_answer jsonb;
BEGIN
    IF p_strategy IS NULL OR p_strategy NOT IN ('row_lock','serializable') THEN
        RAISE EXCEPTION 'strategy phải là row_lock hoặc serializable' USING ERRCODE='22023';
    END IF;
    IF p_strategy='serializable' AND current_setting('transaction_isolation')<>'serializable' THEN
        RAISE EXCEPTION 'Phải BEGIN ISOLATION LEVEL SERIALIZABLE trước khi gọi' USING ERRCODE='25001';
    END IF;
    IF p_request_id IS NULL THEN
        RETURN jsonb_build_object('status','REJECTED','code','INVALID_REQUEST_ID');
    END IF;
    -- Khóa theo UUID, KHÔNG khóa chung mọi lượt: ngăn duplicate liên phiên ở RC.
    -- Hash collision chỉ tăng chờ đợi; UNIQUE(request_id) vẫn là hàng rào cuối.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_request_id::text,190019));
    SELECT * INTO v_old FROM auction.bids WHERE request_id=p_request_id;
    IF FOUND THEN
        IF v_old.auction_id IS DISTINCT FROM p_auction_id OR v_old.bidder_id IS DISTINCT FROM p_bidder_id
           OR v_old.amount IS DISTINCT FROM p_amount THEN
            RETURN jsonb_build_object('status','REJECTED','code','IDEMPOTENCY_CONFLICT');
        END IF;
        RETURN jsonb_build_object('status','REPLAYED','code','BID_REPLAYED','bid_id',v_old.id,
             'amount',v_old.amount,'auction_id',v_old.auction_id,'accepted_at',v_old.accepted_at);
    END IF;
    IF p_amount IS NULL OR p_amount::text IN ('NaN','Infinity','-Infinity')
       OR p_amount<=0 OR p_amount>9999999999999999.99 OR p_amount<>trunc(p_amount,2) THEN
        RETURN jsonb_build_object('status','REJECTED','code','INVALID_AMOUNT');
    END IF;
    IF p_strategy='row_lock' THEN
        SELECT * INTO v_a FROM auction.auctions WHERE id=p_auction_id FOR UPDATE;
    ELSE
        -- Phương án 2: đọc snapshot bình thường; xung đột được phát hiện khi UPDATE.
        SELECT * INTO v_a FROM auction.auctions WHERE id=p_auction_id;
    END IF;
    IF NOT FOUND THEN RETURN jsonb_build_object('status','REJECTED','code','AUCTION_NOT_FOUND'); END IF;
    IF v_a.status<>'OPEN' THEN RETURN jsonb_build_object('status','REJECTED','code','NOT_OPEN'); END IF;
    v_time:=clock_timestamp();
    IF v_time<v_a.opens_at THEN RETURN jsonb_build_object('status','REJECTED','code','NOT_STARTED'); END IF;
    IF v_time>=v_a.closes_at THEN RETURN jsonb_build_object('status','REJECTED','code','AUCTION_ENDED'); END IF;
    SELECT seller_id INTO v_seller FROM auction.assets WHERE id=v_a.asset_id;
    IF p_bidder_id=v_seller THEN RETURN jsonb_build_object('status','REJECTED','code','SELLER_CANNOT_BID'); END IF;
    IF NOT EXISTS(SELECT 1 FROM auction.registrations WHERE auction_id=p_auction_id
                  AND user_id=p_bidder_id AND status='APPROVED') THEN
        RETURN jsonb_build_object('status','REJECTED','code','NOT_REGISTERED');
    END IF;
    v_min:=CASE WHEN v_a.current_price IS NULL THEN v_a.start_price ELSE v_a.current_price+v_a.bid_step END;
    IF p_amount<v_min THEN
        RETURN jsonb_build_object('status','REJECTED','code','BID_TOO_LOW','minimum',v_min);
    END IF;
    IF mod(p_amount-v_a.start_price,v_a.bid_step)<>0 THEN
        RETURN jsonb_build_object('status','REJECTED','code','INVALID_INCREMENT');
    END IF;
    -- Subtransaction: nếu chờ khóa UPDATE qua hạn, rollback cả cache và bid.
    BEGIN
        -- Điểm ghi đầu tiên tạo xung đột SSI và giành quyền cập nhật.
        -- Chưa đổi cache: test AFTER INSERT bids có thể gây lỗi đúng giữa
        -- ghi lịch sử và cập nhật giá hiện tại theo yêu cầu thực nghiệm.
        UPDATE auction.auctions SET revision=revision+1 WHERE id=p_auction_id;
        v_time:=clock_timestamp();
        IF v_time>=v_a.closes_at THEN
            RAISE EXCEPTION 'Hết giờ sau khi giành quyền cập nhật' USING ERRCODE='P1919';
        END IF;
        v_bid_id:=nextval(pg_get_serial_sequence('auction.bids','id'));
        INSERT INTO auction.bids(id,auction_id,bidder_id,amount,request_id,accepted_at)
        VALUES(v_bid_id,p_auction_id,p_bidder_id,p_amount,p_request_id,v_time);
        UPDATE auction.auctions SET current_price=p_amount,leading_bid_id=v_bid_id
        WHERE id=p_auction_id;
        INSERT INTO auction.audit_log(auction_id,action,actor_id,details)
        VALUES(p_auction_id,'BID_ACCEPTED',p_bidder_id,
            jsonb_build_object('bid_id',v_bid_id,'amount',p_amount,'request_id',p_request_id,'strategy',p_strategy));
        v_answer:=jsonb_build_object('status','ACCEPTED','code','BID_ACCEPTED','bid_id',v_bid_id,
            'amount',p_amount,'auction_id',p_auction_id,'accepted_at',v_time);
    EXCEPTION
        WHEN SQLSTATE 'P1919' THEN
            RETURN jsonb_build_object('status','REJECTED','code','AUCTION_ENDED');
        WHEN unique_violation THEN
            -- SERIALIZABLE có thể giữ snapshot cũ sau khi đợi cùng UUID.
            -- Không trả duplicate-key cho client: retry snapshot mới, rồi replay/conflict.
            IF p_strategy='serializable' THEN
                RAISE EXCEPTION 'UUID đã được commit ngoài snapshot; retry transaction' USING ERRCODE='40001';
            END IF;
            RAISE;
    END;
    RETURN v_answer;
END $$;

CREATE OR REPLACE FUNCTION auction.close_auction(p_auction_id bigint,p_strategy text DEFAULT 'row_lock')
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,auction AS $$
DECLARE v_a auction.auctions%ROWTYPE; v_r auction.results%ROWTYPE; v_time timestamptz;
BEGIN
    IF p_strategy IS NULL OR p_strategy NOT IN ('row_lock','serializable') THEN
        RAISE EXCEPTION 'strategy phải là row_lock hoặc serializable' USING ERRCODE='22023';
    END IF;
    IF p_strategy='serializable' AND current_setting('transaction_isolation')<>'serializable' THEN
        RAISE EXCEPTION 'Phải BEGIN ISOLATION LEVEL SERIALIZABLE trước khi gọi' USING ERRCODE='25001';
    END IF;
    IF p_strategy='row_lock' THEN
        SELECT * INTO v_a FROM auction.auctions WHERE id=p_auction_id FOR UPDATE;
    ELSE SELECT * INTO v_a FROM auction.auctions WHERE id=p_auction_id; END IF;
    IF NOT FOUND THEN RETURN jsonb_build_object('status','REJECTED','code','AUCTION_NOT_FOUND'); END IF;
    IF v_a.status='CLOSED' THEN
        SELECT * INTO v_r FROM auction.results WHERE auction_id=p_auction_id;
        RETURN jsonb_build_object('status','REPLAYED','code','CLOSE_REPLAYED','auction_id',p_auction_id,
             'winning_bid_id',v_r.winning_bid_id,'closed_at',v_r.closed_at);
    END IF;
    IF clock_timestamp()<v_a.closes_at THEN
        RETURN jsonb_build_object('status','REJECTED','code','TOO_EARLY');
    END IF;
    UPDATE auction.auctions SET status='CLOSED',revision=revision+1 WHERE id=p_auction_id;
    v_time:=clock_timestamp();
    INSERT INTO auction.results(auction_id,winning_bid_id,closed_at)
    VALUES(p_auction_id,v_a.leading_bid_id,v_time);
    INSERT INTO auction.audit_log(auction_id,action,details)
    VALUES(p_auction_id,'AUCTION_CLOSED',jsonb_build_object('winning_bid_id',v_a.leading_bid_id,
        'winning_price',v_a.current_price,'strategy',p_strategy));
    RETURN jsonb_build_object('status','CLOSED','code','AUCTION_CLOSED','auction_id',p_auction_id,
        'winning_bid_id',v_a.leading_bid_id,'winning_price',v_a.current_price,'closed_at',v_time);
END $$;

CREATE OR REPLACE FUNCTION auction.auction_report(
    p_status text DEFAULT NULL,p_category_id bigint DEFAULT NULL,p_min_price numeric DEFAULT NULL
) RETURNS TABLE(auction_id bigint,title text,category_name text,status text,current_price numeric,
    leading_bidder text,participant_count bigint,bid_count bigint,closes_at timestamptz)
LANGUAGE sql STABLE SET search_path=pg_catalog,auction AS $$
    WITH RECURSIVE category_scope AS (
        SELECT c.id FROM auction.categories c WHERE c.id=p_category_id
        UNION ALL
        SELECT c.id FROM auction.categories c JOIN category_scope s ON c.parent_id=s.id
    )
    SELECT a.id,x.title,c.name,a.status,a.current_price,u.full_name,
        (SELECT count(*) FROM auction.registrations r WHERE r.auction_id=a.id AND r.status='APPROVED'),
        (SELECT count(*) FROM auction.bids b WHERE b.auction_id=a.id),a.closes_at
    FROM auction.auctions a JOIN auction.assets x ON x.id=a.asset_id
    JOIN auction.categories c ON c.id=x.category_id
    LEFT JOIN auction.bids lead ON lead.id=a.leading_bid_id
    LEFT JOIN auction.users u ON u.id=lead.bidder_id
    WHERE (p_status IS NULL OR a.status=p_status)
      AND (p_category_id IS NULL OR x.category_id IN (SELECT id FROM category_scope))
      AND (p_min_price IS NULL OR coalesce(a.current_price,a.start_price)>=p_min_price)
    ORDER BY a.closes_at,a.id;
$$;

CREATE OR REPLACE FUNCTION auction.verify_invariants()
RETURNS TABLE(check_name text,passed boolean,details text)
LANGUAGE sql STABLE SET search_path=pg_catalog,auction AS $$
    WITH highest AS (
        SELECT a.id,a.current_price,a.leading_bid_id,b.id AS actual_id,b.amount AS actual_price
        FROM auction.auctions a LEFT JOIN LATERAL (
            SELECT id,amount FROM auction.bids WHERE auction_id=a.id ORDER BY amount DESC,id DESC LIMIT 1
        ) b ON true
    ), checks(name,violations,description) AS (
        SELECT 'cache_matches_history',count(*),'current_price = MAX(lượt đã chấp nhận), NULL khi rỗng'
        FROM highest WHERE current_price IS DISTINCT FROM actual_price
        UNION ALL
        SELECT 'leader_matches_history',count(*),'leading_bid_id thuộc phiên và là lượt có giá cao nhất'
        FROM highest WHERE leading_bid_id IS DISTINCT FROM actual_id
        UNION ALL
        SELECT 'one_result_per_auction',count(*),'PK results.auction_id; tối đa một kết quả/phiên'
        FROM (SELECT auction_id FROM auction.results GROUP BY auction_id HAVING count(*)>1) d
        UNION ALL
        SELECT 'closed_result_matches_winner',count(*),'CLOSED có đúng kết quả, OPEN chưa có kết quả; thắng bằng leader'
        FROM auction.auctions a LEFT JOIN auction.results r ON r.auction_id=a.id
        WHERE (a.status='CLOSED' AND (r.auction_id IS NULL OR r.winning_bid_id IS DISTINCT FROM a.leading_bid_id))
           OR (a.status='OPEN' AND r.auction_id IS NOT NULL)
        UNION ALL
        SELECT 'unique_request_ids',count(*),'UNIQUE bids.request_id, chống lượt trùng cả liên phiên'
        FROM (SELECT request_id FROM auction.bids GROUP BY request_id HAVING count(*)>1) d
        UNION ALL
        SELECT 'valid_bid_rules',count(*),'Giá đúng lưới, đúng thời gian và tăng nghiêm ngặt theo thứ tự ID'
        FROM (
            SELECT b.*,a.start_price,a.bid_step,a.opens_at,a.closes_at,
                lag(b.amount) OVER(PARTITION BY b.auction_id ORDER BY b.id) AS previous_amount
            FROM auction.bids b JOIN auction.auctions a ON a.id=b.auction_id
        ) v WHERE amount<start_price OR mod(amount-start_price,bid_step)<>0
              OR accepted_at<opens_at OR accepted_at>=closes_at
              OR (previous_amount IS NOT NULL AND amount<previous_amount+bid_step)
        UNION ALL
        SELECT 'asset_subtypes_total_disjoint',count(*),'Mỗi tài sản thuộc đúng một lớp con tương ứng kind'
        FROM auction.assets a LEFT JOIN auction.artworks w ON w.asset_id=a.id
        LEFT JOIN auction.collectibles c ON c.asset_id=a.id LEFT JOIN auction.electronics e ON e.asset_id=a.id
        WHERE (CASE WHEN w.asset_id IS NULL THEN 0 ELSE 1 END+
               CASE WHEN c.asset_id IS NULL THEN 0 ELSE 1 END+
               CASE WHEN e.asset_id IS NULL THEN 0 ELSE 1 END)<>1
           OR (a.kind='ARTWORK' AND w.asset_id IS NULL)
           OR (a.kind='COLLECTIBLE' AND c.asset_id IS NULL)
           OR (a.kind='ELECTRONIC' AND e.asset_id IS NULL)
        UNION ALL
        SELECT 'audit_atomicity',count(*),'Mỗi bid/result có đúng một sự kiện audit cùng dữ liệu'
        FROM (
            SELECT b.id FROM auction.bids b WHERE (SELECT count(*) FROM auction.audit_log l
              WHERE l.action='BID_ACCEPTED' AND l.auction_id=b.auction_id AND l.details->>'bid_id'=b.id::text)<>1
            UNION ALL
            SELECT r.auction_id FROM auction.results r WHERE (SELECT count(*) FROM auction.audit_log l
              WHERE l.action='AUCTION_CLOSED' AND l.auction_id=r.auction_id)<>1
        ) bad
    )
    SELECT name,violations=0,description||'; vi phạm='||violations::text FROM checks;
$$;

-- Không cho mọi role bất kỳ gọi SECURITY DEFINER. 06_permissions.sql cấp lại nhóm app.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auction FROM PUBLIC;
COMMIT;
