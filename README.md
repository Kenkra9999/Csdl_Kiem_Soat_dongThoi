# Đề tài 19 - Hệ thống đấu giá và kiểm soát trả giá đồng thời

Đồ án Cơ sở dữ liệu nâng cao trên **PostgreSQL 18 + Python 3.12**. Mô phỏng tài sản, cây danh mục, đăng ký, trả giá, chốt kết quả và nhật ký. Chỉ triển khai **bài 19** của tài liệu hướng dẫn.

Phần cốt lõi là hai phương án xử lý cùng một nghiệp vụ:

- `row_lock`: `READ COMMITTED` và khóa dòng phiên bằng `SELECT ... FOR UPDATE`.
- `serializable`: giao dịch `SERIALIZABLE`, phát hiện xung đột và chạy lại **toàn bộ giao dịch** khi gặp SQLSTATE `40001` hoặc `40P01`.

## Bắt đầu trên Windows

**Trên máy đã cấu hình sẵn, bấm đúp `CHAY_DEMO.cmd`** để mở menu tiếng Việt: xem phiên, demo nghiệp vụ, kiểm tra, chạy test và benchmark so sánh hai cơ chế. Hoặc mở PowerShell tại thư mục dự án, dùng môi trường `.venv` hiện có; PostgreSQL phải đang chạy:

```powershell
.\.venv\Scripts\python.exe -m auction_lab list
.\.venv\Scripts\python.exe -m auction_lab demo
.\.venv\Scripts\python.exe -m auction_lab verify
```

Lệnh `demo` trình diễn nghiệp vụ; `verify` kiểm tra các bất biến trong CSDL. Chi tiết tùy chọn chính xác của từng lệnh:

```powershell
.\.venv\Scripts\python.exe -m auction_lab --help
.\.venv\Scripts\python.exe -m auction_lab bid --help
```

Nếu cài trên máy khác:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\provision.py
```

Script provision hỏi thông tin quản trị PostgreSQL bằng `getpass`, tạo ba CSDL riêng, hai tài khoản dự án và `.env`. Mật khẩu quản trị không được lưu. Script từ chối ghi đè `.env`, role hay CSDL dự án đã tồn tại. Tài khoản owner không có CREATEDB; app chỉ được gọi hàm nghiệp vụ sau setup. Khi provision xong, chạy:

```powershell
.\.venv\Scripts\python.exe -m auction_lab setup
.\.venv\Scripts\python.exe -m auction_lab list
```

`DATABASE_URL` kết nối tài khoản sở hữu để cài lược đồ; `APP_DATABASE_URL` là kết nối tài khoản ứng dụng nếu đã thiết lập quyền tối thiểu. Các biến `TEST_DATABASE_URL` và `BENCH_DATABASE_URL` phải trỏ vào CSDL riêng. **Không đưa `.env` lên GitHub.** Xem `.env.example` và hướng dẫn cài đặt kèm dự án để cấu hình trên máy mới.

Nếu đã tự tạo tài khoản/CSDL, có thể sao chép `.env.example` thành `.env` rồi điền kết nối thay cho provision. Không chạy provision sau khi đã tạo `.env` thủ công.

## Kiểm thử và thực nghiệm

```powershell
.\.venv\Scripts\python.exe -m auction_lab test
.\.venv\Scripts\python.exe -m auction_lab benchmark
.\.venv\Scripts\python.exe -m auction_lab oql
```

Kiểm thử/benchmark dùng các CSDL dùng riêng có tên mang hậu tố `_test`/`_bench`, có thể tạo lại dữ liệu trong schema `auction` ở các CSDL đó. CSDL demo được giữ riêng. Kết quả đo là số liệu chạy thực tế, có thể thay đổi theo CPU, tải máy và lịch chạy giao dịch; không dùng một lần đo để tuyên bố phương án luôn nhanh hơn.

## Tài liệu để học và bảo vệ

- [Báo cáo PDF 23 trang](output/pdf/BAO_CAO_DE_TAI_19.pdf), có sơ đồ EER và các phụ lục chạy thử.
- [Báo cáo đầy đủ](docs/BAO_CAO.md): đặc tả, EER, khóa và chuẩn hóa, SQL, transaction, thực nghiệm.
- [Mô hình EER](docs/EER.md): sơ đồ quan hệ và chuyên biệt hóa tài sản.
- [Mô hình đối tượng và OQL](docs/MO_HINH_DOI_TUONG_OQL.md): ODL/OQL học thuật và cách đối chiếu với bản mô phỏng Python.
- [Hướng dẫn pgAdmin](docs/HUONG_DAN_PGADMIN.md): chạy SQL, mở hai Query Tool để quan sát khóa.
- [Kịch bản trình bày và câu hỏi bảo vệ](docs/BAO_VE.md).

Kết quả xác minh đi kèm: **35/35 test đạt**, benchmark 360 yêu cầu với 12 worker và 3 round cho mỗi cơ chế; mọi đợt đạt 8/8 bất biến, không có lỗi hoặc hết giới hạn retry. Số liệu chi tiết nằm trong `output/test-results.json`, `output/benchmark/summary.csv`, `results.json`, `requests.csv` và mục 8 báo cáo. Đây là số đo trên máy hiện tại, không là cam kết tốc độ trên máy khác.

Để tạo lại PDF báo cáo sau khi cập nhật Markdown/số liệu, cài `requirements-report.txt` và chạy `scripts/build_report.py` bằng Python trong `.venv`. Việc chạy demo và kiểm thử chỉ cần `requirements.txt`.

Các script SQL theo thứ tự:

1. `sql/01_schema.sql`: bảng, khóa, ràng buộc và chỉ mục.
2. `sql/02_functions.sql`: trả giá, đóng phiên, báo cáo lọc và kiểm tra bất biến.
3. `sql/03_seed.sql`: dữ liệu giả lập.
4. `sql/04_queries.sql`: truy vấn nâng cao.
5. `sql/05_verify.sql`: kiểm chứng dữ liệu.
6. `sql/06_permissions.sql` nếu có: tách tài khoản ứng dụng khỏi quyền ghi trực tiếp bảng.

## Quy tắc quan trọng

Lượt đầu từ giá khởi điểm; các lượt sau phải tăng ít nhất một bước và nằm trên lưới giá. Hai yêu cầu cùng mức giá: chỉ yêu cầu được xử lý hợp lệ trước thắng; yêu cầu còn lại phải đọc lại trạng thái rồi bị từ chối. Hạn nhận giá là khoảng `[opens_at, closes_at)`, kiểm tra bằng đồng hồ máy chủ sau khi giành quyền xử lý. UUID của yêu cầu giúp gửi lại không sinh thêm lượt trả giá. Kết quả có khóa chính `auction_id`, nên mỗi phiên có tối đa một dòng kết quả.

`current_price` là giá cao nhất đã được chấp nhận, **không phải giá khởi điểm**. Khi chưa có lượt trả giá, trường này để `NULL`; giá thắng được suy ra từ lượt trả giá mà kết quả tham chiếu.

Đây là hệ thống mô phỏng phục vụ môn học: chưa có thanh toán, xác minh danh tính, giao nhận, đấu giá kín hoặc chống gian lận thương mại. PostgreSQL không thực thi OQL nguyên bản; ví dụ OQL trong tài liệu được trình bày riêng với SQL và mã Python.

## Nguồn tham khảo

- [PostgreSQL 18 - Explicit Locking](https://www.postgresql.org/docs/18/explicit-locking.html)
- [PostgreSQL 18 - Transaction Isolation](https://www.postgresql.org/docs/18/transaction-iso.html)
- [PostgreSQL 18 - WITH Queries](https://www.postgresql.org/docs/18/queries-with.html)
- [Database System Concepts, 7th edition - slides](https://www.db-book.com/slides-dir/index.html), chương 6-7, 17-19 và 29.
