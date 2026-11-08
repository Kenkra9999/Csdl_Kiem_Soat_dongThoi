# Kịch bản trình bày và giải thích đồ án

Có thể mở `MO_HE_THONG.cmd` để trình bày trên giao diện Đấu Giá Việt. Giữ pgAdmin bên cạnh để đối chiếu dữ liệu và `verify_invariants()`. Nếu muốn chạy bằng dòng lệnh, dùng `CONG_CU_KIEM_THU.cmd` hoặc các lệnh `scenario` bên dưới. Cấu trúc và quy tắc CSDL giống nhau ở cả hai cách thao tác.

## 1. Trình bày khoảng 10-15 phút

### Phút 0-2: vấn đề và quy tắc

“Đề tài của em là hệ thống đấu giá trực tuyến. Khó khăn là nhiều người trả giá đồng thời và một giao dịch khác đóng phiên. Em cần bảo đảm mỗi lượt được kiểm tra trên trạng thái hợp lệ, giá hiện tại khớp lịch sử và chỉ có một kết quả cuối.”

Nêu giá khởi điểm, bước giá, khoảng nhận `[opens_at,closes_at)`, người được duyệt, người bán không tự trả. Hai yêu cầu cùng giá chỉ một được nhận theo thứ tự xử lý hợp lệ; không hứa theo thứ tự click từ máy khách.

### Phút 2-4: mô hình dữ liệu

Mở `docs/EER.md` hoặc sơ đồ SVG kèm dự án. Chỉ ra total/disjoint của tài sản và ba bảng con. Giải thích vì sao seller/bidder là quan hệ theo phiên. Chỉ các khóa quan trọng: registration khóa ghép, request UUID UNIQUE, results khóa chính auction_id.

Nêu `start_price`, `bids.amount`, `current_price`, giá thắng là bốn khái niệm có liên quan nhưng không được dùng lẫn. Cache NULL khi chưa có bid; kết quả winner NULL khi phiên kết thúc không có bid.

### Phút 4-6: chuẩn hóa

Mở mục 4 của báo cáo. Minh họa quan hệ rộng lặp lại tên người bán và cấu hình phiên trong mỗi bid. Trình bày `bid_id -> auction_id -> asset_id -> seller_id`; phân rã về các bảng riêng, giữ FK. Hai khóa định danh của quan hệ quan sát bid là bid_id và request_id; quy tắc tăng giá còn tạo khóa nghiệp vụ `(auction_id,amount)`. Phủ tối tiểu tách RHS một thuộc tính, không chứa FD thừa. Lossless vì giao của từng bước tách là khóa quan hệ được tách; dependency preserving vì từng FD nằm trong một quan hệ.

Cache max không tự đúng vì BCNF; đây là dữ liệu lặp xuyên bảng được giữ nhất quán bằng transaction và kiểm tra cuối giao dịch.

### Phút 6-9: trình diễn trả giá và đóng phiên

```powershell
.\.venv\Scripts\python.exe -m auction_lab scenario --strategy row_lock
```

Đọc các bước theo JSON: nhận lượt đầu, replay cùng UUID, hai người cùng trả một mức chỉ một được nhận, đóng sớm bị từ chối, đóng đúng hạn, đóng lại trả kết quả cũ. Mỗi lần chạy tạo phiên mới nên có thể thực hiện lại.

Mở pgAdmin, chạy `SELECT * FROM auction.verify_invariants();`. Giải thích từng invariant và đối chiếu bid/cache/result của ID vừa demo. Nếu có thời gian làm hai Query Tool theo hướng dẫn để thấy chờ khóa.

### Phút 9-12: so sánh và minh chứng

Mở bảng mục 8.4 báo cáo (hoặc `output/benchmark/summary.csv`). Benchmark đo đúng 4 kịch bản đề bài × 2 giao thức × 3 vòng, cùng danh sách yêu cầu tất định. Ý chính: số nhận/gửi lại/từ chối **giống hệt nhau** giữa hai giao thức (cả hai đều đúng); khác ở cách đạt được — SERIALIZABLE hủy mỗi người thua một lần rồi chạy lại (330 lần thử lại ở kịch bản 1), khóa dòng không thử lại nhưng xếp hàng nên đuôi độ trễ dài hơn. Không kết luận chiến lược nào luôn nhanh hơn từ ba vòng cục bộ.

Mở `output/test-results.json`: các test quan trọng là cùng giá, UUID đồng thời/liên phiên, bid/close race, chờ khóa qua deadline, lỗi sau INSERT và retry transaction thực. Nêu số test thực trong tệp thay vì học thuộc một con số nếu vừa chạy lại phiên bản mới.

### Phút 12-15: đối tượng, OQL và giới hạn

```powershell
.\.venv\Scripts\python.exe -m auction_lab oql
```

Trình bày lớp bắt buộc và truy vấn theo collection. Nói rõ PostgreSQL chạy SQL; OQL là đặc tả học thuật, chương trình chạy bản truy vấn Python tương đương. Kết thúc bằng giới hạn: dữ liệu giả lập, chưa có thanh toán/xác thực, benchmark cục bộ và hotspot một phiên.

## 2. Câu hỏi thường gặp

### Vì sao không chỉ đặt UNIQUE cho người thắng?

UNIQUE ngăn hai dòng nhưng không chọn đúng leader hoặc ngăn một bid được chấp nhận sau khi kết quả đã đọc. Cần giao dịch đóng phối hợp với giao dịch trả giá, cộng PK và kiểm tra winner/max.

### Vì sao không chỉ dùng một lệnh UPDATE giá cao nhất?

Nghiệp vụ còn phải kiểm tra đăng ký, người bán, giờ đóng, idempotency; chèn lịch sử và audit phải cùng thành công. Một UPDATE có điều kiện có thể là thành phần thiết kế khác, nhưng không thay thế việc chứng minh toàn bộ transaction.

### READ COMMITTED có đủ an toàn không?

Có cho protocol này khi trước mọi quyết định quan trọng đều khóa dòng phiên và mọi đường ghi tuân thủ cùng thứ tự. Chỉ chọn READ COMMITTED mà không khóa/điều phối không tự bảo đảm an toàn.

### SERIALIZABLE có loại bỏ mọi khóa không?

Không. Mã phương án B không chủ động FOR UPDATE trên dòng phiên, nhưng PostgreSQL vẫn có khóa ghi, snapshot và SSI. Cạnh tranh có thể dẫn đến serialization_failure; cần retry toàn transaction.

### Tại sao retry phải dùng cùng UUID?

Client có thể không biết commit đã thành công nếu kết nối mất ngay sau commit. Dùng lại UUID giúp trả lại bid cũ thay vì tạo thao tác mới. Tạo UUID mới khi retry có thể làm một ý định trở thành nhiều lượt trả giá.

### Nếu cùng UUID nhưng người khác hoặc số tiền khác?

Đó là conflict, không được replay thành công tùy tiện. Payload cần so khớp auction_id, bidder_id và amount; UNIQUE toàn cục kết hợp protocol request xử lý cả hai phiên khác nhau.

### Request bị từ chối có được cache không?

Không trong thiết kế này. Chỉ lượt chấp nhận có dòng bền vững. Yêu cầu bị từ chối có thể được đánh giá lại khi trạng thái thay đổi, chẳng hạn đăng ký được duyệt. Đây là lựa chọn thiết kế được công bố, không là API ledger lưu mọi kết quả.

### Người gửi trước hạn nhưng chờ khóa đến sau hạn thì sao?

Bị từ chối. Deadline dựa trên giờ CSDL sau khi giành quyền xử lý, không dựa trên timestamp máy khách. Dùng clock_timestamp vì now cố định từ đầu transaction.

### Chưa có bid thì current_price bằng giá khởi điểm được không?

Có thể thiết kế vậy nhưng dễ lẫn “đã có người trả giá”. Đồ án chọn current_price NULL và hiển thị COALESCE(current_price,start_price); giá thắng chỉ lấy từ bid thực.

### Vì sao schema có cache mà vẫn nói chuẩn hóa?

Phần logic được phân rã theo FD đạt BCNF. Phần vật lý thêm dữ liệu suy diễn vì hiệu quả đọc. FD nội bảng và dư thừa xuyên bảng là hai điều cần phân biệt; transaction, quyền và invariant giữ cache nhất quán.

### Lỗi sau INSERT có làm ID bị bỏ qua không?

Có thể, vì sequence không rollback. ID bị khuyết không chứng minh có bid dở dang; kiểm tra nội dung bid/cache/audit đã commit mới chứng minh tính nguyên tử.

### Vì sao dùng trigger hoãn cho lớp con tài sản?

Vì chèn bảng cha rồi mới chèn bảng con trong cùng transaction. Kiểm tra total ngay sau INSERT cha sẽ từ chối dữ liệu cuối giao dịch vốn hợp lệ. Kiểm tra cuối giao dịch vừa cho phép thứ tự chèn vừa bảo đảm đúng một lớp con.

### Vì sao kịch bản 1, 2, 4 có số accepted giống hệt nhau giữa hai giao thức, còn kịch bản 3 thì khác?

Kịch bản 1, 2, 4 được thiết kế theo đợt: trong mỗi đợt mọi người gửi cùng một mức giá (hoặc cùng một UUID), nên kết quả đúng chỉ có một: đúng 1 lượt được nhận mỗi đợt. Giống nhau là bằng chứng cả hai giao thức đều đúng. Kịch bản 3 đếm số yêu cầu xử lý được trong cùng cửa sổ 1 giây trước giờ đóng, nên giao thức nhanh hơn xử lý được nhiều đợt hơn; điều phải giống nhau ở đây là bất biến: đúng 1 kết quả, người thắng là lượt cao nhất, 0 lượt sau hạn.

### OQL chạy trực tiếp trên PostgreSQL được không?

Không. Các câu OQL là đặc tả ODMG để trình bày hướng đối tượng; có bản SQL và mô phỏng Python tương đương cho dữ liệu mẫu. Không đưa OQL vào Query Tool như SQL thực thi.

### Superuser có sửa dữ liệu làm sai quy tắc được không?

Tài khoản quản trị tin cậy có thể thay lược đồ hoặc vô hiệu hóa bảo vệ. Đồ án tách owner/app; app chỉ gọi hàm và không ghi bảng trực tiếp. Không tuyên bố chống được người quản trị có toàn quyền.

## 3. Trước khi nộp

- Bổ sung thông tin sinh viên/lớp/giảng viên theo thực tế vào bản báo cáo nếu mẫu trường yêu cầu.
- Giữ nguyên `.env` ngoài Git; hướng dẫn người chấm cấu hình `.env.example` trên máy khác.
- Chạy `verify`, bộ test và benchmark nếu có thay đổi code; cập nhật bảng số liệu cùng bản PDF.
- Kiểm tra các tệp SQL, báo cáo, sơ đồ, kết quả thực đo và hướng dẫn được đưa vào bản nộp.
- Chuẩn bị giải thích các quy tắc bằng lời của mình và chạy lại demo, không chỉ đọc báo cáo.
