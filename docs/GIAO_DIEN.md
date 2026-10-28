# Hướng dẫn sử dụng giao diện Đấu Giá Việt

## 1. Mở hệ thống

Trên máy đã cấu hình PostgreSQL và `.env`, bấm đúp **`MO_HE_THONG.cmd`** trong thư mục dự án. Trình duyệt mở địa chỉ **http://127.0.0.1:8765**. Máy chủ chạy nền nên không cần giữ cửa sổ dòng lệnh. Nếu hệ thống đã chạy, bấm mở lần nữa chỉ mở trình duyệt dùng lại máy chủ đó.

Khi dùng xong, bấm đúp **`DUNG_HE_THONG.cmd`** để dừng máy chủ giao diện. Thao tác này không dừng dịch vụ PostgreSQL và không xóa dữ liệu.

Nếu muốn chạy bằng PowerShell:

```powershell
.\.venv\Scripts\python.exe -m auction_lab.web --open
```

Khi chạy trực tiếp bằng lệnh này, giữ cửa sổ PowerShell đang chạy; nhấn **Ctrl+C** để dừng. Đây là cách chạy ở cửa sổ hiện tại, khác với trình khởi động chạy nền.

Không mở `web/index.html` trực tiếp bằng File Explorer: giao diện cần HTTP API để đọc và thao tác với PostgreSQL. CSDL đang dùng vẫn có tên **`auction19_demo`**; không cần đổi tên, chạy lại setup hay nhập lại dữ liệu.

Giao diện là lớp tương tác của đồ án. Việc chọn người tham gia là mô phỏng danh tính trong lớp học, chưa phải một hệ thống đăng nhập thương mại. Dữ liệu tài sản và người dùng đều giả lập.

## 2. Tìm một phiên đấu giá

Tại khu vực **Phiên đấu giá**:

1. Nhập tên tài sản vào ô tìm kiếm nếu cần.
2. Dùng bộ lọc trạng thái hoặc loại tài sản để thu hẹp danh sách.
3. Sắp xếp theo thời gian kết thúc, phiên mới hoặc giá.
4. Mở một tài sản để xem chi tiết phiên, giá khởi điểm, bước giá, thời gian, người đang dẫn đầu và lịch sử trả giá.

Các trạng thái hiển thị được suy ra từ trạng thái trong CSDL và thời gian máy chủ: đang nhận giá, chưa mở, đã hết giờ chờ chốt, hoặc đã chốt. Bộ đếm trên màn hình chỉ hỗ trợ quan sát; quyết định nhận hay từ chối vẫn dựa vào đồng hồ PostgreSQL trong giao dịch.

## 3. Trả giá

Chọn một phiên đang nhận giá. Trong phần chi tiết:

1. Chọn một **người tham gia** trong danh sách được duyệt của phiên.
2. Chọn cơ chế **khóa dòng** hoặc **SERIALIZABLE** nếu muốn so sánh hai phương án.
3. Nhập mức giá tối thiểu đang hiển thị hoặc một mức cao hơn đúng bước giá.
4. Bấm **Trả giá ngay** và chờ phản hồi.

Có thể bấm **Giá tối thiểu** để điền nhanh mức tối thiểu hiện tại. Cách nhập đơn giản là `1050000`; giao diện cũng nhận dạng dấu chấm phân cách hàng nghìn kiểu Việt Nam và dấu phẩy thập phân, chẳng hạn `1.050.000` hoặc `1050000,50`. Số tiền được chuẩn hóa rồi gửi dưới dạng chuỗi thập phân để tránh sai số tiền tệ của JavaScript.

Nếu được chấp nhận, lịch sử có thêm một lượt và giá hiện tại/người dẫn đầu được tải lại từ CSDL. Nếu bị từ chối, thông báo giải thích nguyên nhân; các trường hợp thường gặp là giá thấp, sai bước, phiên chưa mở hoặc đã hết giờ. Khi có cạnh tranh, giá có thể thay đổi sau khi bạn xem mức tối thiểu, vì vậy từ chối giá thấp là hành vi đúng của hệ thống.

Không sửa `current_price`, `leading_bid_id`, `status` hoặc `closes_at` trực tiếp trong pgAdmin để làm cho thao tác thành công. Các giá trị suy diễn phải được cập nhật qua hàm nghiệp vụ.

## 4. Gửi lại cùng yêu cầu

Sau một lượt trả giá được chấp nhận, bấm **Gửi lại yêu cầu vừa gửi**. Hệ thống dùng lại cùng UUID, người tham gia, số tiền và mã phiên của lượt cuối, dù bạn đã sửa ô nhập trên màn hình.

Thông báo mong đợi là **Đã nhận diện yêu cầu gửi lại**, tương ứng mã **REPLAYED**: CSDL trả lại lượt cũ, giữ nguyên mã lượt và thời điểm chấp nhận. Lịch sử không tăng thêm một dòng. Thao tác gửi lại trên giao diện luôn giữ nguyên payload cũ; quy tắc `IDEMPOTENCY_CONFLICT` cho cùng UUID nhưng payload khác được kiểm chứng trong bộ test/API.

Một lần trả giá mới là ý định mới và nhận UUID mới. Tự động retry do xung đột transaction giữ nguyên UUID của ý định đang thực hiện.

## 5. Thử hai người trả giá

1. Mở cùng địa chỉ hệ thống trong hai cửa sổ trình duyệt.
2. Cả hai mở cùng một phiên đang nhận giá.
3. Chọn hai người tham gia khác nhau, nhập cùng mức giá hợp lệ.
4. Bấm **Trả giá ngay** gần nhau; một lượt được nhận trước sẽ thay đổi mức tối thiểu của phiên.

Nếu hai yêu cầu thực sự cạnh tranh ở cùng giá, tối đa một lượt được chấp nhận; lượt sau bị từ chối do giá thấp. Khi dùng SERIALIZABLE, client có thể rollback và chạy lại toàn giao dịch trước khi đưa ra kết quả cuối. Thứ tự bấm từ phía người dùng không phải cam kết thứ tự thắng.

Thao tác thủ công không bảo đảm gửi đồng thời chính xác. Dùng khu vực **Kiểm soát đồng thời** ở mục 8 để tạo các worker bắt đầu cùng nhau và kiểm chứng có hệ thống.

## 6. Chốt phiên và xem kết quả

Phiên đã hết giờ nhưng còn `OPEN` không nhận thêm giá. Bấm **Chốt kết quả phiên** trong phần chi tiết để gọi hàm đóng phiên hiện có. Nút chốt chỉ xuất hiện khi đã hết hạn hoặc phiên đã chốt.

- Chưa tới hạn: giao diện chưa cho chốt; hàm SQL vẫn bảo vệ bằng mã `TOO_EARLY` nếu được gọi trực tiếp từ CLI/API.
- Đã tới hạn: ghi kết quả và chuyển trạng thái trong cùng giao dịch.
- Phiên đã chốt: nút đổi thành **Xem lại kết quả đã chốt**; gọi lại trả kết quả cũ, không tạo người thắng thứ hai.
- Không có lượt hợp lệ: kết quả có người thắng NULL; giao diện thể hiện phiên không có người thắng.

Chuyển sang khu vực **Kết quả** để xem người thắng và giá thắng của các phiên đã đóng. Giá thắng được lấy từ lượt mà kết quả tham chiếu, không phải bản sao do trình duyệt tự lưu.

## 7. Kiểm chứng tính nhất quán

Trong **Kiểm soát đồng thời**, chạy/tải lại phần kiểm tra bất biến. Kết quả đúng là mọi kiểm tra đều đạt:

1. Giá hiện tại bằng giá cao nhất trong lịch sử.
2. Lượt dẫn đầu thuộc đúng phiên và khớp lịch sử.
3. Mỗi phiên có tối đa một dòng kết quả.
4. Phiên đóng có kết quả tương ứng với người dẫn đầu.
5. UUID của lượt trả giá không trùng.
6. Giá và thời gian của lượt được nhận đúng quy tắc.
7. Mỗi tài sản thuộc đúng một lớp con phù hợp.
8. Bid/kết quả có nhật ký cùng giao dịch.

Có thể đối chiếu trong Query Tool của `auction19_demo`:

```sql
SELECT * FROM auction.verify_invariants();
```

Tất cả dòng phải có `passed = true`.

## 8. Chạy thực nghiệm cạnh tranh

Trong **Kiểm soát đồng thời**, chọn cơ chế và số người gửi yêu cầu, sau đó bấm **Chạy thực nghiệm** để chạy kịch bản cạnh tranh cùng mức giá. Các worker dùng kết nối PostgreSQL thật; đây không phải một hoạt ảnh mô phỏng kết quả.

Kịch bản này dùng **CSDL có hậu tố `_test`**, tạo thêm một phiên dành riêng cho đợt chạy; không reset hay thay dữ liệu vận hành của `auction19_demo`. Nếu schema kiểm thử chưa tồn tại, chương trình có thể khởi tạo bằng chính bộ SQL sẵn có của đồ án. Tài khoản app của CSDL vận hành không được cấp quyền ghi trực tiếp bảng.

Với cùng mức giá và các người tham gia hợp lệ, kết quả mong đợi:

- Đúng một yêu cầu được chấp nhận.
- Các yêu cầu khác bị từ chối do giá không còn đủ cao.
- Lượt thử lại được thống kê khi thực sự xảy ra.
- Mọi bất biến đều đạt sau đợt chạy.

Không bắt buộc SERIALIZABLE phải phát sinh retry trong mọi lần chạy nhỏ; lịch thực thi phụ thuộc máy và hệ điều hành. Dùng benchmark CLI hoặc bộ kiểm thử có đồng bộ bằng Event để xem minh chứng xung đột bắt buộc.

Trang này cũng đọc kết quả kiểm thử/benchmark đã lưu cùng thời điểm ghi nhận. Số liệu lưu là kết quả của một lần đo trước đó; không coi đó là số đếm trực tiếp của các thao tác vừa làm trên giao diện. Chạy lại bộ benchmark nếu cần tạo số đo mới.

## 9. Công cụ dòng lệnh và kiểm thử đầy đủ

Bấm đúp **`CONG_CU_KIEM_THU.cmd`** để mở menu kiểm thử, hoặc dùng:

```powershell
.\.venv\Scripts\python.exe -m auction_lab scenario
.\.venv\Scripts\python.exe -m auction_lab scenario --strategy serializable
.\.venv\Scripts\python.exe -m auction_lab verify
.\.venv\Scripts\python.exe -m auction_lab test
.\.venv\Scripts\python.exe -m auction_lab benchmark
```

`scenario` tạo một phiên nghiệp vụ ngắn, chạy trả giá, replay, cạnh tranh, chốt và kiểm chứng. Tên lệnh cũ `demo` chỉ là bí danh tương thích. Những file kết quả đi kèm bản nộp dùng tên `kich-ban-nghiep-vu.json`, `kich-ban-serializable.json` và `truy-van-doi-tuong.json`.

Không chạy test/benchmark CLI cùng lúc với thực nghiệm trên giao diện: bộ test đầy đủ có quyền tạo lại schema của CSDL kiểm thử riêng để tái lập dữ liệu.

## 10. Khi gặp sự cố

- **Không vào được trang:** bấm lại `MO_HE_THONG.cmd`, dùng đúng địa chỉ/port mà chương trình thông báo. Với cách chạy PowerShell trực tiếp, kiểm tra cửa sổ máy chủ còn hoạt động.
- **Không kết nối PostgreSQL:** kiểm tra service PostgreSQL, `.env`, tên CSDL và hai tài khoản dự án; không đưa mật khẩu vào ảnh chụp hoặc GitHub.
- **Hết giờ nhưng chưa có người thắng:** chốt phiên bằng thao tác trên giao diện; hết giờ nhận giá và ghi kết quả là hai điều kiện khác nhau.
- **Giá thấp hoặc sai bước:** xem lại giá hiện tại và bước giá rồi gửi một yêu cầu mới.
- **Dữ liệu vừa thay đổi ở cửa sổ khác:** chờ lần tải lại hoặc làm mới; quyết định cuối vẫn được kiểm tra trong CSDL.
- **Không có phiên đang nhận giá:** dùng `scenario` để tạo kịch bản ngắn hoặc phần thực nghiệm độc lập. Các phiên mẫu dùng mốc thời gian tương đối của lần cài đầu, không tự kéo dài hạn sau mỗi lần mở giao diện.

## 11. Cấu trúc và giới hạn

Luồng thao tác là: trình duyệt -> HTTP API cục bộ -> `AuctionClient` -> `auction.place_bid`/`auction.close_auction` -> các bảng và trigger hiện có. Phần giao diện không thay định nghĩa database hay sao chép quy tắc đấu giá sang một cơ chế ghi bảng khác.

Các API đọc dùng truy vấn tham số hóa; API ghi yêu cầu token và kiểm tra Origin. Máy chủ chỉ lắng nghe địa chỉ loopback. Đồ án chưa có xác thực đăng nhập, thanh toán, giao nhận hay triển khai truy cập internet; không mở máy chủ này ra mạng công cộng như một hệ thống đấu giá thương mại.
