# Bước 05 - Tạo cơ sở dữ liệu và viết DDL chuẩn BCNF

Bộ SQL này thực hiện phần tạo cơ sở dữ liệu, bảng, khóa và ràng buộc của đề tài 19. Máy đã cài PostgreSQL và pgAdmin 4 nên không cần cài đặt lại.

Đây là **các tệp mã để tải về và tự chạy**. Bản bàn giao không tự cài lược đồ vào PostgreSQL trên máy người dùng. Các bước dùng pgAdmin dưới đây chỉ là hướng dẫn khi bạn chủ động thực hiện.

Các tên như `NguoiDung`, `GiaKhoiDiem`, `BuocGia` khớp với nhãn tiếng Việt trong sơ đồ. Bộ bài nộp dùng cơ sở dữ liệu riêng **`dau_gia_19_bcnf`**, lược đồ **`dau_gia`**. Các bảng tiếng Anh và dữ liệu của hệ thống web hiện tại được giữ nguyên.

## 1. Các tệp cần dùng

- [00_tao_database.sql](../sql/buoc_05/00_tao_database.sql): tạo cơ sở dữ liệu riêng.
- [01_tao_bang.sql](../sql/buoc_05/01_tao_bang.sql): tạo 11 bảng, khóa, ràng buộc, chỉ mục, kiểm tra chuyên biệt hóa tài sản và khung nhìn thông tin phiên.
- [02_kiem_tra.sql](../sql/buoc_05/02_kiem_tra.sql): đọc danh mục hệ thống để kiểm tra các đối tượng đã tạo.
- [03_thu_rang_buoc.sql](../sql/buoc_05/03_thu_rang_buoc.sql): thử dữ liệu hợp lệ và dữ liệu vi phạm ràng buộc trong giao dịch được hoàn tác.

Bốn bảng chính theo yêu cầu bài tập là `NguoiDung`, `TaiSan`, `PhienDauGia`, `LuotTraGia`. Các bảng còn lại giữ những quan hệ đã có trên sơ đồ: `DanhMuc`, `TacPhamNgheThuat`, `DoSuuTam`, `ThietBiDienTu`, `DangKyThamGia`, `KetQuaDauGia`, `NhatKyThayDoi`.

## 2. Chạy trong pgAdmin 4

### Bước 1: Tạo cơ sở dữ liệu

1. Trong Object Explorer, mở máy chủ PostgreSQL đang dùng.
2. Bấm phải cơ sở dữ liệu `postgres`, chọn **Query Tool**.
3. Sử dụng kết nối quản trị có quyền `CREATEDB`, chẳng hạn tài khoản `postgres` đã thiết lập khi cài máy.
4. Bật **Auto-commit** trong Query Tool. Mở tệp `sql/buoc_05/00_tao_database.sql`, thực thi bằng **Execute/F5**.

`CREATE DATABASE` phải chạy ngoài giao dịch; không bọc lệnh này trong `BEGIN ... COMMIT`. Nếu gặp lỗi thiếu quyền tạo cơ sở dữ liệu, chuyển sang kết nối quản trị; không cần thay đổi quyền của tài khoản chạy ứng dụng.

Nếu tên `dau_gia_19_bcnf` đã tồn tại, không xóa cơ sở dữ liệu đó để chạy lại. Kiểm tra xem đây có phải cơ sở dữ liệu đã tạo cho bước này hay không, rồi dùng kết nối tương ứng cho các bước sau.

### Bước 2: Tạo bảng

1. Bấm phải nhóm **Databases**, chọn **Refresh** để thấy `dau_gia_19_bcnf`.
2. Bấm phải **`dau_gia_19_bcnf`**, mở một **Query Tool mới**. Tab đang nối vào `postgres` không tự chuyển sang cơ sở dữ liệu mới.
3. Chạy câu sau để kiểm tra kết nối:

```sql
SELECT current_database(), current_user;
```

Giá trị `current_database` phải là `dau_gia_19_bcnf`.

4. Mở `sql/buoc_05/01_tao_bang.sql`, chạy toàn bộ tệp bằng **F5**. Khi không chọn một đoạn văn bản, Query Tool chạy toàn bộ nội dung trong cửa sổ.
5. Làm mới **Schemas → dau_gia → Tables** để thấy 11 bảng. Khung nhìn nằm trong **Views**.

Đây là bộ cài lược đồ mới cho bài tập. Không chạy nó vào cơ sở dữ liệu đang chứa dữ liệu của hệ thống web, không thêm lệnh `DROP ... CASCADE` để vượt qua lỗi đối tượng đã tồn tại.

### Bước 3: Kiểm tra cấu trúc và ràng buộc

Trong chính Query Tool của `dau_gia_19_bcnf`:

1. Chạy `02_kiem_tra.sql` để xem bảng, cột, khóa và các đối tượng hỗ trợ.
2. Chạy `03_thu_rang_buoc.sql` để thử các ràng buộc. Tệp này kết thúc bằng hoàn tác giao dịch nên không giữ lại dữ liệu thử.
3. Có thể xem trực tiếp bốn bảng chính:

```sql
SELECT * FROM dau_gia."NguoiDung";
SELECT * FROM dau_gia."TaiSan";
SELECT * FROM dau_gia."PhienDauGia";
SELECT * FROM dau_gia."LuotTraGia";

SELECT "MaPhien", "GiaKhoiDiem", "BuocGia",
       "GiaHienTai", "MaLuotDanDau"
FROM dau_gia."ThongTinPhienDauGia";
```

Các bảng mới có thể chưa có dòng dữ liệu; điều này bình thường vì bước này tập trung vào DDL. Phải giữ dấu ngoặc kép quanh tên CamelCase, ví dụ `"NguoiDung"`: PostgreSQL sẽ chuyển tên không có ngoặc kép về chữ thường.

Nếu một thao tác bị hủy giữa chừng và pgAdmin báo giao dịch đang lỗi, chạy `ROLLBACK;` trước khi chạy lại. Không coi việc không có lỗi cú pháp là bằng chứng đầy đủ rằng thiết kế đạt BCNF; phần chứng minh nằm ở mục tiếp theo.

## 3. Vì sao bốn bảng chính đạt BCNF?

Một quan hệ đạt BCNF khi với mọi phụ thuộc hàm không tầm thường `X → Y`, `X` là siêu khóa. Một bảng có khóa chính chưa đủ để kết luận BCNF: cần xét các phụ thuộc phát sinh từ quy tắc nghiệp vụ.

Phân tích dưới đây dựa trên các giả định đã công bố: một người có thể sở hữu nhiều tài sản; một tài sản có thể được đưa vào nhiều phiên; họ tên, tên tài sản và số tiền không duy nhất trên toàn hệ thống. Không giả định thêm phụ thuộc như `HoTen → MaNguoiDung`, `TenTaiSan → MaTaiSan` hay `SoTien → MaLuotTraGia`.

### 3.1. NguoiDung

Phụ thuộc hàm:

```text
MaNguoiDung → HoTen, DiaChiThuDienTu, ThoiDiemTao
DiaChiThuDienTu → MaNguoiDung
```

Khóa ứng viên là `MaNguoiDung` và `DiaChiThuDienTu`. Địa chỉ thư điện tử được khai báo `NOT NULL UNIQUE`; từ địa chỉ này suy ra mã người dùng, rồi suy ra mọi thuộc tính còn lại. Mỗi định thức không tầm thường trong tập phụ thuộc công bố là một khóa ứng viên, nên bảng đạt BCNF và do đó đạt 3NF.

### 3.2. TaiSan

```text
MaTaiSan → MaNguoiBan, MaDanhMuc, LoaiTaiSan,
           TenTaiSan, MoTa, ThoiDiemTao
```

Khóa ứng viên là `MaTaiSan`. Mã người bán không xác định tài sản vì một người có thể bán nhiều tài sản. Tên danh mục, họ tên và địa chỉ thư điện tử của người bán nằm trong các bảng tương ứng, không được sao chép vào `TaiSan`. Định thức của các phụ thuộc không tầm thường đã công bố là khóa, nên bảng đạt BCNF.

### 3.3. PhienDauGia

```text
MaPhien → MaTaiSan, GiaKhoiDiem, BuocGia,
          ThoiDiemMo, ThoiDiemDong, TrangThai, PhienBan
```

Khóa ứng viên là `MaPhien`. `MaTaiSan` không là khóa: sơ đồ cho phép một tài sản có nhiều phiên, với thời gian và cấu hình giá khác nhau. Thông tin mô tả tài sản và thông tin người bán được truy xuất qua khóa ngoại, không lặp vào bảng phiên. Theo tập phụ thuộc này, bảng đạt BCNF.

`PhienBan` là thuộc tính kỹ thuật phục vụ việc thay đổi trạng thái phiên; nó không xác định duy nhất một phiên và không được coi là khóa.

### 3.4. LuotTraGia

```text
MaLuotTraGia → MaPhien, MaNguoiTraGia, SoTien,
              MaYeuCau, ThoiDiemChapNhan
MaYeuCau → MaLuotTraGia
(MaPhien, SoTien) → MaLuotTraGia
```

Ba khóa ứng viên là:

- `MaLuotTraGia`: khóa chính.
- `MaYeuCau`: `NOT NULL UNIQUE`, định danh yêu cầu trên toàn hệ thống.
- `(MaPhien, SoTien)`: hai cột bắt buộc có giá trị, có ràng buộc `UNIQUE` để không lưu hai lượt được chấp nhận cùng mức giá trong một phiên.

Mỗi khóa trên xác định toàn bộ thuộc tính của lượt trả giá. Riêng `MaPhien` không xác định một lượt vì một phiên có nhiều lượt; riêng `SoTien` cũng không xác định một lượt vì các phiên khác nhau có thể cùng mức giá. Các định thức không tầm thường đã công bố đều là khóa ứng viên, nên bảng đạt BCNF.

`MaNguoiTraGia` tham chiếu người đã đăng ký đúng phiên qua khóa ngoại ghép `(MaPhien, MaNguoiTraGia)`. Không lưu thêm họ tên, thư điện tử, giá khởi điểm hay tên tài sản trong bảng này, nhờ đó tránh những phụ thuộc bắc cầu từ các mã tham chiếu sang dữ liệu mô tả.

## 4. Các bảng hỗ trợ và những điểm dễ nhầm

- `DanhMuc`: mã danh mục xác định thông tin danh mục. Cặp danh mục cha và tên danh mục là duy nhất; tên riêng lẻ không duy nhất toàn hệ thống. Quy tắc các danh mục gốc không trùng tên cũng phải được giữ khi mã cha không có giá trị.
- Ba lớp con tài sản: `MaTaiSan` vừa là khóa chính vừa là khóa ngoại tới `TaiSan`, xác định các thuộc tính chuyên biệt. Ràng buộc cuối giao dịch bảo đảm mỗi tài sản có đúng một lớp con phù hợp với `LoaiTaiSan`.
- `ThietBiDienTu`: số sê-ri duy nhất khi có giá trị, nhưng có thể không có số sê-ri. Không dùng cột `UNIQUE` cho phép `NULL` này làm một khóa ứng viên vô điều kiện trong chứng minh lý thuyết.
- `DangKyThamGia`: `(MaPhien, MaNguoiDung) → TrangThai, ThoiDiemDangKy`. Khóa ghép ngăn đăng ký trùng; từng mã riêng lẻ không xác định một đăng ký.
- `KetQuaDauGia`: `MaPhien → MaLuotThang, ThoiDiemChot`. Mỗi phiên có tối đa một dòng kết quả. Không có lượt thắng thì `MaLuotThang` không có giá trị; không thêm một mã kết quả mới. Khóa ngoại ghép buộc lượt thắng thuộc đúng phiên.
- `NhatKyThayDoi`: mã nhật ký xác định sự kiện. Mã giao dịch và thời điểm ghi không là khóa vì một giao dịch có thể ghi nhiều sự kiện. Chi tiết sự kiện không thay thế cho các bảng nghiệp vụ.

## 5. Ánh xạ giá hiện tại từ sơ đồ sang bản DDL logic

Sơ đồ đã vẽ `GiaHienTai` và `MaLuotDanDau` trong thông tin phiên. Trong bộ DDL logic này, hai giá trị được lấy từ lịch sử `LuotTraGia` qua khung nhìn `dau_gia."ThongTinPhienDauGia"`, không lưu thành hai cột trong bảng gốc `PhienDauGia`.

Nếu phiên chưa có lượt được chấp nhận, cả hai giá trị không có giá trị. Nếu đã có lượt, khung nhìn trả mức giá cao nhất và mã lượt tương ứng của chính phiên đó. Giá thắng được lấy từ lượt mà `KetQuaDauGia` tham chiếu, không sao chép thêm số tiền thắng hoặc thông tin người thắng vào bảng kết quả.

Đây là lựa chọn tách dữ liệu gốc và dữ liệu suy diễn cho phần nộp chuẩn hóa. Việc hệ thống đang chạy lưu thêm giá hiện tại để xử lý nhanh không tự động chứng minh bảng đó vi phạm BCNF; chuẩn hóa nội bảng và sự nhất quán của dữ liệu suy diễn giữa các bảng là hai vấn đề cần phân biệt. Bộ DDL mới không thay đổi cơ chế lưu giá của hệ thống đang chạy.

## 6. Phạm vi của CREATE TABLE

DDL bảo vệ các định danh, tham chiếu, mức giá dương, thứ tự thời điểm mở/đóng và các ràng buộc cấu trúc được khai báo. `NUMERIC(18,2)` lưu tiền với hai chữ số thập phân; PostgreSQL có thể làm tròn đầu vào nhiều chữ số hơn, nên không mô tả kiểu này là cơ chế tự động từ chối mọi đầu vào có trên hai chữ số thập phân.

Các quy tắc sau cần được xử lý ở phần hàm/giao dịch nghiệp vụ và các kiểm tra bổ sung, không thể khẳng định đã được bảo đảm đầy đủ chỉ bằng việc có khóa chính và khóa ngoại:

- Người đăng ký phải đang được duyệt, người bán không tự trả giá tài sản của mình.
- Thời điểm chấp nhận thuộc khoảng mở/đóng; mức giá tuân theo bước giá và cao hơn trạng thái mới nhất.
- Cây danh mục không tạo chu trình nhiều cấp.
- Chốt phiên phải phối hợp nguyên tử với trả giá và chọn đúng lượt thắng cao nhất.
- Yêu cầu gửi lại phải được xử lý đúng nội dung; `UNIQUE MaYeuCau` mới chỉ là lớp ngăn bản ghi trùng.

Hệ thống hiện tại đã có các hàm nghiệp vụ cho những bước này. Không chạy trực tiếp các hàm của schema tiếng Anh `auction` trên các bảng tiếng Việt của bộ DDL mới nếu chưa viết phần ánh xạ tương ứng.

## 7. Tệp cần đưa lên Git

Phần nộp bước 05 gồm thư mục `sql/buoc_05/` và tài liệu này. Không thêm `.env`, mật khẩu hoặc chuỗi kết nối chứa mật khẩu vào commit. Commit phần DDL và kiểm tra của bước này riêng để người chấm dễ xem thay đổi.

Ví dụ lệnh khi tự thực hiện từ thư mục dự án:

```powershell
git add sql/buoc_05 docs/BUOC_05_DDL_BCNF.md
git diff --cached --stat
git commit -m "Add topic 19 Vietnamese BCNF database DDL"
git push origin main
```

Kết quả thực thi và mã commit thực tế phải được đối chiếu sau khi chạy; các lệnh ví dụ này không phải bằng chứng rằng cơ sở dữ liệu đã được tạo hoặc mã đã được đẩy lên kho từ xa.

CI của kho mã chạy bốn tệp SQL trên một PostgreSQL 18 riêng của GitHub Actions. Dữ liệu của 23 kiểm tra ràng buộc được hoàn tác. Kết quả cấu trúc và kiểm tra được đính kèm artifact của lần chạy CI; việc này không truy cập PostgreSQL trên máy của bạn.
