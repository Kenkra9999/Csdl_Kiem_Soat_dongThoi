# BÁO CÁO ĐỒ ÁN CƠ SỞ DỮ LIỆU NÂNG CAO

## Đề tài 19: Thiết kế CSDL hệ thống đấu giá trực tuyến và kiểm soát trả giá đồng thời

Nền tảng: PostgreSQL 18, Python 3.12, psycopg 3. Dữ liệu trong đồ án là dữ liệu giả lập. Thông tin sinh viên, lớp và giảng viên được người nộp bổ sung theo thông tin thực tế.

## Tóm tắt

Đồ án giải quyết việc nhiều người trả giá cho cùng một tài sản, trong khi một giao dịch khác có thể đang đóng phiên. Nếu ứng dụng đọc giá hiện tại rồi ghi giá mới mà không điều phối giao dịch, một yêu cầu có thể kiểm tra trên dữ liệu cũ, làm mất cập nhật, hoặc tạo kết quả không tương ứng với lịch sử. Giải pháp sử dụng CSDL quan hệ chuẩn hóa, giữ lịch sử trả giá bất biến, thực hiện nghiệp vụ nguyên tử trong PostgreSQL và so sánh hai phương án trên cùng loại tải: khóa dòng phiên ở READ COMMITTED và SERIALIZABLE có thử lại toàn giao dịch.

Các tiêu chí kiểm chứng là: tối đa một kết quả cho mỗi phiên, giá hiện tại khớp lịch sử, cùng mã yêu cầu không sinh hai lượt trả giá, và lỗi giữa giao dịch không để lại dữ liệu dở dang. Kết quả benchmark được đo từ chương trình đi kèm, không lấy từ số liệu giả định.

## 1. Bài toán, mục tiêu và phạm vi

### 1.1. Câu hỏi nghiên cứu

Làm thế nào để mỗi lượt trả giá được kiểm tra trên trạng thái hợp lệ, không làm mất cập nhật và không tạo hai người thắng cho cùng một phiên khi nhiều yêu cầu chạy đồng thời?

### 1.2. Phạm vi

Quản lý người dùng, cây danh mục tài sản, tài sản có chuyên biệt hóa, phiên đấu giá, đăng ký tham gia, lịch sử trả giá, kết quả và nhật ký. Mô phỏng đấu giá tăng dần công khai, một tài sản trong một phiên, một đơn vị tiền tệ. Không triển khai thanh toán, giao hàng, giấy phép đấu giá, xác minh danh tính, chống thông đồng hoặc ứng dụng thương mại đầy đủ. Không triển khai bài 20 về RBAC.

### 1.3. Sản phẩm bàn giao

Mã SQL tạo và kiểm tra CSDL; dữ liệu mẫu; hàm trả giá/đóng phiên/báo cáo; truy vấn nâng cao; client Python; giao diện web cục bộ; kiểm thử đồng thời; benchmark tái lập được; mô hình EER, đối tượng và OQL; hướng dẫn pgAdmin; báo cáo và kịch bản bảo vệ.

## 2. Đặc tả nghiệp vụ

### 2.1. Giá và bước giá

Giá khởi điểm `start_price` dương. Bước giá `bid_step` dương. Dùng `numeric(18,2)` để lưu tiền chính xác đến hai chữ số thập phân, phía Python dùng `Decimal`.

Nếu chưa có lượt trả giá hợp lệ, mức tối thiểu là `start_price`. Nếu đã có, mức tối thiểu là `current_price + bid_step`. Mọi mức giá phải thuộc lưới `start_price + k * bid_step`, với `k` nguyên không âm. Vì vậy không chỉ kiểm tra lớn hơn giá trước mà còn phải kiểm tra đúng bước giá. Các trường hợp số âm, độ chính xác vượt quy định, NaN hoặc vô cực phải bị từ chối trước khi lưu.

`start_price` là điều kiện của phiên. `bids.amount` là giá của một lượt đã được chấp nhận. `current_price` là giá cao nhất suy diễn từ lịch sử; khi chưa có bid thì bằng NULL. Giá thắng là `amount` của `results.winning_bid_id`, không lưu thêm một bản sao giá thắng.

### 2.2. Mở, đóng và hạn nhận giá

Phiên có `opens_at < closes_at`. Lượt trả giá chỉ hợp lệ trong khoảng nửa mở `[opens_at, closes_at)` trên đồng hồ CSDL. Đúng `closes_at` đã hết hạn. Phiên có thể còn mang trạng thái `OPEN` sau hạn nếu tác vụ đóng chưa chạy; hàm trả giá vẫn từ chối bằng kiểm tra thời gian.

Thời điểm xét nhận là `clock_timestamp()` khi hàm được quyền xử lý phiên. Một yêu cầu gửi từ máy khách trước hạn nhưng chờ khóa đến sau hạn vẫn bị từ chối. Không tin thời gian do máy khách gửi. Không dùng `now()` để quyết định hạn sau khi chờ khóa, vì `now()` cố định từ đầu transaction và có thể đã cũ.

`close_auction` chỉ đóng khi thời gian máy chủ đạt `closes_at`; chưa tới hạn trả `TOO_EARLY`. Không có chức năng ép đóng trong hàm nghiệp vụ chính. Đóng lại một phiên đã đóng trả kết quả cũ.

### 2.3. Điều kiện người tham gia

Người dùng phải có đăng ký `APPROVED` của chính phiên. Chủ sở hữu tài sản không được tự trả giá. Vai trò người bán/người tham gia là quan hệ theo từng phiên, không phải hai lớp người dùng loại trừ nhau.

Trong thời gian thí nghiệm, cấu hình phiên và đăng ký được chuẩn bị trước. Tài khoản ứng dụng chỉ gọi hàm, không sửa trực tiếp tài sản, đăng ký, lịch sử hoặc kết quả. Tài khoản sở hữu CSDL dùng cho cài đặt và sinh dữ liệu không phải tài khoản ứng dụng thông thường.

### 2.4. Hai yêu cầu cùng giá và yêu cầu gửi lại

Hai yêu cầu khác UUID cùng mức giá không cùng được chấp nhận. Yêu cầu được xử lý hợp lệ trước cập nhật leader; yêu cầu sau phải kiểm tra lại giá mới và bị từ chối. Không bảo đảm người bấm nút trước hoặc gói mạng đến trước luôn thắng; thứ tự được xác định bởi quá trình xử lý giao dịch của CSDL.

UUID `request_id` nhận diện một yêu cầu trả giá trên toàn hệ thống. Nếu UUID đã được chấp nhận và nội dung `(auction_id, bidder_id, amount)` giống nhau, trả lại bid cũ, kể cả phiên đã đóng. Nếu UUID trùng nhưng nội dung khác, trả `IDEMPOTENCY_CONFLICT`. Cơ chế khóa request/định danh duy nhất phải xử lý cả trường hợp hai phiên khác nhau đồng thời sử dụng cùng UUID.

Chỉ yêu cầu được chấp nhận được lưu trong `bids`. Từ chối nghiệp vụ không được cache như một kết quả vĩnh viễn: chẳng hạn người dùng có thể được duyệt đăng ký sau đó. Vì vậy UUID của một yêu cầu đã bị từ chối có thể được thử lại và đánh giá trên trạng thái mới; client nên tạo UUID mới khi chủ động thay đổi ý định. Đây là idempotency của **thao tác đã ghi nhận**, không phải sổ lưu mọi lần gọi API.

### 2.5. Kết quả và kiểm toán

Không có giá dự trữ. Nếu có bid hợp lệ, người thắng là người của bid cao nhất. Nếu không có bid, vẫn tạo kết quả với `winning_bid_id IS NULL`, thể hiện phiên không thành công. Mỗi phiên kết thúc có đúng một dòng kết quả; trước khi đóng có thể chưa có dòng nào.

Ghi `BID_ACCEPTED` và `AUCTION_CLOSED` cùng giao dịch nghiệp vụ. Nhật ký là chứng cứ thay đổi đã commit; các yêu cầu bị từ chối và số lần retry được lưu ở log thực nghiệm phía client. Nếu giao dịch rollback, bid, cache và audit đều rollback.

## 3. Thiết kế EER và lược đồ quan hệ

### 3.1. Thực thể và chuyên biệt hóa

Sơ đồ EER ký hiệu Chen theo tài liệu SGU nằm ở `docs/eer/EER_DE_TAI_19_DA_SUA.pdf` (trang 3 của bản PDF này); `GiaHienTai` và mối kết hợp `DanDau` vẽ nét đứt vì là dữ liệu suy diễn, `ThuDienTu` và `MaYeuCau` gạch chân vì là khóa ứng viên. Ánh xạ sang bảng trong `docs/EER.md`. Tài sản là lớp cha, có ba lớp con nghệ thuật, sưu tầm, điện tử; chuyên biệt hóa total và disjoint. Các bảng con dùng PK đồng thời là FK tới tài sản cha. Trigger ràng buộc hoãn đến cuối giao dịch kiểm tra mỗi tài sản có đúng bảng con phù hợp. Cần hoãn vì khi chèn tài sản cha, bảng con có thể chưa được chèn ở câu lệnh đó.

Cây danh mục dùng adjacency list `(id, parent_id)`, cấm chu trình. Người dùng bán tài sản qua `seller_id`; tham gia qua bảng nối `registrations`. Không tạo hai bản ghi người dùng cho hai vai trò.

### 3.2. Lược đồ vật lý

- `users(id PK, email UNIQUE, full_name, created_at)`.
- `categories(id PK, parent_id FK -> categories, name)`; tên trong cùng một cha duy nhất, kể cả các gốc cùng NULL.
- `assets(id PK, seller_id FK, category_id FK, kind, title, description, created_at)`.
- `artworks(asset_id PK/FK, artist, material, creation_year)`.
- `collectibles(asset_id PK/FK, origin, rarity, production_year)`.
- `electronics(asset_id PK/FK, brand, model, serial_number UNIQUE nullable, condition)`.
- `auctions(id PK, asset_id FK, start_price, bid_step, opens_at, closes_at, status, current_price, leading_bid_id FK, revision)`.
- `registrations(auction_id PK/FK, user_id PK/FK, status)`.
- `bids(id PK, auction_id FK, bidder_id FK, amount, request_id UNIQUE, accepted_at)`.
- `results(auction_id PK/FK, winning_bid_id FK nullable, closed_at)`.
- `audit_log(id PK, auction_id FK, action, actor_id FK nullable, details JSONB, occurred_at, transaction_id)`.

Khóa ghép đăng ký ngăn một người đăng ký trùng phiên. UUID duy nhất ngăn một yêu cầu được lưu hai lần. FK kép `(leading_bid_id,id)` và `(winning_bid_id,auction_id)` tham chiếu `(bids.id,bids.auction_id)`, bảo đảm lượt dẫn/thắng thuộc đúng phiên; một FK chỉ vào `bids.id` không tự bảo đảm điều đó. Trigger kiểm chứng liên bảng bổ sung tính nhất quán leader, max-price và kết quả.

### 3.3. Chỉ mục

PK/UNIQUE tạo các chỉ mục tương ứng. Chỉ mục truy vấn phục vụ tìm phiên theo trạng thái/hạn đóng, tìm bid theo phiên và giá, tra đăng ký theo khóa ghép, duyệt con theo `categories.parent_id`, tìm tài sản theo danh mục. Đánh đổi là tăng dung lượng và chi phí ghi; chỉ mục không thay thế transaction hay kiểm tra nghiệp vụ.

## 4. Phụ thuộc hàm, khóa và chuẩn hóa

### 4.1. Quan hệ quan sát ban đầu

Xét quan hệ rộng `R` cho **mỗi lượt trả giá đã chấp nhận** gồm:

```text
bid_id, request_id, auction_id, bidder_id, amount, accepted_at,
asset_id, start_price, bid_step, opens_at, closes_at,
seller_id, category_id, title, kind,
bidder_email, bidder_name, seller_email, seller_name,
category_name, parent_id
```

Tên và email được đặt hai bí danh để biểu diễn hai vai trò của cùng thực thể người dùng. Quan hệ R chỉ là công cụ phân tích; không thể biểu diễn phiên chưa có bid hoặc người chỉ đăng ký mà chưa trả giá, nên các thực thể đó vẫn được mô hình hóa riêng.

### 4.2. Tập phụ thuộc hàm

Từ quy tắc định danh, có tập F sau, viết gộp vế phải để dễ đọc:

```text
bid_id -> request_id, auction_id, bidder_id, amount, accepted_at
request_id -> bid_id
auction_id -> asset_id, start_price, bid_step, opens_at, closes_at
asset_id -> seller_id, category_id, title, kind
bidder_id -> bidder_email, bidder_name
bidder_email -> bidder_id
seller_id -> seller_email, seller_name
seller_email -> seller_id
category_id -> category_name, parent_id
(auction_id, amount) -> bid_id
(parent_id, category_name) -> category_id
```

Không giả định họ tên là duy nhất, tên tài sản xác định tài sản, tên danh mục xác định danh mục toàn cục, hay mức giá xác định một bid trên toàn CSDL. Việc cấm hai bid bằng giá tạo khóa nghiệp vụ `(auction_id,amount)` trong dữ liệu bid hợp lệ, không phải FD `amount -> bid_id`. Khóa này được bảo đảm hai lớp: protocol giá tăng nghiêm ngặt trong `place_bid`, và ràng buộc `UNIQUE (auction_id, amount)` (`bids_auction_id_amount_key`) làm hàng rào cuối cùng ở mức CSDL, kể cả khi có ai đó ghi thẳng vào bảng. Với danh mục gốc, FD theo cặp cha/tên được hiểu trong mô hình logic dùng một ký hiệu gốc thống nhất; PostgreSQL hiện thực quy tắc tương đương bằng UNIQUE NULLS NOT DISTINCT để xử lý NULL của parent_id.

### 4.3. Khóa ứng viên bằng bao đóng

`{bid_id}+` chứa request, phiên, bidder, giá, thời gian; từ phiên suy ra tài sản/cấu hình; từ tài sản suy ra seller/danh mục; từ hai người và danh mục suy ra mọi thông tin mô tả. Vì vậy `bid_id` là khóa ứng viên.

`request_id -> bid_id`, nên `{request_id}+ = R`; `request_id` là khóa ứng viên thứ hai. Cả hai là thuộc tính đơn nên tối thiểu. Khóa thứ ba là `(auction_id,amount)` vì cặp này suy ra bid_id; từng thuộc tính riêng không suy ra bid_id nên cặp là tối thiểu. Các FD còn lại không sinh auction_id hoặc amount nếu thiếu các định thức này; vì vậy ba khóa trên là các khóa ứng viên theo F đã công bố.

### 4.4. Phủ tối tiểu

Tách từng phụ thuộc gộp vế phải ở mục 4.2 thành các FD có **một thuộc tính vế phải**. Tập thu được là phủ tối tiểu `Fmin`:

```text
bid_id -> request_id       bid_id -> auction_id
bid_id -> bidder_id        bid_id -> amount
bid_id -> accepted_at      request_id -> bid_id
auction_id -> asset_id     auction_id -> start_price
auction_id -> bid_step     auction_id -> opens_at
auction_id -> closes_at    asset_id -> seller_id
asset_id -> category_id    asset_id -> title
asset_id -> kind           bidder_id -> bidder_email
bidder_id -> bidder_name   bidder_email -> bidder_id
seller_id -> seller_email  seller_id -> seller_name
seller_email -> seller_id  category_id -> category_name
category_id -> parent_id
(auction_id,amount) -> bid_id
(parent_id,category_name) -> category_id
```

Các FD có vế trái đơn không có thuộc tính thừa ở vế trái. Ở hai vế trái ghép, riêng auction_id hoặc amount không suy ra bid_id; riêng parent_id hoặc category_name không suy ra category_id. Khi bỏ từng FD, tính bao đóng của vế trái trên phần còn lại không sinh lại thuộc tính vế phải của FD đó. Ví dụ bỏ `auction_id -> start_price` thì không còn đường nào từ auction đến start_price; bỏ `request_id -> bid_id` thì request không sinh bid; bỏ `bidder_email -> bidder_id` thì email không sinh người dùng. Các cặp ID/email hai chiều đều cần để giữ khóa thay thế. Fmin tương đương F do phép tách/hợp vế phải.

### 4.5. Bất thường của quan hệ rộng

R không đạt 3NF vì `auction_id`, `asset_id`, `bidder_id`, `seller_id`, `category_id` không là siêu khóa của R nhưng xác định các thuộc tính không khóa. Thay email người bán phải sửa nhiều dòng; thêm phiên chưa có bid không có dòng đại diện; xóa bid cuối có thể mất thông tin phiên nếu chỉ lưu R. Các FD bắc cầu từ bid tới phiên, tài sản và mô tả tạo lặp thông tin.

### 4.6. Phân rã và chứng minh

Gom các FD chung vế trái để tạo `Bid`, `AuctionCore`, `Asset`, `Bidder`, `Seller`, `Category`. Hợp hai quan hệ `Bidder` và `Seller` về thực thể chuẩn `Users` với bí danh khi join. `Bid` chứa cả hai khóa bid_id/request_id. Mỗi định thức không tầm thường của các quan hệ trên là khóa ứng viên, nên đạt BCNF theo tập FD đã công bố.

Phân rã không mất mát: lần lượt tách nhóm thuộc tính do `auction_id`, `asset_id`, `bidder_id`, `seller_id`, `category_id` xác định. Mỗi bước hai quan hệ có giao là một định thức X; X là khóa của quan hệ được tách ra, thỏa điều kiện lossless của phân rã nhị phân `X -> Y`. Lặp các bước bảo toàn lossless; join hai bản sao Users theo đúng bí danh bidder/seller phục hồi R.

Bảo toàn phụ thuộc: từng FD của Fmin nằm trọn trong một quan hệ sau phân rã; kiểm tra tại quan hệ đó không cần join. Các khóa thay thế email, request_id và cặp (auction_id, amount) đều được khai báo UNIQUE, nên mọi khóa ứng viên trong bảng phân tích đều được CSDL thực thi. Các phụ thuộc được bảo toàn này là FD; những ràng buộc như thời hạn, giá tăng, cây không chu trình và winner cùng phiên vẫn cần CHECK/FK/trigger/hàm, không suy ra chỉ từ chuẩn hóa.

### 4.7. Các quan hệ bổ sung

`registrations`: `(auction_id,user_id) -> status,registered_at`, khóa ghép là định thức; đạt BCNF theo FD nghiệp vụ. `results`: `auction_id -> winning_bid_id,closed_at`, khóa là auction_id; không lặp tên và giá thắng. Các bảng con tài sản có FD `asset_id -> các thuộc tính chuyên biệt`, đạt BCNF; serial_number không NULL là khóa thay thế có điều kiện của thiết bị khi được khai báo duy nhất, không coi nhiều NULL là cùng một số serial. `audit_log`: `id -> mọi thuộc tính còn lại`; timestamp và transaction_id không phải khóa vì một giao dịch có thể có nhiều sự kiện. Tên danh mục chỉ duy nhất trong một cha; không coi `name` là khóa toàn cục.

### 4.8. Cache là phi chuẩn hóa có kiểm soát

Lược đồ logic chuẩn hóa không cần `current_price` hoặc `leading_bid_id`, vì có thể tính từ bids. Lược đồ vật lý giữ chúng để kiểm tra giá và hiển thị nhanh. FD nội bảng của auction vẫn do ID xác định, nhưng **dữ liệu suy diễn bị lặp xuyên bảng**; việc gọi một bảng là BCNF không tự chứng minh cache đúng.

Mọi thao tác thêm bid, cập nhật cache và audit cùng transaction. Không cho app sửa cache hoặc lịch sử trực tiếp. Trigger cuối giao dịch và hàm `verify_invariants()` đối chiếu cache với lịch sử. Sau lỗi, rollback trả cả lịch sử/cache về trạng thái trước. Không cho xóa/sửa bid đã chấp nhận; sửa nghiệp vụ phải có quy trình mới, ngoài phạm vi đồ án.

## 5. SQL nâng cao và hàm nghiệp vụ

### 5.1. Truy vấn phân tích

`sql/04_queries.sql` cung cấp các nhóm truy vấn cần thiết:

- Phiên đang nhận giá và sắp kết thúc: lọc status, khoảng thời gian và sắp theo closes_at.
- Người đang dẫn: join auctions -> bids qua leading_bid_id -> users.
- Lịch sử thay đổi giá: dùng `LAG(amount)` trong partition từng phiên để tính chênh lệch, thứ tự thời gian/ID ổn định.
- Số người tham gia: nhóm registrations; phân biệt tổng đăng ký, đã duyệt và số bidder đã thực sự trả giá.
- Tỷ lệ thành công: số phiên đã đóng có winning_bid_id chia cho tổng số phiên đã đóng; tránh chia cho 0 và không tính phiên còn mở vào mẫu số.
- Tổng hợp cây danh mục: `WITH RECURSIVE` tạo tập hậu duệ rồi tổng hợp. Khi join đồng thời đăng ký và bids phải tổng hợp riêng hoặc `COUNT(DISTINCT ...)`, tránh nhân dòng.

Ví dụ truy vấn leader:

```sql
SELECT a.id AS auction_id, u.full_name, b.amount
FROM auction.auctions AS a
LEFT JOIN auction.bids AS b ON b.id = a.leading_bid_id
LEFT JOIN auction.users AS u ON u.id = b.bidder_id
ORDER BY a.id;
```

LEFT JOIN giúp vẫn thấy phiên chưa có bid. Người đang dẫn chưa phải người thắng chính thức.

### 5.2. Báo cáo có bộ lọc động

`auction.auction_report(p_status, p_category_id, p_min_price)` nhận bộ lọc tùy chọn; NULL nghĩa là bỏ lọc. Hàm viết bằng PL/pgSQL và dùng **SQL động**: chỉ ghép vào `WHERE` những điều kiện có tham số khác NULL, rồi chạy bằng `RETURN QUERY EXECUTE ... USING p_status, p_category_id, p_min_price`. Giá trị luôn đi qua tham số `$1, $2, $3` nên không thể SQL injection (test 18 thử chuỗi `OPEN' OR 1=1 --`); người dùng không bao giờ ghép chuỗi vào câu lệnh. Câu lệnh chỉ chứa điều kiện thật sự cần nên bộ tối ưu lập kế hoạch cho đúng tổ hợp bộ lọc. Lọc danh mục bao gồm toàn bộ cây con nhờ `WITH RECURSIVE`.

```sql
SELECT * FROM auction.auction_report(NULL, NULL, NULL);
SELECT * FROM auction.auction_report('OPEN', NULL, 100000);
```

Giá được lọc là giá hiển thị `COALESCE(current_price,start_price)`: phiên chưa có bid được xét theo giá khởi điểm. Biểu thức nằm trực tiếp trong `sql/02_functions.sql`.

### 5.3. Giao diện hàm

```sql
SELECT auction.place_bid(1::bigint, 2::bigint, 100000::numeric,
    '00000000-0000-4000-8000-000000000001'::uuid, 'row_lock');
SELECT auction.close_auction(2::bigint, 'row_lock');
SELECT * FROM auction.verify_invariants();
```

Ví dụ số tiền chỉ minh họa cú pháp; mức hợp lệ phải lấy từ cấu hình của phiên. Mỗi transaction client chỉ gọi một thao tác nghiệp vụ. Kết quả JSON phân biệt chấp nhận, phát lại và từ chối nghiệp vụ. Lỗi hạ tầng/xung đột transaction là ngoại lệ cần rollback/retry, không phải lượt bị từ chối do giá thấp.

## 6. Thiết kế transaction và kiểm soát đồng thời

### 6.1. Rủi ro khi đọc rồi ghi rời rạc

Giả sử giá đang 100, bước 10. T1 và T2 cùng đọc 100. T1 nhận 120; T2 nhận 110 dựa trên bản đọc cũ. Nếu T2 ghi cache sau T1 thì cache về 110 trong khi lịch sử có 120. Nếu đóng phiên đọc leader cũ giữa các câu lệnh, kết quả có thể không khớp bid được chấp nhận. UNIQUE kết quả ngăn hai dòng nhưng không tự chọn đúng người thắng; cần điều phối toàn nghiệp vụ.

### 6.2. Phương án A: READ COMMITTED và khóa dòng

Trình tự rút gọn:

1. Mở transaction READ COMMITTED; đồng bộ request_id để nhận biết replay/xung đột UUID.
2. `SELECT ... FROM auctions WHERE id = ... FOR UPDATE`.
3. Sau khi lấy khóa, đọc trạng thái mới, giờ hiện tại, người bán và đăng ký; kiểm tra mức giá.
4. Chèn bid, cập nhật current_price/leading_bid_id/revision và ghi audit.
5. COMMIT, hoặc ROLLBACK tất cả nếu lỗi.

Khóa phiên giữ đến cuối giao dịch. Một transaction khác cùng phiên chờ; khi được chạy phải kiểm tra trạng thái/giá mới. Các phiên khác nhau không bị khóa chung bằng một khóa toàn hệ thống. Tất cả đường trả giá/đóng phiên phải dùng cùng protocol; ghi bảng trực tiếp sẽ phá giả thiết.

Giao dịch đóng cũng khóa cùng dòng phiên, kiểm tra đã đến hạn, chốt leader hoặc NULL, chèn results rồi chuyển CLOSED trong cùng transaction. Nếu bid có quyền xử lý trước hạn thì close sau đó thấy bid; nếu close giành quyền khi đã hết hạn thì bid chờ phải thấy CLOSED hoặc hết hạn. Không có cửa sổ giữa ghi kết quả và đổi trạng thái mà transaction khác được phép dựa vào dữ liệu dở dang.

### 6.3. Phương án B: SERIALIZABLE và thử lại

Client phải `BEGIN ISOLATION LEVEL SERIALIZABLE` **trước câu lệnh đọc đầu tiên**. Hàm đọc phiên bình thường, kiểm tra điều kiện và cập nhật phiên; không dùng `SELECT FOR UPDATE` trên phiên như phương án A. Khi lịch xử lý không thể tuần tự hóa hoặc hai transaction cập nhật trên snapshot không tương thích, PostgreSQL hủy một transaction.

Client bắt SQLSTATE `40001` (serialization_failure) và `40P01` (deadlock_detected), rollback, chờ backoff có jitter rồi tạo transaction mới, đọc lại toàn bộ và gọi lại hàm với **cùng request_id**. Không chạy lại riêng UPDATE trên snapshot cũ. Retry có giới hạn; nếu hết giới hạn ghi riêng `exhausted` để không che giấu lỗi thành công giả.

Đóng phiên cũng phải chạy trong transaction SERIALIZABLE. Hàm từ chối nếu client chọn strategy này nhưng isolation hiện tại không đúng. SERIALIZABLE không có nghĩa không sử dụng khóa: PostgreSQL vẫn có khóa ghi thông thường, snapshot và cơ chế SSI; khác biệt là không chủ động tuần tự hóa bằng khóa đọc dòng phiên trong mã nghiệp vụ.

### 6.4. Idempotency và điểm chấp nhận

Khóa/điều phối theo UUID là bổ sung cho khóa phiên: khóa phiên riêng lẻ không ngăn cùng UUID được đưa vào hai phiên khác nhau. UNIQUE request_id là lớp bảo vệ cuối. Cần so sánh payload sau khi tìm thấy UUID, không đơn giản trả thành công cho bất kỳ người gửi nào dùng lại UUID.

Thời điểm chấp nhận nghiệp vụ xảy ra tại bước kiểm tra thời gian hợp lệ trong transaction giành quyền xử lý; kết quả chỉ có hiệu lực bên ngoài sau COMMIT. Các transaction có thể chồng lấn về thời gian nên không diễn giải SERIALIZABLE là thứ tự tăng theo timestamp client. Tính đúng dựa vào bất biến sau mỗi commit và protocol đồng nhất.

### 6.5. So sánh lý thuyết

| Tiêu chí | Khóa dòng | SERIALIZABLE + retry |
|---|---|---|
| Isolation client | READ COMMITTED | SERIALIZABLE |
| Cách bảo vệ phiên | Chủ động FOR UPDATE | Snapshot/SSI và xung đột cập nhật |
| Khi cạnh tranh | Chủ yếu chờ khóa | Có thể bị abort rồi làm lại |
| Mã client | Có xử lý lỗi transaction | Bắt buộc retry toàn transaction |
| Hotspot một phiên | Hàng đợi trên một dòng | Nhiều retry khi nhiều người cùng ghi |
| Quy tắc nhiều dòng | Phải xác định đầy đủ thứ tự khóa | Có thể phát hiện phụ thuộc đọc/ghi rộng hơn |
| Nguy cơ vận hành | Giữ khóa lâu, deadlock nếu sai thứ tự | Retry storm, exhausted khi đặt giới hạn thấp |

Không kết luận tuyệt đối về tốc độ từ bảng lý thuyết. Cả hai cùng ghi một dòng trạng thái nên đều có hotspot. Cần đo latency gồm retry và tỷ lệ yêu cầu hoàn thành dưới cùng cấu hình.

## 7. Mô hình đối tượng và OQL

Các lớp bắt buộc `TaiSan`, `PhienDauGia`, `LuotTraGia`, `NguoiThamGia`, `KetQuaDauGia`, quan hệ và ví dụ ODL/OQL được trình bày trong `docs/MO_HINH_DOI_TUONG_OQL.md`. Truy vấn mẫu gồm tìm phiên theo loại tài sản, duyệt collection lượt trả giá, tìm leader qua giá lớn nhất và đọc người thắng qua kết quả.

PostgreSQL thực thi SQL; OQL chỉ là phần đặc tả mô hình đối tượng. Lệnh `oql` là bản mô phỏng truy vấn tương đương bằng Python trên các đối tượng mẫu, có thể chạy để đối chiếu kết quả. Không khẳng định chạy OQL nguyên bản trong pgAdmin. Định danh đối tượng được ánh xạ về PK; object relationship được ánh xạ về FK/join.

## 8. Thiết kế thực nghiệm

### 8.1. Môi trường và cách tái lập

Máy Windows, PostgreSQL 18 đang chạy cục bộ, Python 3.12 và psycopg 3. Phiên bản chi tiết và thông số workload được lưu trong kết quả thực nghiệm. Ba CSDL riêng: demo để trình bày, `_test` cho kiểm thử, `_bench` cho benchmark. Chương trình từ chối thao tác reset của test/benchmark nếu tên đích không phù hợp hoặc trùng CSDL demo.

```powershell
.\.venv\Scripts\python.exe -m auction_lab test --output output/test-results.json
.\.venv\Scripts\python.exe -m auction_lab benchmark --workers 12 --waves 10 --rounds 3 --output output/benchmark
```

Benchmark đo **đúng bốn kịch bản của đề bài** cho cả hai giao thức (mã: `auction_lab/benchmark.py`):

| Mã | Kịch bản | Cách tạo tải | Kỳ vọng phải đạt |
|---|---|---|---|
| `dong_thoi` | Nhiều người trả giá cùng lúc | 12 người cùng trả **cùng một mức** giá tối thiểu, 10 đợt | Mỗi đợt đúng 1 ACCEPTED, 11 REJECTED |
| `gui_lai` | Yêu cầu được gửi lại | 12 bản sao cùng UUID và nội dung gửi đồng thời, 10 đợt | Mỗi đợt 1 ACCEPTED, 11 REPLAYED, không lượt trùng |
| `dong_phien` | Trả giá cạnh tranh với đóng phiên | 11 người trả giá liên tục theo đợt, 1 luồng đóng phiên đúng lúc hết hạn (phiên dài 1 giây) | 1 kết quả, người thắng = lượt cao nhất, 0 lượt sau hạn |
| `loi_giua` | Lỗi sau khi ghi lượt, trước khi cập nhật giá | Trigger thử nghiệm ném lỗi ngay sau `INSERT bids`; 12 người, 10 đợt | Mọi yêu cầu lỗi; 0 lượt, 0 nhật ký, giá vẫn NULL |

Mỗi vòng × giao thức tạo lại schema từ seed. Người trả, số tiền và UUID được sinh tất định, nên hai giao thức nhận **cùng một danh sách yêu cầu**; Barrier cho mọi worker xuất phát cùng lúc để tạo cạnh tranh thật; thứ tự giao thức đảo giữa các vòng. Mỗi worker giữ một kết nối suốt vòng đo.

### 8.2. Các kịch bản kiểm thử

1. Giá hợp lệ/không hợp lệ, người chưa duyệt, người bán tự trả, phiên chưa mở và phiên hết hạn.
2. Nhiều bidder cùng trả một mức: đúng một bid được chấp nhận, các yêu cầu còn lại bị từ chối do giá.
3. Dãy mức giá cạnh tranh: max-cache luôn khớp MAX lịch sử, leader thuộc đúng phiên.
4. Gửi lại cùng UUID và cùng nội dung: một bid duy nhất, các lần sau replay; cùng UUID khác payload: conflict.
5. Hai phiên khác nhau đồng thời dùng cùng UUID: không tạo hai bid, không lộ replay sai payload.
6. Trả giá cạnh tranh với đóng phiên: kết quả thống nhất với lịch sử, tối đa một kết quả và không nhận bid sau hạn.
7. Chờ khóa đi qua closes_at: yêu cầu phải bị từ chối dù bắt đầu transaction trước hạn.
8. Nhiều giao dịch đóng cùng phiên: chỉ một kết quả; các lần còn lại trả lại kết quả đã chốt.
9. Đóng phiên không có bid: một kết quả với winning_bid_id NULL.
10. Lỗi sau INSERT bids, trước UPDATE cache: trigger chỉ cài ở CSDL test phát sinh lỗi; rollback không để lại bid/cache/audit dở dang. Không thêm cửa hậu fault injection vào hàm production.
11. Chọn strategy serializable ở isolation sai: bị từ chối; retry thực sự đi qua transaction mới.
12. Kiểm tra ràng buộc lớp con tài sản, vòng danh mục và tính bất biến lịch sử theo các test đi kèm.

### 8.3. Chỉ số đo

`accepted`: yêu cầu tạo bid mới; `replayed`: trả lại bid đã có; `rejected`: vi phạm nghiệp vụ; `retries`: tổng lần phải chạy lại transaction; `exhausted`: hết giới hạn thử lại; `errors`: lỗi ngoài các loại dự kiến. Số yêu cầu logic là số lần client được gọi; tổng attempts có thể lớn hơn vì retry.

Latency đo từ lúc worker gọi hàm tới khi COMMIT xong, bao gồm chờ khóa, backoff và mọi lần retry. Mỗi worker giữ một kết nối nên **không** gồm thời gian mở kết nối TCP/xác thực (bản đo trước đây mở kết nối mới cho mỗi lần thử, làm độ trễ ~100 ms chủ yếu là chi phí kết nối và che mất khác biệt giữa hai giao thức). Mean/p50/p95 tính trên tất cả yêu cầu, kể cả bị từ chối; percentile dùng nearest-rank `ceil(q*n)`. Không chia throughput cho tổng attempts khi đang gọi đó là throughput yêu cầu logic.

### 8.4. Kết quả thực đo

<!-- BENCHMARK_RESULTS_START -->
Thời điểm đo: 09:25 ngày 08/11/2026 (giờ Việt Nam). Môi trường: PostgreSQL 18.6 x86_64 Windows, Python 3.12.10, psycopg 3.3.8, Windows 11; max_connections=100, shared_buffers=128MB, synchronous_commit=on. Nguồn: `output/benchmark/results.json`, `summary.csv` (24 dòng: 3 vòng × 2 giao thức × 4 kịch bản), `requests.csv` (từng yêu cầu).

Bảng gộp 3 vòng. Độ trễ tính trên mọi yêu cầu của kịch bản (kể cả bị từ chối/lỗi); p50/p95 theo nearest-rank trên toàn bộ mẫu gộp, không lấy trung bình các p95.

| Kịch bản | Giao thức | Yêu cầu | Nhận | Gửi lại | Từ chối | Lỗi | YC phải thử lại | Tổng lần thử lại | TB ms | p50 ms | p95 ms | Đạt kỳ vọng |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|
| 1. Nhiều người cùng trả | row_lock | 360 | 30 | 0 | 330 | 0 | 0 | 0 | 42.57 | 10.21 | 280.96 | 3/3 |
| 1. Nhiều người cùng trả | serializable | 360 | 30 | 0 | 330 | 0 | 330 | 330 | 15.07 | 14.91 | 27.85 | 3/3 |
| 2. Gửi lại cùng yêu cầu | row_lock | 360 | 30 | 330 | 0 | 0 | 0 | 0 | 5.82 | 4.69 | 9.88 | 3/3 |
| 2. Gửi lại cùng yêu cầu | serializable | 360 | 30 | 330 | 0 | 0 | 323 | 323 | 12.17 | 12.51 | 17.90 | 3/3 |
| 3. Trả giá vs đóng phiên | row_lock | 4334 | 393 | 0 | 3941 | 0 | 0 | 0 | 5.79 | 4.52 | 8.34 | 3/3 |
| 3. Trả giá vs đóng phiên | serializable | 2541 | 231 | 0 | 2310 | 0 | 2225 | 2225 | 9.95 | 10.17 | 14.34 | 3/3 |
| 4. Lỗi giữa giao dịch | row_lock | 360 | 0 | 0 | 0 | 360 | 0 | 0 | 4.88 | 4.67 | 7.35 | 3/3 |
| 4. Lỗi giữa giao dịch | serializable | 360 | 0 | 0 | 0 | 360 | 0 | 0 | 4.01 | 3.65 | 7.55 | 3/3 |

Cả 24 dòng đo đều có `exhausted=0`, 8/8 bất biến đạt và đạt kỳ vọng của kịch bản. Lỗi ở kịch bản 4 là lỗi **cố ý cài** (trigger ném `INJECTED_AFTER_BID_INSERT`), sau đó kiểm tra thấy 0 lượt, 0 dòng nhật ký, giá hiện tại vẫn NULL và `revision` vẫn 0. Ở kịch bản 3, kịch bản đếm số yêu cầu xử lý được trong cùng cửa sổ 1 giây nên số yêu cầu khác nhau giữa hai giao thức; giao dịch đóng phiên mất 2–5 ms, riêng một vòng row_lock 284 ms vì phải xếp hàng sau các lượt trả giá đang giữ khóa.

Bộ test hiện tại: **56/56 đạt** (39 kiểm thử lõi CSDL + 17 kiểm thử tầng HTTP), 0 failure, 0 error, 0 skip, theo `output/test-results.json`; cộng 8/8 kiểm thử JavaScript và 24/24 kiểm tra ràng buộc DDL bước 5.

Nhận xét trên số đo này:

- **Kết quả nghiệp vụ giống hệt nhau** ở kịch bản 1, 2, 4 (cùng số nhận/gửi lại/từ chối/lỗi): hai giao thức đều đúng; khác nhau ở **cách** đạt được.
- **SERIALIZABLE trả giá bằng thử lại**: ở kịch bản 1, mỗi người thua cuộc bị hủy đúng một lần (330/330) rồi chạy lại, đọc giá mới và bị từ chối `BID_TOO_LOW`. Trung vị cao hơn khóa dòng (14.9 so với 10.2 ms) nhưng đuôi rất ổn định (p95 27.9 ms).
- **Khóa dòng không thử lại** nhưng xếp hàng: người cuối hàng chờ 11 giao dịch trước, nên đuôi độ trễ dài (p95 281 ms, dao động mạnh giữa các vòng: 42 → 405 → 134 ms), một phần do bộ lập lịch Windows khi đánh thức tiến trình đang chờ khóa.
- Ở kịch bản 3, khóa dòng xử lý được nhiều yêu cầu hơn trong cùng 1 giây (4334 so với 2541) vì không tốn công làm lại giao dịch bị hủy.
- Kết luận chỉ áp dụng cho máy và tải này; không suy ra ưu thế tốc độ phổ quát.
<!-- BENCHMARK_RESULTS_END -->

### 8.5. Phân tích và giới hạn suy luận

Khóa dòng thường phù hợp với nghiệp vụ có điểm tranh chấp rõ là một phiên: dễ kiểm tra thứ tự, nhưng giao dịch giữ khóa lâu làm tăng thời gian chờ. SERIALIZABLE giúp bảo vệ lịch đọc/ghi theo khả năng tuần tự hóa, đổi lại có thể cần nhiều retry dưới hotspot. Cả hai chỉ đúng khi mọi thao tác liên quan tuân thủ protocol và quyền truy cập không cho đi vòng qua hàm.

So sánh tốc độ phải đi kèm số accepted/rejected/retries/exhausted: một phương án trả lỗi nhanh không thể được coi là tốt hơn chỉ vì mean latency thấp. Một lần benchmark trên máy cá nhân không đủ kết luận cho tải internet, dữ liệu lớn hoặc nhiều máy chủ. Số người thắng là hệ quả của quy tắc và lịch cạnh tranh, không là bằng chứng duy nhất về tính đúng.

## 9. Minh chứng tính đúng

### 9.1. Tối đa một kết quả thắng

PK `results.auction_id` ngăn hai dòng kết quả. Giao dịch đóng phối hợp với trả giá trên cùng trạng thái phiên. Kiểm tra winner thuộc cùng phiên và bằng leader/max lịch sử; phiên không bid có winner NULL. Kiểm thử close đồng thời và close/bid kiểm chứng các trường hợp cạnh tranh.

### 9.2. Cache khớp lịch sử

Bid, cache và audit cập nhật nguyên tử. Lịch sử bất biến; app không được DML trực tiếp. Kiểm tra tổng hợp `MAX(amount)` và leading_bid_id sau các đợt cạnh tranh, cộng trigger ràng buộc cuối transaction. `verify_invariants()` cần mọi dòng passed=true; không chỉ nhìn dòng giá cuối trên giao diện.

### 9.3. Không nhân đôi yêu cầu

UNIQUE request_id và protocol theo UUID ngăn trùng khi gửi đồng thời. So sánh payload bảo đảm chỉ replay yêu cầu giống nội dung. Kiểm tra `COUNT(*)` theo request_id và giữ bid_id cũ khi replay sau đóng phiên.

### 9.4. Không có dữ liệu dở dang

Lỗi chèn có thể làm sequence ID bị khuyết vì sequence không rollback; khoảng trống ID không phải mất dữ liệu. Điều cần chứng minh là không có bid/audit mới đã commit và cache vẫn ở giá trước sau lỗi giữa transaction. Test fault injection kiểm tra dữ liệu trước/sau và thực hiện lại thành công khi bỏ trigger test.

## 10. Hướng dẫn vận hành và hướng phát triển

README cung cấp lệnh chạy; `docs/HUONG_DAN_PGADMIN.md` chỉ cách dùng Query Tool và quan sát chờ khóa bằng hai cửa sổ. `docs/BAO_VE.md` đề xuất thứ tự demo, giải thích từng bất biến và các câu hỏi thường gặp.

`MO_HE_THONG.cmd` mở giao diện web cục bộ bằng máy chủ nền và dùng lại phiên máy chủ đã chạy; `DUNG_HE_THONG.cmd` dừng máy chủ giao diện; `CONG_CU_KIEM_THU.cmd` mở menu công cụ. Hướng dẫn thao tác giao diện nằm trong `docs/GIAO_DIEN.md`. Lệnh `scenario` là tên chính của kịch bản nghiệp vụ; tên `demo` vẫn được nhận như bí danh để tương thích hướng dẫn cũ. Tên CSDL `auction19_demo` giữ nguyên để không thay đổi kết nối và dữ liệu đã cài.

Tài khoản app chỉ có quyền đọc dữ liệu cần thiết và EXECUTE hàm nghiệp vụ; không cấp sửa bảng trực tiếp. SECURITY DEFINER phải cố định search_path an toàn, chỉ tham chiếu đối tượng tin cậy và thu hồi quyền EXECUTE mặc định PUBLIC khi cần. Chủ sở hữu CSDL vẫn là tài khoản quản trị tin cậy có thể thay đổi lược đồ; không coi ràng buộc trong ứng dụng là ranh giới chống superuser.

Hướng phát triển: quản lý duyệt đăng ký qua hàm có protocol rõ; quản lý vòng đời tài sản/phiên; job đóng phiên đến hạn; giao diện người dùng có xác thực; phân trang lịch sử; hàng đợi/thông báo sau commit; giám sát lock/retry; thêm thử nghiệm quy mô lớn và nhiều phiên. Thanh toán, đấu giá có giá dự trữ hoặc gia hạn chống sniping cần đặc tả lại quy tắc trước khi mở rộng.

## 11. Lớp giao diện web cục bộ

### 11.1. Mục đích và kiến trúc

Giao diện Đấu Giá Việt bổ sung cách thao tác bằng trình duyệt cho chính CSDL đã xây dựng. Các màn hình gồm danh sách/chi tiết phiên đấu giá, kết quả và thực nghiệm. Các bảng, khóa, chỉ mục, trigger, hàm trả giá/đóng phiên và bộ SQL gốc giữ nguyên; không thêm một bản database thay thế cho giao diện.

Luồng ghi nghiệp vụ:

```text
Trình duyệt
    -> HTTP API trên 127.0.0.1
    -> AuctionClient.bid / AuctionClient.close
    -> transaction READ COMMITTED hoặc SERIALIZABLE
    -> auction.place_bid / auction.close_auction
    -> bids + cache phiên + results + audit hiện có
```

HTTP server dùng thư viện chuẩn Python và phục vụ các tệp HTML/CSS/JavaScript cục bộ. Không cần cài Node.js, framework frontend hay tải font từ internet để chạy bản nộp. API đọc dùng truy vấn tham số hóa; dữ liệu tiền được tuần tự hóa thành chuỗi thập phân. Trình duyệt định dạng tiền để hiển thị, còn kiểm tra đúng giá/bước giá vẫn thực hiện trong PostgreSQL.

### 11.2. Quy tắc tương tác và tính đúng

Bộ chọn người tham gia liệt kê người đã được duyệt của phiên; đó là cơ chế mô phỏng danh tính trong đồ án, không phải đăng nhập thương mại. Thông tin thời gian máy chủ giúp hiển thị bộ đếm còn lại, nhưng không được dùng để thay quyết định hạn nhận của hàm SQL. Trường hợp giao diện còn hiển thị giá cũ khi một cửa sổ khác đã trả giá vẫn được xử lý đúng: hàm kiểm tra lại trạng thái trong transaction và có thể trả `BID_TOO_LOW`.

Mỗi ý định trả giá mới có UUID riêng. Thao tác gửi lại dùng lại cùng UUID và payload để quan sát idempotency. Chốt phiên đi qua hàm đóng hiện có, do đó không tự chốt sớm hoặc tạo thêm người thắng. Thông báo trên giao diện phân biệt từ chối nghiệp vụ, kết quả phát lại và lỗi hạ tầng; không coi phản hồi HTTP thành công là bằng chứng rằng một lượt trả giá đã được chấp nhận.

### 11.3. Thực nghiệm và kiểm chứng trên giao diện

Màn hình thực nghiệm đọc tám bất biến từ `auction.verify_invariants()` và đọc các kết quả kiểm thử/benchmark đã lưu kèm thời điểm. Các chỉ số lưu được ghi rõ là kết quả đợt đo trước, tách khỏi trạng thái hiện tại của phiên.

Kịch bản cạnh tranh cùng mức giá tạo các worker với kết nối PostgreSQL thật trong CSDL có hậu tố `_test`. Đợt chạy tạo phiên riêng và không reset dữ liệu vận hành của `auction19_demo`. Nếu dữ liệu kiểm thử chưa được khởi tạo, dùng chính SQL cài đặt sẵn có. Chỉ kịch bản thực nghiệm được định trước được cung cấp qua API; trình duyệt không được gửi câu SQL hay câu lệnh hệ điều hành tùy ý.

### 11.4. Phạm vi an toàn và giới hạn

Máy chủ lắng nghe loopback; yêu cầu ghi có token và kiểm tra Origin; API không trả chuỗi kết nối hay mật khẩu. Tài khoản app vẫn không được sửa trực tiếp bảng. Tài khoản chủ sở hữu chỉ phục vụ cài đặt/tạo dữ liệu thực nghiệm theo phạm vi đã công bố.

Đây là giao diện cho đồ án cục bộ, chưa có xác thực người dùng thực, thanh toán, giao nhận, thông báo ngoài hệ thống hoặc cơ chế vận hành internet. Khi mở rộng các chức năng này cần thiết kế thêm ranh giới xác thực và phân quyền, không được xem bộ chọn người tham gia hiện tại là ranh giới bảo mật.

### 11.5. Kiểm chứng lớp giao diện và bảo toàn CSDL

Bên cạnh 52 kiểm thử Python/HTTP, 8 kiểm thử JavaScript kiểm tra định dạng tiền vượt giới hạn số nguyên an toàn, nhập tiền tiếng Việt, ranh giới thời gian, thay bộ lọc khi có request cũ, cập nhật sau giao dịch và chuyển cửa sổ phiên. Kết quả được lưu ở `output/frontend-test-results.xml`. Các kiểm thử này chạy mã JavaScript độc lập; không được diễn giải thành kiểm thử trình duyệt đầu cuối.

Đối chiếu trước/sau trong `output/bao-toan-csdl.json` cho thấy toàn bộ script SQL và bản dump cấu trúc schema auction không thay đổi, 8/8 bất biến đều đạt. Giao diện không yêu cầu đổi tên CSDL vận hành, chạy migration hay ghi lại dữ liệu mẫu.

## Tài liệu tham khảo

1. Silberschatz, Korth, Sudarshan. *Database System Concepts*, 7th edition, slides chương 6-7 (E-R, chuẩn hóa), 17-19 (transaction, đồng thời, phục hồi), 29 (CSDL đối tượng): https://www.db-book.com/slides-dir/index.html .
2. PostgreSQL Global Development Group. PostgreSQL 18, *Explicit Locking*: https://www.postgresql.org/docs/18/explicit-locking.html .
3. PostgreSQL Global Development Group. PostgreSQL 18, *Transaction Isolation*: https://www.postgresql.org/docs/18/transaction-iso.html .
4. PostgreSQL Global Development Group. PostgreSQL 18, *WITH Queries*: https://www.postgresql.org/docs/18/queries-with.html .
5. PostgreSQL Global Development Group. PostgreSQL 18, *Constraints*: https://www.postgresql.org/docs/18/ddl-constraints.html .

Tài liệu giao đề là nguồn xác định phạm vi và các minh chứng cần nộp. Các quy tắc cụ thể như lưới giá, thời điểm xét sau chờ khóa, idempotency chỉ lưu lượt đã nhận và không có giá dự trữ là quyết định thiết kế được công bố trong báo cáo, không trình bày như yêu cầu nguyên văn của giảng viên.
