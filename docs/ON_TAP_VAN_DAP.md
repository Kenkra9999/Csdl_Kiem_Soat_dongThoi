# Ôn tập vấn đáp – Đề tài 19: Đấu giá trực tuyến và kiểm soát trả giá đồng thời

> Đọc file này trước khi gặp thầy. Mỗi mục trả lời một câu hỏi thầy có thể hỏi; chi tiết đầy đủ nằm ở [BAO_CAO.md](BAO_CAO.md).
> Số liệu trong file đo ngày 08/11/2026 trên máy Windows của nhóm (PostgreSQL 18.6).

---

## 0. Nói trong 30 giây

**Câu hỏi nghiên cứu:** làm sao để mỗi lượt trả giá được kiểm tra trên trạng thái đúng, không mất cập nhật và không có hai người thắng cho một phiên?

**Trả lời của đồ án:**

1. **Mọi thay đổi của một phiên đi qua một "cửa" duy nhất là dòng phiên** (`auction.auctions`). Trả giá và đóng phiên đều phải ghi dòng này trước khi ghi gì khác. Hai giao dịch không thể cùng ghi một dòng, nên luôn có thứ tự.
2. **Hai cách giữ cửa:** khóa dòng (`SELECT … FOR UPDATE`, người sau chờ) hoặc `SERIALIZABLE` (người sau bị hủy với lỗi `40001` rồi chạy lại toàn bộ giao dịch).
3. **CSDL tự chặn dữ liệu sai** dù code có lỗi: `PRIMARY KEY results(auction_id)` (tối đa 1 kết quả), `UNIQUE(request_id)` (gửi lại không nhân đôi), `UNIQUE(auction_id, amount)` (cùng giá chỉ một lượt), trigger kiểm tra lúc COMMIT rằng giá hiện tại = giá cao nhất trong lịch sử.

---

## 1. Đề yêu cầu gì → làm ở đâu → minh chứng

| Bước của đề | Sản phẩm | Minh chứng chạy được |
|---|---|---|
| 1. Đặc tả quy tắc | BAO_CAO mục 2; README "Quy tắc quan trọng" | test 01–09 |
| 2. EER | [eer/EER_DE_TAI_19_DA_SUA.pdf](eer/EER_DE_TAI_19_DA_SUA.pdf), [EER.md](EER.md) | DDL bước 5 ánh xạ đúng sơ đồ |
| 3. Phụ thuộc hàm, chuẩn hóa | BAO_CAO mục 4, [BUOC_05_DDL_BCNF.md](BUOC_05_DDL_BCNF.md), `sql/buoc_05/` | 24/24 kiểm tra ràng buộc |
| 4. SQL nâng cao | `sql/04_queries.sql` (Q1–Q11), `sql/02_functions.sql` | test 18, 35 |
| 5. Transaction, so sánh 2 phương án | `sql/02_functions.sql`, `auction_lab/db.py` | test 10–17, 28, 32 |
| 6. Mô hình đối tượng, OQL | [MO_HINH_DOI_TUONG_OQL.md](MO_HINH_DOI_TUONG_OQL.md), `auction_lab/objects.py` | lệnh `oql` |
| 7. Thực nghiệm | `auction_lab/benchmark.py`, `output/benchmark/` | bảng mục 7 file này |

| Minh chứng đề bắt buộc | Cơ chế | Test / số liệu |
|---|---|---|
| Mỗi phiên tối đa 1 kết quả | PK `results.auction_id` + đóng phiên dùng chung giao thức với trả giá | test 09, 13, 32; kịch bản 3 |
| Giá cao nhất lưu riêng khớp lịch sử | cập nhật cùng giao dịch + trigger DEFERRED kiểm tra lúc COMMIT + `verify_invariants()` | 8/8 bất biến sau mọi lần đo |
| Gửi lại không tạo lượt trùng | advisory lock theo UUID + `UNIQUE(request_id)` + so khớp nội dung | test 02, 03, 11, 12; kịch bản 2 |
| Lỗi giữa giao dịch không để dữ liệu dở dang | một giao dịch nguyên tử; lỗi ⇒ ROLLBACK | test 15; kịch bản 4 |
| Bảng so sánh 2 giải pháp cùng dữ liệu/cấu hình | benchmark tất định 4 kịch bản × 2 giao thức × 3 vòng | BAO_CAO mục 8.4 |

---

## 2. Kết quả rà soát: đồ án đã đúng chưa?

**Kết luận:** phần lõi (hàm trả giá, đóng phiên, chống gửi lại, trigger kiểm tra, phân quyền, bộ test) **đã đúng** – không phát hiện lỗi làm sai kết quả đấu giá. Các vấn đề dưới đây là chỗ thiếu ràng buộc, đo chưa đúng yêu cầu, hoặc khó đọc; tất cả đã được sửa và kiểm chứng lại.

| # | Vấn đề tìm thấy | Mức độ | Đã sửa | Tệp |
|---|---|---|---|---|
| 1 | Báo cáo coi `(auction_id, amount)` là khóa ứng viên, DDL bước 5 có `UNIQUE`, nhưng **schema chạy thật lại không khai báo** → ba chỗ mâu thuẫn nhau. | Trung bình | Thêm `CONSTRAINT bids_auction_id_amount_key UNIQUE (auction_id, amount)`; bỏ chỉ mục cũ trùng chức năng. Test 33 ghi thẳng vào bảng vẫn bị chặn. | `sql/01_schema.sql` |
| 2 | **Một tài sản có thể nằm trong hai phiên đang mở cùng lúc** (ví dụ cùng một bức tranh bán ở hai phiên, có thể ra hai người thắng cho một món đồ). Code cũ còn tự tạo nhiều phiên mở cho tài sản 1; test bước 5 số 02 cũng chấp nhận điều này. | Trung bình | Chỉ mục duy nhất có điều kiện `ON auctions(asset_id) WHERE status='OPEN'` ở cả hai bộ DDL; fixture tạo tài sản mới cho mỗi phiên; test 34 và kiểm tra bước 5 số 24. | `sql/01_schema.sql`, `sql/buoc_05/01_tao_bang.sql`, `auction_lab/fixtures.py` |
| 3 | **Thực nghiệm chưa đo đủ 4 kịch bản đề yêu cầu**: chỉ đo một dãy giá xáo trộn; "đóng phiên cạnh tranh" và "lỗi giữa giao dịch" chỉ có trong test, không có số đo. Số lượt được nhận khác nhau giữa 2 phương án nên khó so sánh. | Cao (ảnh hưởng điểm bước 7) | Viết lại benchmark: 4 kịch bản, danh sách yêu cầu tất định, mỗi kịch bản có điều kiện "đạt kỳ vọng". | `auction_lab/benchmark.py` |
| 4 | Benchmark **mở kết nối mới cho mỗi lần thử**: độ trễ ~100 ms gần như toàn là chi phí kết nối, che mất khác biệt giữa hai phương án. | Trung bình | Mỗi worker giữ một kết nối (`AuctionClient._run(..., conn=...)`). Độ trễ còn 5–15 ms và thấy rõ chi phí thử lại của SERIALIZABLE. | `auction_lab/db.py` |
| 5 | "Báo cáo có bộ lọc động" chỉ là tham số tùy chọn `(p IS NULL OR …)`, chưa phải SQL động. | Thấp | Viết lại bằng PL/pgSQL: chỉ ghép điều kiện cần thiết, chạy `RETURN QUERY EXECUTE … USING` (an toàn SQL injection). Test 35. | `sql/02_functions.sql` |
| 6 | Hàm `SECURITY DEFINER` không đặt `pg_temp` cuối `search_path` (tài liệu PostgreSQL khuyến nghị vì `pg_temp` mặc định được tìm **đầu tiên**). | Thấp (mọi bảng đã ghi rõ schema) | `SET search_path = pg_catalog, auction, pg_temp`. | `sql/01_schema.sql`, `sql/02_functions.sql` |
| 7 | Dùng `txid_current()` – thuộc nhóm hàm "Deprecated" trong PostgreSQL 18. | Thấp | `(pg_current_xact_id()::text)::bigint`. | cả hai bộ DDL |
| 8 | SQL khó đọc: dồn nhiều lệnh một dòng, biến `v_a`, `v_b`, kiểm tra tham số lặp lại. | Trung bình (khó trình bày) | Viết lại theo từng BƯỚC có chú thích tiếng Việt, đổi tên biến, tách hàm dùng chung `auction.require_strategy`. **Hành vi giữ nguyên** – toàn bộ test cũ vẫn đạt. | `sql/01_schema.sql`, `sql/02_functions.sql` |
| 9 | EER: thuộc tính suy diễn vẽ như thuộc tính thường; khóa ứng viên thứ hai không gạch chân; thiếu ghi chú thuộc tính phân loại; thiếu ràng buộc "một phiên mở / tài sản". | Trung bình | Xem mục 4. | `docs/eer/` |
| 10 | Tài liệu lệch: số test, "23 kiểm tra", hướng dẫn pgAdmin tạo phiên trên tài sản 1 (sẽ lỗi sau sửa #2). | Thấp | Cập nhật README, BAO_CAO, BAO_VE, BUOC_05, HUONG_DAN_PGADMIN. | `docs/` |
| 11 | Giao diện web: khi từ chối sớm một yêu cầu ghi (sai token/Origin), máy chủ đóng kết nối mà chưa đọc phần thân → Windows gửi RST, trình duyệt mất thông báo lỗi 403 (hiện "lỗi mạng"). Test HTTP số 09 lỗi chập chờn ~1/15 lần. | Thấp | Đọc bỏ phần thân (tối đa 128 KB) trước khi đóng. Chạy lặp 15 lần: bản cũ lỗi 1, bản sửa lỗi 0. | `auction_lab/web.py` |

**Những phần đã kiểm tra kỹ và giữ nguyên vì đúng:** kiểm tra hạn hai lần (trước và sau khi giành quyền ghi); khóa tư vấn theo UUID để chống gửi lại liên phiên; đổi `unique_violation` thành `40001` ở SERIALIZABLE; FK kép `(leading_bid_id, id)` và `(winning_bid_id, auction_id)` chứng minh lượt thuộc đúng phiên; trigger DEFERRED cho chuyên biệt hóa toàn phần/phân ly; chặn chu trình danh mục bằng advisory lock; tách tài khoản owner/app; lịch sử bất biến.

**Kiểm chứng sau khi sửa (chạy trên PostgreSQL 18.6):** 56/56 test Python/HTTP (thêm test 33–36), 8/8 test JavaScript, 24/24 kiểm tra DDL bước 5, 24/24 dòng benchmark đạt kỳ vọng và 8/8 bất biến. Đã thử nâng cấp một CSDL cài bằng **bản cũ** có dữ liệu: chạy `07_nang_cap.sql` → `01` → `02` → `06`, dữ liệu giữ nguyên, 8/8 bất biến.

---

## 3. Hai cơ chế kiểm soát đồng thời – giải thích bằng dòng thời gian

**Nếu không kiểm soát (mất cập nhật):** giá đang 100, bước 10. T1 đọc 100, T2 đọc 100. T1 ghi lượt 120 và đặt giá = 120. T2 (dựa trên bản đọc cũ) ghi lượt 110 và đặt giá = 110. Kết quả: lịch sử có 120 nhưng giá hiện tại là 110 → **sai**.

### Phương án A – `row_lock`: READ COMMITTED + `SELECT … FOR UPDATE`

```text
     T1 (An trả 110)                          T2 (Bình trả 110)
t1   BEGIN; SELECT phiên FOR UPDATE  → có khóa
t2                                            BEGIN; SELECT phiên FOR UPDATE → CHỜ
t3   giá NULL → tối thiểu 100; 110 hợp lệ
     INSERT lượt; UPDATE giá = 110; ghi nhật ký
t4   COMMIT (nhả khóa)
t5                                            có khóa, đọc bản MỚI: giá 110 → tối thiểu 120
t6                                            110 < 120 → REJECTED BID_TOO_LOW; COMMIT
```

Ý chính: người sau **chờ**, rồi đọc trạng thái mới nhất (READ COMMITTED lấy snapshot mới cho mỗi câu lệnh). Không có lần chạy lại.

### Phương án B – `serializable`: SERIALIZABLE + thử lại

```text
     T1                                       T2
t1   BEGIN SERIALIZABLE; đọc phiên (giá NULL)
t2                                            BEGIN SERIALIZABLE; đọc phiên (giá NULL)
t3   UPDATE phiên (revision+1) → giành quyền
     INSERT lượt 110; UPDATE giá; nhật ký
t4                                            UPDATE phiên → CHỜ T1
t5   COMMIT
t6                                            lỗi 40001 "could not serialize access"
t7                                            client ROLLBACK, chạy lại TỪ BEGIN (cùng UUID)
t8                                            snapshot mới: giá 110 → 110 < 120 → REJECTED
```

Ý chính: không khóa khi đọc; PostgreSQL phát hiện xung đột lúc ghi và **hủy** người sau; client phải chạy lại **toàn bộ** giao dịch (không chỉ câu lệnh lỗi), giữ nguyên `request_id` để lần chạy lại không thành lượt mới.

### Đóng phiên phối hợp với trả giá thế nào?

`close_auction` dùng **cùng giao thức**: khóa dòng phiên (A) hoặc ghi dòng phiên rồi bị 40001 nếu xung đột (B). Vì vậy:

- Nếu lượt trả giá giành quyền ghi trước giờ đóng → đóng phiên phải chờ/làm lại → **thấy lượt đó** và chọn nó làm người thắng (test 32 giữ lượt chưa COMMIT qua giờ đóng để chứng minh).
- Nếu đóng phiên giành quyền trước → lượt trả giá đọc thấy `CLOSED` → `NOT_OPEN`.
- Lượt trả giá kiểm tra hạn **hai lần**: trước khi đọc và **sau khi giành quyền ghi** – vì có thể đã chờ khóa vượt quá giờ đóng (test 14).

### Vì sao không có dữ liệu dở dang?

Ghi lượt, cập nhật giá, ghi nhật ký nằm trong **một giao dịch**. Lỗi ở bất kỳ đâu (kịch bản 4 cố ý cài trigger ném lỗi ngay sau `INSERT bids`) ⇒ cả giao dịch ROLLBACK ⇒ không còn lượt, không còn nhật ký, giá vẫn như cũ. Mã lượt (sequence) có thể bị nhảy số – đó **không** phải dữ liệu dở dang vì sequence không rollback theo thiết kế của PostgreSQL.

### So sánh nhanh

| | Khóa dòng | SERIALIZABLE + thử lại |
|---|---|---|
| Người sau | chờ | bị hủy (40001) rồi chạy lại |
| Code client | đơn giản | bắt buộc vòng thử lại toàn giao dịch |
| Độ trễ trung vị (kịch bản 1) | thấp hơn (10.2 ms) | cao hơn (14.9 ms) |
| Đuôi độ trễ p95 (kịch bản 1) | dài, dao động (281 ms) | ổn định (27.9 ms) |
| Rủi ro | giữ khóa lâu, deadlock nếu khóa sai thứ tự | "bão" thử lại khi tranh chấp lớn |
| Hợp với | một điểm tranh chấp rõ (một dòng phiên) | ràng buộc trải nhiều dòng khó xác định thứ tự khóa |

---

## 4. Sơ đồ EER: đúng chưa, đã sửa gì

Sơ đồ gốc (`EER_DE_TAI_19_KHONG_DAU.drawio`) **đúng ở các điểm chính** theo tài liệu SGU:

- Chuyên biệt hóa `TAISAN` → 3 lớp con: đường kép tới vòng tròn = **toàn phần** (trang 15), chữ **D = phân ly** (trang 17), ký hiệu tập con ∪ mở về lớp cha (trang 9), lớp con chỉ vẽ thuộc tính riêng (trang 22).
- Người bán / người tham gia là **vai trò theo quan hệ** (`Ban`, `DangKy`), không tách lớp người dùng – đúng yêu cầu đề "một người có thể đảm nhiệm cả hai vai trò ở các phiên khác nhau".
- `DangKy` n:m có thuộc tính riêng; `KETQUADAUGIA` là thực thể yếu (chữ nhật kép + hình thoi kép + đường kép, như "Cuon sach", "Ky XB" trang 20); cây danh mục là quan hệ đệ quy có ghi vai trò cha/con.
- Tỷ số lực lượng đặt theo cách đọc của ví dụ trang 20–21.

**Đã sửa** (tệp mới [eer/EER_DE_TAI_19_DA_SUA.drawio](eer/EER_DE_TAI_19_DA_SUA.drawio), xuất sẵn [PDF](eer/EER_DE_TAI_19_DA_SUA.pdf)/[PNG](eer/EER_DE_TAI_19_DA_SUA.png); bố cục giữ nguyên):

| Chỗ sửa | Trước | Sau | Lý do |
|---|---|---|---|
| `GiaHienTai` | elip nét liền | **elip nét đứt** | Là thuộc tính **suy diễn** (= SoTien lớn nhất của phiên). Quy ước ER chuẩn: thuộc tính suy diễn vẽ nét đứt. Chú thích cũ đã nói "được tính từ lịch sử" nhưng hình vẽ lại như thuộc tính gốc. |
| `DanDau` | hình thoi nét liền | **hình thoi + 2 cạnh nét đứt** | Lượt dẫn đầu suy ra được từ `ThuocPhien` + `SoTien` → nếu vẽ như quan hệ gốc thì mô hình khái niệm bị **dư thừa**. Giữ lại (vì bản cài đặt có lưu `leading_bid_id`) nhưng đánh dấu là suy diễn. |
| `ThuDienTu`, `MaYeuCau` | không gạch chân | **gạch chân** | Là khóa ứng viên (NOT NULL + UNIQUE). Tài liệu trang 11 (OTO: Sokhung, Somay) gạch chân **cả hai** khóa. |
| Nhãn chuyên biệt hóa | "TOAN PHAN" | "TOAN PHAN (phan loai theo LoaiTaiSan)" | Chuyên biệt hóa định nghĩa theo thuộc tính `LoaiTaiSan`. |
| Chú thích | – | thêm giải thích nét đứt, khóa ứng viên, thực thể yếu 1:1 không cần khóa riêng phần; thêm ràng buộc 10 "tối đa một phiên đang mở / tài sản" | Khớp với DDL sau sửa. |

**Nếu thầy hỏi "sao KETQUADAUGIA là thực thể yếu mà không có khóa riêng phần?"** – Vì quan hệ định danh `CoKetQua` là **1:1**: mỗi phiên có tối đa một kết quả, nên chỉ cần khóa của chủ (`MaPhien`) là định danh được. Khóa riêng phần chỉ cần khi một chủ có nhiều thực thể yếu (như nhiều "Cuon sach" của một "Lan xuat ban").

**Nếu thầy hỏi "sao không bỏ hẳn DanDau?"** – Ở mức khái niệm có thể bỏ (vì suy ra được). Nhóm giữ và vẽ nét đứt để nối thẳng sang thiết kế vật lý: bảng phiên lưu `leading_bid_id` như **bộ đệm có kiểm soát**, đúng yêu cầu bước 3 của đề "nếu lưu thêm giá cao nhất hiện tại, phải giải thích cơ chế giữ nhất quán".

### Ánh xạ EER → bảng (theo trang 22: lớp con lấy khóa lớp cha làm PK đồng thời FK)

| EER | Bảng (bản chạy app) | Bảng (bản bước 5) |
|---|---|---|
| NGUOIDUNG | `users` | `NguoiDung` |
| TAISAN + 3 lớp con | `assets` + `artworks`/`collectibles`/`electronics` (PK = FK `asset_id`) | `TaiSan` + 3 bảng con |
| DANHMUC + ChaCon | `categories(parent_id)` | `DanhMuc(MaDanhMucCha)` |
| PHIENDAUGIA | `auctions` (có cache `current_price`, `leading_bid_id`) | `PhienDauGia` (không cache, VIEW `ThongTinPhienDauGia` tính) |
| DangKy (n:m) | `registrations` PK(auction_id, user_id) | `DangKyThamGia` |
| LUOTTRAGIA | `bids`; FK (auction_id, bidder_id) → `registrations` | `LuotTraGia` |
| KETQUADAUGIA (yếu) | `results` PK = `auction_id` | `KetQuaDauGia` PK = `MaPhien` |
| NHATKYTHAYDOI | `audit_log` | `NhatKyThayDoi` |

**Vì sao có hai bộ DDL?** Bản bước 5 (`dau_gia`, tên tiếng Việt) là **lược đồ logic BCNF** ánh xạ trực tiếp từ EER – không lưu dữ liệu suy diễn. Bản `auction` là **lược đồ vật lý** chạy ứng dụng: thêm cache giá hiện tại (để kiểm tra giá nhanh trong giao dịch), trigger, hàm nghiệp vụ, phân quyền. Hai bản cùng khóa và ràng buộc nghiệp vụ.

---

## 5. Chuẩn hóa – ý cần nói

- Xuất phát từ quan hệ rộng R (mỗi dòng = một lượt + thông tin phiên, tài sản, người, danh mục). R **không đạt 3NF** vì có phụ thuộc bắc cầu (`bid_id → auction_id → asset_id → seller_id → seller_email`) → bất thường khi thêm/sửa/xóa.
- Ba khóa ứng viên của lượt trả giá: `bid_id`, `request_id`, `(auction_id, amount)` – nay **cả ba đều được CSDL thực thi** bằng PK/UNIQUE.
- Phân rã theo vế trái của từng FD → mọi định thức là khóa ⇒ **BCNF**; phân rã không mất thông tin (mỗi bước tách theo một khóa của phần bị tách) và bảo toàn phụ thuộc (mỗi FD nằm trọn trong một bảng).
- **Phân biệt 3 loại giá:** giá khởi điểm (`start_price`, cấu hình phiên), giá từng lượt (`bids.amount`), giá thắng (không lưu riêng: = `amount` của `results.winning_bid_id`). Giá hiện tại là **cache** của MAX lịch sử.
- Cache không phá BCNF trong bảng, nhưng là **dữ liệu lặp xuyên bảng** → phải giữ nhất quán bằng: ghi cùng giao dịch + trigger DEFERRED + `verify_invariants()` + app không có quyền UPDATE trực tiếp.

---

## 6. Câu hỏi thầy hay hỏi – trả lời ngắn

**Hai người cùng trả đúng một mức giá cùng lúc thì sao?**
Chỉ người giành quyền ghi dòng phiên trước được nhận. Người sau đọc giá mới (chờ khóa hoặc chạy lại) ⇒ mức tối thiểu đã tăng một bước ⇒ `BID_TOO_LOW`. Lớp cuối: `UNIQUE(auction_id, amount)` không cho hai lượt cùng giá trong một phiên. Kịch bản 1 benchmark: mỗi đợt 12 người cùng giá, đúng 1 người được nhận, 30/30 đợt.

**Trả giá sát giờ đóng thì tính thế nào?**
Hạn nhận là `[opens_at, closes_at)` theo **đồng hồ máy chủ CSDL** (không tin giờ client). Kiểm tra hai lần: lúc đọc và sau khi giành quyền ghi. Lượt đã giành quyền ghi trước giờ đóng thì hợp lệ dù COMMIT sau giờ đóng – đóng phiên sẽ chờ và chọn nó (test 32). Đồ án không có "gia hạn phút chót" (anti-sniping) – có thể là hướng phát triển.

**Gửi lại cùng yêu cầu (mạng chập chờn, bấm hai lần) thì sao?**
Mỗi yêu cầu mang một UUID (`request_id`). Hàm khóa theo UUID, tìm lượt đã có: cùng nội dung ⇒ trả `REPLAYED` với đúng lượt cũ; khác nội dung ⇒ `IDEMPOTENCY_CONFLICT`. `UNIQUE(request_id)` là hàng rào cuối. Kịch bản 2: 330 bản sao ⇒ 330 `REPLAYED`, 0 lượt trùng.

**Sao phải khóa theo UUID, khóa dòng phiên chưa đủ à?**
Không đủ: cùng một UUID có thể bị gửi tới **hai phiên khác nhau** – hai phiên là hai dòng khác nhau nên khóa dòng không chặn được (test 12).

**Yêu cầu bị từ chối có được lưu UUID không?**
Không – chỉ lượt được nhận mới được lưu. Gửi lại một yêu cầu từng bị từ chối sẽ được xét lại trên trạng thái mới (test 27). Không tạo lượt trùng vì lần đầu chưa có lượt nào.

**Vì sao chạy lại phải từ BEGIN chứ không chạy lại câu lệnh lỗi?**
Vì mọi điều kiện đã kiểm tra trước đó dựa trên snapshot cũ – đã sai. Phải đọc lại toàn bộ trên snapshot mới (test 17 tạo lỗi tuần tự hóa thật và kiểm tra cả giao dịch chạy lại).

**SERIALIZABLE có dùng khóa không?**
Có khóa ghi thông thường (UPDATE cùng dòng phải chờ), cộng SSI theo dõi phụ thuộc đọc–ghi. Khác phương án A ở chỗ code **không chủ động khóa khi đọc**.

**Vì sao trong hàm có `UPDATE … SET revision = revision + 1` trước khi INSERT lượt?**
Đó là "điểm giành quyền": lệnh ghi đầu tiên lên dòng phiên. Ở SERIALIZABLE, xung đột bị phát hiện ngay tại đây (trước khi ghi lịch sử). Nó cũng cho phép thí nghiệm "lỗi sau khi ghi lượt nhưng trước khi cập nhật giá" đúng thứ tự đề yêu cầu.

**Lỗi xảy ra giữa chừng có để lại gì không?**
Không. Một giao dịch: ghi lượt + cập nhật giá + nhật ký. Lỗi ⇒ ROLLBACK cả ba. Kịch bản 4: 720 yêu cầu lỗi ⇒ 0 lượt, 0 nhật ký, giá vẫn NULL. Chỉ có mã sequence bị nhảy – không phải dữ liệu.

**Làm sao bảo đảm không có hai người thắng?**
(1) `results.auction_id` là khóa chính ⇒ tối đa một dòng; (2) đóng phiên dùng cùng giao thức với trả giá ⇒ người thắng = lượt cao nhất tại lúc chốt; (3) trigger kiểm tra lúc COMMIT: phiên `CLOSED` phải có kết quả và người thắng = lượt cao nhất; (4) gọi đóng lần hai trả `CLOSE_REPLAYED`.

**Không có lượt hợp lệ thì kết quả là gì?**
Vẫn có một dòng kết quả với `winning_bid_id = NULL` (phiên không thành công). Tỷ lệ thành công = số phiên đóng có người thắng / số phiên đã đóng (Q5).

**Giá hiện tại lưu riêng có bị lệch lịch sử không?**
Không thể COMMIT trạng thái lệch: trigger `guard_auction_consistency` (DEFERRED) so `current_price` với MAX(`bids.amount`) lúc COMMIT. App không có quyền UPDATE bảng (test 26). `verify_invariants()` kiểm tra lại toàn CSDL.

**Chưa có lượt nào thì giá hiện tại bằng giá khởi điểm được không?**
Không: `current_price = NULL` nghĩa là chưa có ai trả. Gán bằng giá khởi điểm sẽ lẫn "giá cấu hình" với "giá đã có người trả". Mức tối thiểu lượt đầu = giá khởi điểm được tính trong hàm.

**Người bán có tự trả giá được không? Người chưa duyệt thì sao?**
Không – `SELLER_CANNOT_BID`, `NOT_REGISTERED`. Ngoài hàm, FK `(auction_id, bidder_id) → registrations` bảo đảm người trả phải có đăng ký ở đúng phiên đó.

**Một tài sản bán ở nhiều phiên được không?**
Được theo thời gian (ví dụ phiên trước không có người mua thì đấu giá lại), nhưng **không** được hai phiên đang mở cùng lúc – chỉ mục duy nhất có điều kiện `WHERE status='OPEN'`.

**Tại sao kiểm tra lớp con bằng trigger hoãn (DEFERRED)?**
Phải chèn tài sản cha trước rồi mới chèn lớp con. Kiểm tra ngay sau INSERT cha thì chưa có con ⇒ báo sai. Kiểm tra lúc COMMIT vừa cho phép thứ tự chèn, vừa bảo đảm đúng **một** lớp con khớp `kind` (toàn phần + phân ly).

**SQL đệ quy dùng ở đâu? Có lo vòng lặp vô hạn không?**
Q6 tổng hợp theo cây danh mục và báo cáo lọc theo cả nhánh con. Trigger `guard_category_tree` chặn chu trình khi thêm/sửa (đi ngược từ cha mới lên gốc, gặp chính mình ⇒ lỗi), có advisory lock để hai quản trị viên sửa đồng thời không cùng tạo chu trình.

**"Bộ lọc động" làm thế nào? Có bị SQL injection không?**
Hàm chỉ ghép những điều kiện có tham số rồi `EXECUTE … USING`; giá trị đi qua `$1, $2, $3`, không bao giờ ghép chuỗi người dùng. Test 18 thử `OPEN' OR 1=1 --` ⇒ không trả dòng nào.

**OQL chạy được trên PostgreSQL không?**
Không. OQL (chuẩn ODMG) dùng để đặc tả truy vấn hướng đối tượng; lệnh `oql` là bản mô phỏng Python tương đương trên đối tượng mẫu, kèm SQL đối chiếu.

**Vì sao benchmark mỗi worker giữ một kết nối?**
Để đo đúng thời gian giao dịch. Bản cũ mở kết nối mới mỗi lần thử nên ~90% độ trễ là bắt tay TCP/xác thực, không phản ánh khác biệt giữa hai giao thức.

**Kết luận phương án nào tốt hơn?**
Cả hai đều **đúng** (cùng kết quả nghiệp vụ, 8/8 bất biến). Trên máy này: khóa dòng có trung vị thấp hơn, không thử lại, xử lý nhiều yêu cầu hơn trong cùng thời gian; SERIALIZABLE có độ trễ ổn định hơn nhưng mỗi người thua phải chạy lại một lần. Với bài toán có một điểm tranh chấp rõ (dòng phiên), khóa dòng là lựa chọn tự nhiên; SERIALIZABLE hợp hơn khi ràng buộc trải nhiều dòng khó xác định thứ tự khóa. Không kết luận phổ quát từ một máy.

**Quản trị viên (superuser) có phá được ràng buộc không?**
Có thể (tắt trigger, sửa lược đồ). Đồ án tách owner/app: app chỉ được gọi 4 hàm, không ghi bảng trực tiếp; không tuyên bố chống được người có toàn quyền.

---

## 7. Số liệu cần nhớ (đo 08/11/2026)

Bảng gộp 3 vòng, 12 người đồng thời. "Đạt" = đạt kỳ vọng của kịch bản ở cả 3 vòng và 8/8 bất biến.

| Kịch bản | Giao thức | Yêu cầu | Nhận | Gửi lại | Từ chối | Lỗi | Lần thử lại | p50 ms | p95 ms | Đạt |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:-:|
| 1. Nhiều người cùng trả | row_lock | 360 | 30 | 0 | 330 | 0 | 0 | 10.2 | 281.0 | ✔ |
| 1. Nhiều người cùng trả | serializable | 360 | 30 | 0 | 330 | 0 | 330 | 14.9 | 27.9 | ✔ |
| 2. Gửi lại | row_lock | 360 | 30 | 330 | 0 | 0 | 0 | 4.7 | 9.9 | ✔ |
| 2. Gửi lại | serializable | 360 | 30 | 330 | 0 | 0 | 323 | 12.5 | 17.9 | ✔ |
| 3. Trả giá vs đóng phiên | row_lock | 4334 | 393 | 0 | 3941 | 0 | 0 | 4.5 | 8.3 | ✔ |
| 3. Trả giá vs đóng phiên | serializable | 2541 | 231 | 0 | 2310 | 0 | 2225 | 10.2 | 14.3 | ✔ |
| 4. Lỗi giữa giao dịch | row_lock | 360 | 0 | 0 | 0 | 360 | 0 | 4.7 | 7.4 | ✔ |
| 4. Lỗi giữa giao dịch | serializable | 360 | 0 | 0 | 0 | 360 | 0 | 3.7 | 7.6 | ✔ |

- Test: **56/56** Python/HTTP, **8/8** JavaScript, **24/24** kiểm tra DDL bước 5, **8/8** bất biến.
- Kịch bản 3 đếm yêu cầu trong cùng cửa sổ 1 giây nên số yêu cầu khác nhau; điều phải giống là: 1 kết quả, người thắng = lượt cao nhất, 0 lượt sau hạn.

---

## 8. Lệnh dùng khi bảo vệ

```powershell
# Mở giao diện (bấm đúp cũng được): MO_HE_THONG.cmd
.\.venv\Scripts\python.exe -m auction_lab scenario                         # kịch bản nghiệp vụ, khóa dòng
.\.venv\Scripts\python.exe -m auction_lab scenario --strategy serializable
.\.venv\Scripts\python.exe -m auction_lab verify                           # 8 bất biến
.\.venv\Scripts\python.exe -m auction_lab test                             # 56 test trên CSDL _test
.\.venv\Scripts\python.exe -m auction_lab benchmark                        # 4 kịch bản × 2 giao thức × 3 vòng
```

Quan sát khóa trực tiếp: [HUONG_DAN_PGADMIN.md](HUONG_DAN_PGADMIN.md) mục 5 (hai Query Tool, tab B chờ tab A).

**Cập nhật CSDL `auction19_demo` đang có trên máy** (không mất dữ liệu): trong pgAdmin, mở Query Tool bằng tài khoản `auction19_owner`, chạy lần lượt `sql/07_nang_cap.sql` → `sql/01_schema.sql` → `sql/02_functions.sql` → `sql/06_permissions.sql`. Nếu `07` báo WARNING "nhiều phiên mở cho cùng tài sản", đóng các phiên thừa (đã hết hạn) bằng `SELECT auction.close_auction(<id>);` rồi chạy lại `07`.

---

## 9. Đã đạt 10/10 chưa?

**Đủ mọi hạng mục đề yêu cầu** (7 bước + 5 minh chứng) và có bằng chứng chạy được cho từng mục; sau đợt sửa này không còn chỗ báo cáo nói một đằng, code làm một nẻo. Điểm cuối cùng còn phụ thuộc phần trình bày và trả lời của nhóm. Những chỗ thầy có thể "bắt bẻ" – nên chủ động nêu là **giới hạn có chủ đích**:

- Phiên không tự đóng khi hết giờ: cần gọi `close_auction` (thực tế dùng bộ lập lịch như `pg_cron`); trong lúc chờ, giao diện tính trạng thái hết hạn (`ENDED`) từ giờ máy chủ và hàm trả giá vẫn từ chối `AUCTION_ENDED`.
- Không có gia hạn phút chót, đặt giá tự động (proxy bid), thanh toán, xác thực người dùng – ngoài phạm vi "mô phỏng nghiệp vụ".
- OQL chỉ là đặc tả + mô phỏng Python, không có hệ quản trị đối tượng thật.
- Số đo trên một máy Windows; đuôi độ trễ của khóa dòng dao động mạnh giữa các vòng.
- Thu hồi đăng ký (`REVOKED`) chưa có hàm riêng phối hợp khóa với trả giá; hiện chỉ đổi trạng thái bằng tài khoản owner.
