# Chạy thử và quan sát trên pgAdmin 4

Để thao tác bằng giao diện, mở `MO_HE_THONG.cmd` và xem `docs/GIAO_DIEN.md`. Hướng dẫn dưới đây dùng Query Tool để kiểm tra trực tiếp dữ liệu và quan sát khóa. Cả hai cách đều kết nối cùng CSDL `auction19_demo` và cùng các hàm PostgreSQL hiện có.

## 1. Mở đúng CSDL

1. Mở pgAdmin 4, mở nhóm **Servers**, chọn PostgreSQL đang chạy trên máy.
2. Nếu pgAdmin hỏi mật khẩu PostgreSQL, nhập mật khẩu tài khoản bạn đã thiết lập khi cài; đây không phải mật khẩu GitHub hay mật khẩu Windows.
3. Mở **Databases**, chọn CSDL demo của đồ án (trên máy đã cài là `auction19_demo`), bấm phải và chọn **Query Tool**.
4. Chạy câu kiểm tra:

```sql
SELECT current_database(), current_user, version();
SELECT * FROM auction.auction_report(NULL,NULL,NULL);
SELECT * FROM auction.verify_invariants();
```

Chạy bằng nút Execute/F5. Nếu chọn một đoạn SQL, chỉ đoạn được chọn sẽ chạy. Trong kết quả verify, mọi dòng phải có `passed = true`.

## 2. Khi cài trên CSDL mới

Dùng CSDL riêng, tài khoản sở hữu lược đồ, chạy lần lượt `01_schema.sql`, `02_functions.sql`, `03_seed.sql` qua **Open File** trong Query Tool. `04_queries.sql` và `05_verify.sql` là truy vấn đọc/kiểm tra. Nếu dùng tài khoản ứng dụng, cấu hình riêng quyền theo script permissions và thông tin cài đặt; không cấp quyền ghi trực tiếp mọi bảng chỉ để demo.

Không chạy script tạo lại dữ liệu test/benchmark vào CSDL đang chứa dữ liệu thật. CLI `setup` từ chối nếu schema đã tồn tại. Nếu đã cài rồi chỉ cần chạy `list`, `scenario`, `verify`.

Nếu cần chỉnh cây danh mục bằng tài khoản quản trị, dùng READ COMMITTED hoặc SERIALIZABLE có retry; trigger từ chối REPEATABLE READ để tránh đọc cây trên snapshot cũ sau khi chờ khóa. Thao tác này không thuộc đường trả giá của app.

## 3. Đọc dữ liệu mẫu

```sql
-- Cấu hình và giá đang dẫn
SELECT id,asset_id,start_price,bid_step,opens_at,closes_at,
       status,current_price,leading_bid_id
FROM auction.auctions ORDER BY id;

-- Lịch sử lượt trả giá
SELECT b.id,b.auction_id,u.full_name,b.amount,b.request_id,b.accepted_at
FROM auction.bids b JOIN auction.users u ON u.id=b.bidder_id
ORDER BY b.auction_id,b.amount;

-- Kết quả chính thức: NULL nghĩa là không có lượt thắng
SELECT r.auction_id,u.full_name AS winner,b.amount AS winning_price,r.closed_at
FROM auction.results r
LEFT JOIN auction.bids b ON b.id=r.winning_bid_id
LEFT JOIN auction.users u ON u.id=b.bidder_id
ORDER BY r.auction_id;
```

Giờ hiển thị có thể theo múi giờ session. Có thể đặt `SET TIME ZONE 'Asia/Ho_Chi_Minh';` để xem theo giờ Việt Nam; dữ liệu `timestamptz` vẫn biểu diễn cùng thời điểm tuyệt đối.

## 4. Kịch bản tự động trước khi thao tác thủ công

Trong PowerShell tại thư mục dự án:

```powershell
.\.venv\Scripts\python.exe -m auction_lab scenario --strategy row_lock
.\.venv\Scripts\python.exe -m auction_lab scenario --strategy serializable
```

Mỗi lần chạy tạo một phiên mới, giá khởi điểm 100, bước 10, hạn khoảng 4 giây. Chương trình thực hiện lượt đầu, replay cùng UUID, hai người cùng trả 110, đóng sớm, đóng đúng hạn, đóng lại và kiểm tra bất biến. Ghi lại `auction_id` trong JSON rồi lọc dữ liệu phiên đó trên pgAdmin. Demo tạo thêm dữ liệu, không reset schema demo.

## 5. Hai Query Tool để quan sát khóa dòng

### 5.1. Chuẩn bị phiên dành riêng cho thí nghiệm

Thực hiện bằng tài khoản sở hữu CSDL. Dữ liệu mẫu đã có asset 1 và users 2, 3. Tạo phiên mới và hai đăng ký trong một câu lệnh:

```sql
WITH new_auction AS (
  INSERT INTO auction.auctions
    (asset_id,start_price,bid_step,opens_at,closes_at)
  VALUES (1,100000,10000,
          clock_timestamp()-interval '1 minute',
          clock_timestamp()+interval '5 minutes')
  RETURNING id
), registrations AS (
  INSERT INTO auction.registrations(auction_id,user_id)
  SELECT a.id,u.id FROM new_auction a
  CROSS JOIN (VALUES (2::bigint),(3::bigint)) AS u(id)
  RETURNING auction_id
)
SELECT DISTINCT auction_id FROM registrations;
```

Ghi lại số trả về. Trong các câu tiếp theo thay `123` bằng ID thực tế. Không dùng ID 123 khi chưa tạo nó. Mở thêm Query Tool thứ hai cho **cùng CSDL**; hai tab phải là hai kết nối, không chỉ hai đoạn trong cùng một cửa sổ editor.

### 5.2. Tab A giữ khóa

Chạy riêng đoạn này, chưa COMMIT:

```sql
BEGIN ISOLATION LEVEL READ COMMITTED;
SELECT id,current_price FROM auction.auctions WHERE id=123 FOR UPDATE;
```

Tab A đang giữ khóa trên dòng phiên. Tránh để transaction quên mở lâu sau thí nghiệm.

### 5.3. Tab B yêu cầu cùng phiên

Chạy ở tab B:

```sql
BEGIN ISOLATION LEVEL READ COMMITTED;
SELECT auction.place_bid(123::bigint,3::bigint,110000::numeric,
                        gen_random_uuid(),'row_lock');
COMMIT;
```

Tab B sẽ chờ vì tab A chưa giải phóng khóa. Đây là chờ khóa thật, không phải ứng dụng bị treo. Nếu phiên đã hết 5 phút, tạo phiên thí nghiệm mới trước khi làm lại.

### 5.4. Tab A nhận giá rồi commit

Quay tab A, chạy:

```sql
SELECT auction.place_bid(123::bigint,2::bigint,110000::numeric,
                        gen_random_uuid(),'row_lock');
COMMIT;
```

Tab A nhận giá 110000. Sau COMMIT, tab B chạy tiếp, đọc trạng thái mới và trả `BID_TOO_LOW` vì không còn đủ mức tối thiểu 120000. Chỉ một bid giá 110000 tồn tại. Nếu tab B gửi 120000 thì có thể được nhận nếu vẫn trước hạn.

```sql
SELECT * FROM auction.bids WHERE auction_id=123;
SELECT * FROM auction.verify_invariants();
```

Nếu bấm Cancel khi đang chờ hoặc gặp lỗi SQL, chạy `ROLLBACK;` trên kết nối tương ứng rồi mới bắt đầu thí nghiệm khác. Cảnh báo “transaction is aborted” nghĩa là cần rollback giao dịch đang lỗi.

## 6. Gửi lại cùng UUID

Trong một phiên còn hạn và có đăng ký được duyệt, tạo một UUID rồi **giữ nguyên nó** khi gửi lại:

```sql
SELECT gen_random_uuid();
```

Sao chép UUID, lấy mức giá hợp lệ của phiên và chạy hai lần:

```sql
SELECT auction.place_bid(123::bigint,2::bigint,120000::numeric,
 '00000000-0000-4000-8000-000000000099'::uuid,'row_lock');
```

UUID trong ví dụ là minh họa, thay bằng UUID vừa tạo để tránh đụng dữ liệu của lần demo trước. Lần đầu `ACCEPTED`, lần sau `REPLAYED`, bid_id không đổi. Với cùng UUID nhưng số tiền/người/phiên khác, kết quả `IDEMPOTENCY_CONFLICT`. Nếu mức giá không hợp lệ ngay lần đầu thì không có bid được lưu và đó chưa phải trường hợp replay.

## 7. Thử SERIALIZABLE đúng cách

```sql
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT auction.place_bid(123::bigint,3::bigint,130000::numeric,
                        gen_random_uuid(),'serializable');
COMMIT;
```

Mức giá trong ví dụ cần điều chỉnh theo dữ liệu thực. Hai tab cùng cập nhật có thể làm một tab gặp `40001`; khi đó `ROLLBACK`, tạo transaction mới, đọc lại toàn trạng thái và gọi lại với cùng UUID yêu cầu. pgAdmin không tự thực hiện vòng retry. Dùng CLI/test/benchmark để xem cơ chế retry tự động và đo số lần retry.

Không thể đổi isolation sang SERIALIZABLE sau khi transaction đã đọc dữ liệu. Gọi strategy serializable trong READ COMMITTED bị hàm từ chối; lựa chọn strategy không tự nâng mức cô lập của transaction đang chạy.

## 8. Đóng phiên và kiểm chứng

Sau khi đã hết hạn:

```sql
SELECT auction.close_auction(123::bigint,'row_lock');
SELECT auction.close_auction(123::bigint,'row_lock');
SELECT * FROM auction.results WHERE auction_id=123;
SELECT * FROM auction.verify_invariants();
```

Lần đóng đầu chốt leader, lần sau trả lại kết quả cũ. Đóng trước hạn trả `TOO_EARLY`. Không sửa trực tiếp closes_at/status để giả kết quả demo, vì điều đó làm mất ý nghĩa quy tắc. Kịch bản lỗi giữa transaction và cạnh tranh sát hạn đã được tự động hóa trong bộ test, không cần cài trigger gây lỗi vào CSDL demo.

## 9. Các lỗi thường gặp

- `relation auction... does not exist`: đang chọn sai CSDL hoặc chưa chạy setup.
- Không kết nối PostgreSQL: kiểm tra service, host/port, tên CSDL và `.env`; không dùng mật khẩu GitHub.
- `permission denied`: dùng đúng tài khoản app để gọi hàm, owner cho setup/sinh dữ liệu; không tự cấp quyền ghi rộng để bỏ qua lỗi.
- `BID_TOO_LOW`: tính lại giá tối thiểu từ current_price hoặc start_price.
- `INVALID_INCREMENT`: mức giá không nằm trên lưới của start_price và bid_step.
- `AUCTION_ENDED` dù trạng thái OPEN: tác vụ đóng chưa chạy nhưng thời hạn đã qua; không thể nhận giá nữa.
- Output tiếng Việt lỗi font ở terminal: dùng Windows Terminal/PowerShell hỗ trợ UTF-8; CLI đã cấu hình stdout UTF-8.
