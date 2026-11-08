-- =====================================================================
-- ĐỀ TÀI 19 - 02_functions.sql: HÀM NGHIỆP VỤ
--   auction.require_strategy   kiểm tra tham số giao thức đồng thời
--   auction.place_bid          trả giá (một lượt = một transaction)
--   auction.close_auction      đóng phiên, chốt tối đa một kết quả
--   auction.auction_report     báo cáo có bộ lọc động (EXECUTE ... USING)
--   auction.verify_invariants  kiểm tra 8 bất biến của toàn CSDL
--
-- Hai phương án kiểm soát đồng thời (tham số p_strategy):
--   'row_lock'     READ COMMITTED + SELECT ... FOR UPDATE trên dòng phiên.
--   'serializable' Client BEGIN ISOLATION LEVEL SERIALIZABLE; khi gặp lỗi
--                  40001/40P01 client ROLLBACK và chạy lại TOÀN BỘ giao dịch
--                  (giữ nguyên request_id). Xem AuctionClient._run trong db.py.
-- Trả giá và đóng phiên dùng CHUNG một quy tắc: ai ghi dòng phiên trước thì
-- người kia phải chờ (row_lock) hoặc bị hủy rồi làm lại (serializable).
-- =====================================================================
BEGIN;

CREATE OR REPLACE FUNCTION auction.require_strategy(p_strategy text) RETURNS void
LANGUAGE plpgsql SET search_path = pg_catalog, pg_temp AS $$
BEGIN
    IF p_strategy IS NULL OR p_strategy NOT IN ('row_lock', 'serializable') THEN
        RAISE EXCEPTION 'strategy phải là row_lock hoặc serializable' USING ERRCODE = '22023';
    END IF;
    IF p_strategy = 'serializable' AND current_setting('transaction_isolation') <> 'serializable' THEN
        RAISE EXCEPTION 'Phải BEGIN ISOLATION LEVEL SERIALIZABLE trước khi gọi' USING ERRCODE = '25001';
    END IF;
END $$;

-- =====================================================================
-- TRẢ GIÁ
-- Kết quả jsonb: status = ACCEPTED | REPLAYED | REJECTED, kèm code.
-- Lỗi tuần tự hóa/deadlock KHÔNG trả về jsonb mà ném lỗi để client thử lại.
-- =====================================================================
CREATE OR REPLACE FUNCTION auction.place_bid(
    p_auction_id bigint,
    p_bidder_id  bigint,
    p_amount     numeric,
    p_request_id uuid,
    p_strategy   text DEFAULT 'row_lock'
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER                              -- app chỉ được gọi hàm, không ghi bảng
SET search_path = pg_catalog, auction, pg_temp
AS $$
DECLARE
    v_auction      auction.auctions%ROWTYPE;  -- trạng thái phiên đọc được
    v_existing_bid auction.bids%ROWTYPE;      -- lượt đã lưu với cùng request_id
    v_seller_id    bigint;
    v_min_amount   numeric;
    v_bid_id       bigint;
    v_now          timestamptz;
    v_response     jsonb;
BEGIN
    PERFORM auction.require_strategy(p_strategy);
    IF p_request_id IS NULL THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'INVALID_REQUEST_ID');
    END IF;

    -- BƯỚC 1. CHỐNG GỬI LẠI (idempotency) ------------------------------
    -- Khóa tư vấn theo UUID: các yêu cầu cùng UUID xếp hàng nối tiếp, kể cả
    -- khi nhắm vào hai phiên khác nhau (khóa dòng phiên không che được).
    -- Trùng giá trị băm chỉ làm chờ thêm; UNIQUE(request_id) là hàng rào cuối.
    PERFORM pg_advisory_xact_lock(hashtextextended(p_request_id::text, 190019));

    SELECT * INTO v_existing_bid FROM auction.bids WHERE request_id = p_request_id;
    IF FOUND THEN
        IF (v_existing_bid.auction_id, v_existing_bid.bidder_id, v_existing_bid.amount)
           IS DISTINCT FROM (p_auction_id, p_bidder_id, p_amount) THEN
            -- Cùng UUID nhưng nội dung khác: không được coi là gửi lại.
            RETURN jsonb_build_object('status', 'REJECTED', 'code', 'IDEMPOTENCY_CONFLICT');
        END IF;
        RETURN jsonb_build_object(
            'status', 'REPLAYED', 'code', 'BID_REPLAYED',
            'bid_id', v_existing_bid.id, 'amount', v_existing_bid.amount,
            'auction_id', v_existing_bid.auction_id, 'accepted_at', v_existing_bid.accepted_at);
    END IF;

    -- BƯỚC 2. KIỂM TRA SỐ TIỀN (không cần đọc bảng) ---------------------
    IF p_amount IS NULL
       OR p_amount::text IN ('NaN', 'Infinity', '-Infinity')
       OR p_amount <= 0
       OR p_amount > 9999999999999999.99         -- giới hạn của numeric(18,2)
       OR p_amount <> trunc(p_amount, 2) THEN    -- tối đa 2 chữ số thập phân
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'INVALID_AMOUNT');
    END IF;

    -- BƯỚC 3. ĐỌC PHIÊN THEO GIAO THỨC ĐỒNG THỜI ------------------------
    IF p_strategy = 'row_lock' THEN
        -- Phương án A: khóa dòng phiên. Lượt trả giá/đóng phiên khác của CÙNG
        -- phiên phải chờ tới khi giao dịch này kết thúc; sau khi có khóa,
        -- READ COMMITTED đọc được bản mới nhất đã commit.
        SELECT * INTO v_auction FROM auction.auctions WHERE id = p_auction_id FOR UPDATE;
    ELSE
        -- Phương án B: đọc snapshot, không khóa. Nếu giao dịch khác đã ghi
        -- phiên này sau snapshot, lệnh UPDATE ở bước 5a ném lỗi 40001.
        SELECT * INTO v_auction FROM auction.auctions WHERE id = p_auction_id;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'AUCTION_NOT_FOUND');
    END IF;

    -- BƯỚC 4. KIỂM TRA QUY TẮC TRÊN TRẠNG THÁI VỪA ĐỌC ------------------
    IF v_auction.status <> 'OPEN' THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'NOT_OPEN');
    END IF;

    v_now := clock_timestamp();                  -- giờ máy chủ CSDL, không tin giờ client
    IF v_now < v_auction.opens_at THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'NOT_STARTED');
    END IF;
    IF v_now >= v_auction.closes_at THEN          -- hạn nhận giá là [opens_at, closes_at)
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'AUCTION_ENDED');
    END IF;

    SELECT seller_id INTO v_seller_id FROM auction.assets WHERE id = v_auction.asset_id;
    IF p_bidder_id = v_seller_id THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'SELLER_CANNOT_BID');
    END IF;

    IF NOT EXISTS (SELECT 1 FROM auction.registrations
                   WHERE auction_id = p_auction_id AND user_id = p_bidder_id
                     AND status = 'APPROVED') THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'NOT_REGISTERED');
    END IF;

    -- Lượt đầu >= giá khởi điểm; lượt sau >= giá hiện tại + bước giá.
    -- Vì vậy hai yêu cầu CÙNG mức giá: yêu cầu đến sau đọc giá mới và bị từ chối.
    v_min_amount := CASE WHEN v_auction.current_price IS NULL THEN v_auction.start_price
                         ELSE v_auction.current_price + v_auction.bid_step END;
    IF p_amount < v_min_amount THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'BID_TOO_LOW', 'minimum', v_min_amount);
    END IF;
    -- Lưới giá: amount = start_price + k * bid_step, k nguyên >= 0.
    IF mod(p_amount - v_auction.start_price, v_auction.bid_step) <> 0 THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'INVALID_INCREMENT');
    END IF;

    -- BƯỚC 5. GHI NGUYÊN TỬ: lịch sử + giá hiện tại + nhật ký -----------
    -- Khối BEGIN ... EXCEPTION là một subtransaction: nhảy vào EXCEPTION thì
    -- mọi thay đổi trong khối bị hủy. Lỗi không bắt ở đây làm hỏng cả giao
    -- dịch và client ROLLBACK => không bao giờ còn dữ liệu dở dang.
    BEGIN
        -- 5a. Điểm ghi đầu tiên lên dòng phiên = "giành quyền cập nhật".
        --     row_lock     : đã giữ khóa nên không phải chờ.
        --     serializable : nếu bên khác đã ghi phiên sau snapshot của mình,
        --                    PostgreSQL báo 40001 ngay tại đây.
        UPDATE auction.auctions SET revision = revision + 1 WHERE id = p_auction_id;

        -- 5b. Kiểm tra hạn LẦN HAI: có thể đã chờ khóa vượt quá giờ đóng.
        v_now := clock_timestamp();
        IF v_now >= v_auction.closes_at THEN
            RAISE EXCEPTION 'Hết giờ sau khi giành quyền cập nhật' USING ERRCODE = 'P1919';
        END IF;

        -- 5c. Ghi lịch sử. (Thực nghiệm "lỗi sau khi ghi lượt, trước khi cập
        --     nhật giá hiện tại" gắn trigger AFTER INSERT lên bảng này.)
        v_bid_id := nextval(pg_get_serial_sequence('auction.bids', 'id'));
        INSERT INTO auction.bids (id, auction_id, bidder_id, amount, request_id, accepted_at)
        VALUES (v_bid_id, p_auction_id, p_bidder_id, p_amount, p_request_id, v_now);

        -- 5d. Cập nhật giá hiện tại (cache) và lượt dẫn đầu.
        UPDATE auction.auctions
        SET current_price = p_amount, leading_bid_id = v_bid_id
        WHERE id = p_auction_id;

        -- 5e. Nhật ký trong CÙNG giao dịch.
        INSERT INTO auction.audit_log (auction_id, action, actor_id, details)
        VALUES (p_auction_id, 'BID_ACCEPTED', p_bidder_id,
                jsonb_build_object('bid_id', v_bid_id, 'amount', p_amount,
                                   'request_id', p_request_id, 'strategy', p_strategy));

        v_response := jsonb_build_object(
            'status', 'ACCEPTED', 'code', 'BID_ACCEPTED', 'bid_id', v_bid_id,
            'amount', p_amount, 'auction_id', p_auction_id, 'accepted_at', v_now);
    EXCEPTION
        WHEN SQLSTATE 'P1919' THEN
            RETURN jsonb_build_object('status', 'REJECTED', 'code', 'AUCTION_ENDED');
        WHEN unique_violation THEN
            -- Chỉ gặp với SERIALIZABLE: snapshot chụp trước lúc chờ khóa UUID
            -- nên không thấy lượt mà giao dịch khác vừa COMMIT. Đổi thành 40001
            -- để client chạy lại trên snapshot mới; lần sau bước 1 sẽ trả
            -- REPLAYED hoặc IDEMPOTENCY_CONFLICT. Không trả lỗi trùng khóa thô.
            IF p_strategy = 'serializable' THEN
                RAISE EXCEPTION 'Dữ liệu đã được commit ngoài snapshot; thử lại transaction'
                    USING ERRCODE = '40001';
            END IF;
            RAISE;
    END;
    RETURN v_response;
END $$;

-- =====================================================================
-- ĐÓNG PHIÊN
-- Chỉ đóng khi đã tới closes_at. Gọi lại khi đã đóng trả REPLAYED với đúng
-- kết quả cũ. PK results(auction_id) chặn mọi kết quả thứ hai.
-- =====================================================================
CREATE OR REPLACE FUNCTION auction.close_auction(
    p_auction_id bigint,
    p_strategy   text DEFAULT 'row_lock'
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, auction, pg_temp
AS $$
DECLARE
    v_auction auction.auctions%ROWTYPE;
    v_result  auction.results%ROWTYPE;
    v_now     timestamptz;
BEGIN
    PERFORM auction.require_strategy(p_strategy);

    -- Cùng giao thức với place_bid: khóa dòng phiên hoặc đọc snapshot.
    -- Nếu một lượt trả giá đang giữ quyền ghi, đóng phiên phải chờ (row_lock)
    -- hoặc bị 40001 rồi làm lại (serializable) => luôn thấy lượt đó.
    IF p_strategy = 'row_lock' THEN
        SELECT * INTO v_auction FROM auction.auctions WHERE id = p_auction_id FOR UPDATE;
    ELSE
        SELECT * INTO v_auction FROM auction.auctions WHERE id = p_auction_id;
    END IF;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'AUCTION_NOT_FOUND');
    END IF;

    IF v_auction.status = 'CLOSED' THEN
        SELECT * INTO v_result FROM auction.results WHERE auction_id = p_auction_id;
        RETURN jsonb_build_object(
            'status', 'REPLAYED', 'code', 'CLOSE_REPLAYED', 'auction_id', p_auction_id,
            'winning_bid_id', v_result.winning_bid_id, 'closed_at', v_result.closed_at);
    END IF;
    IF clock_timestamp() < v_auction.closes_at THEN
        RETURN jsonb_build_object('status', 'REJECTED', 'code', 'TOO_EARLY');
    END IF;

    -- Lệnh ghi đầu tiên lên dòng phiên: giành quyền (giống bước 5a của place_bid).
    UPDATE auction.auctions SET status = 'CLOSED', revision = revision + 1 WHERE id = p_auction_id;

    -- Người thắng = lượt dẫn đầu tại thời điểm chốt; NULL nếu không có lượt nào.
    v_now := clock_timestamp();
    INSERT INTO auction.results (auction_id, winning_bid_id, closed_at)
    VALUES (p_auction_id, v_auction.leading_bid_id, v_now);
    INSERT INTO auction.audit_log (auction_id, action, details)
    VALUES (p_auction_id, 'AUCTION_CLOSED',
            jsonb_build_object('winning_bid_id', v_auction.leading_bid_id,
                               'winning_price', v_auction.current_price,
                               'strategy', p_strategy));

    RETURN jsonb_build_object(
        'status', 'CLOSED', 'code', 'AUCTION_CLOSED', 'auction_id', p_auction_id,
        'winning_bid_id', v_auction.leading_bid_id, 'winning_price', v_auction.current_price,
        'closed_at', v_now);
END $$;

-- =====================================================================
-- BÁO CÁO CÓ BỘ LỌC ĐỘNG
-- Chỉ ghép vào WHERE những điều kiện có tham số khác NULL (SQL động).
-- Giá trị luôn truyền bằng USING ($1, $2, $3) nên không thể SQL injection;
-- người dùng không bao giờ được ghép chuỗi vào câu lệnh.
-- p_category_id lọc theo CẢ CÂY con của danh mục (WITH RECURSIVE).
-- =====================================================================
CREATE OR REPLACE FUNCTION auction.auction_report(
    p_status      text    DEFAULT NULL,
    p_category_id bigint  DEFAULT NULL,
    p_min_price   numeric DEFAULT NULL
) RETURNS TABLE (
    auction_id        bigint,
    title             text,
    category_name     text,
    status            text,
    current_price     numeric,
    leading_bidder    text,
    participant_count bigint,
    bid_count         bigint,
    closes_at         timestamptz
)
LANGUAGE plpgsql STABLE
SET search_path = pg_catalog, auction, pg_temp
AS $$
DECLARE
    v_sql text := $sql$
        WITH RECURSIVE category_scope(id) AS (
            SELECT c.id FROM auction.categories c WHERE c.id = $2
            UNION ALL
            SELECT c.id FROM auction.categories c JOIN category_scope s ON c.parent_id = s.id
        )
        SELECT a.id, x.title, c.name, a.status, a.current_price::numeric, u.full_name,
               (SELECT count(*) FROM auction.registrations r
                WHERE r.auction_id = a.id AND r.status = 'APPROVED'),
               (SELECT count(*) FROM auction.bids b WHERE b.auction_id = a.id),
               a.closes_at
        FROM auction.auctions a
        JOIN auction.assets x     ON x.id = a.asset_id
        JOIN auction.categories c ON c.id = x.category_id
        LEFT JOIN auction.bids lead ON lead.id = a.leading_bid_id
        LEFT JOIN auction.users u   ON u.id = lead.bidder_id
        WHERE true
    $sql$;
BEGIN
    IF p_status IS NOT NULL THEN
        v_sql := v_sql || ' AND a.status = $1';
    END IF;
    IF p_category_id IS NOT NULL THEN
        v_sql := v_sql || ' AND x.category_id IN (SELECT id FROM category_scope)';
    END IF;
    IF p_min_price IS NOT NULL THEN
        -- Phiên chưa có lượt được xét theo giá khởi điểm.
        v_sql := v_sql || ' AND coalesce(a.current_price, a.start_price) >= $3';
    END IF;
    v_sql := v_sql || ' ORDER BY a.closes_at, a.id';

    RETURN QUERY EXECUTE v_sql USING p_status, p_category_id, p_min_price;
END $$;

-- =====================================================================
-- KIỂM TRA BẤT BIẾN (minh chứng cho báo cáo)
-- =====================================================================
CREATE OR REPLACE FUNCTION auction.verify_invariants()
RETURNS TABLE (check_name text, passed boolean, details text)
LANGUAGE sql STABLE
SET search_path = pg_catalog, auction, pg_temp
AS $$
    WITH highest AS (                          -- lượt cao nhất thực tế của mỗi phiên
        SELECT a.id, a.current_price, a.leading_bid_id,
               b.id AS actual_id, b.amount AS actual_price
        FROM auction.auctions a
        LEFT JOIN LATERAL (
            SELECT id, amount FROM auction.bids
            WHERE auction_id = a.id
            ORDER BY amount DESC, id DESC
            LIMIT 1
        ) b ON true
    ),
    checks(name, violations, description) AS (
        SELECT 'cache_matches_history', count(*),
               'current_price = MAX(lượt đã chấp nhận), NULL khi rỗng'
        FROM highest WHERE current_price IS DISTINCT FROM actual_price

        UNION ALL
        SELECT 'leader_matches_history', count(*),
               'leading_bid_id thuộc phiên và là lượt có giá cao nhất'
        FROM highest WHERE leading_bid_id IS DISTINCT FROM actual_id

        UNION ALL
        SELECT 'one_result_per_auction', count(*),
               'PK results.auction_id; tối đa một kết quả/phiên'
        FROM (SELECT auction_id FROM auction.results
              GROUP BY auction_id HAVING count(*) > 1) d

        UNION ALL
        SELECT 'closed_result_matches_winner', count(*),
               'CLOSED có đúng kết quả, OPEN chưa có kết quả; thắng bằng leader'
        FROM auction.auctions a
        LEFT JOIN auction.results r ON r.auction_id = a.id
        WHERE (a.status = 'CLOSED' AND (r.auction_id IS NULL
                                        OR r.winning_bid_id IS DISTINCT FROM a.leading_bid_id))
           OR (a.status = 'OPEN' AND r.auction_id IS NOT NULL)

        UNION ALL
        SELECT 'unique_request_ids', count(*),
               'UNIQUE bids.request_id, chống lượt trùng cả liên phiên'
        FROM (SELECT request_id FROM auction.bids
              GROUP BY request_id HAVING count(*) > 1) d

        UNION ALL
        SELECT 'valid_bid_rules', count(*),
               'Giá đúng lưới, đúng thời gian và tăng nghiêm ngặt theo thứ tự ID'
        FROM (
            SELECT b.*, a.start_price, a.bid_step, a.opens_at, a.closes_at,
                   lag(b.amount) OVER (PARTITION BY b.auction_id ORDER BY b.id) AS previous_amount
            FROM auction.bids b JOIN auction.auctions a ON a.id = b.auction_id
        ) v
        WHERE amount < start_price
           OR mod(amount - start_price, bid_step) <> 0
           OR accepted_at < opens_at OR accepted_at >= closes_at
           OR (previous_amount IS NOT NULL AND amount < previous_amount + bid_step)

        UNION ALL
        SELECT 'asset_subtypes_total_disjoint', count(*),
               'Mỗi tài sản thuộc đúng một lớp con tương ứng kind'
        FROM auction.assets a
        LEFT JOIN auction.artworks w     ON w.asset_id = a.id
        LEFT JOIN auction.collectibles c ON c.asset_id = a.id
        LEFT JOIN auction.electronics e  ON e.asset_id = a.id
        WHERE (w.asset_id IS NOT NULL)::int + (c.asset_id IS NOT NULL)::int
              + (e.asset_id IS NOT NULL)::int <> 1
           OR (a.kind = 'ARTWORK'     AND w.asset_id IS NULL)
           OR (a.kind = 'COLLECTIBLE' AND c.asset_id IS NULL)
           OR (a.kind = 'ELECTRONIC'  AND e.asset_id IS NULL)

        UNION ALL
        SELECT 'audit_atomicity', count(*),
               'Mỗi bid/result có đúng một sự kiện audit cùng dữ liệu'
        FROM (
            SELECT b.id FROM auction.bids b
            WHERE (SELECT count(*) FROM auction.audit_log l
                   WHERE l.action = 'BID_ACCEPTED' AND l.auction_id = b.auction_id
                     AND l.details->>'bid_id' = b.id::text) <> 1
            UNION ALL
            SELECT r.auction_id FROM auction.results r
            WHERE (SELECT count(*) FROM auction.audit_log l
                   WHERE l.action = 'AUCTION_CLOSED' AND l.auction_id = r.auction_id) <> 1
        ) bad
    )
    SELECT name, violations = 0, description || '; vi phạm=' || violations::text
    FROM checks;
$$;

-- Không cho mọi role gọi hàm SECURITY DEFINER. 06_permissions.sql cấp lại cho app.
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA auction FROM PUBLIC;
COMMIT;
