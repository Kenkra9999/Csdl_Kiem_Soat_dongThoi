# Mô hình EER và ánh xạ quan hệ

## 1. Chuyên biệt hóa tài sản

`TaiSan` là lớp cha. Ba lớp con `TacPhamNgheThuat`, `DoSuuTam`, `ThietBiDienTu` có cùng định danh với tài sản cha.

- **Total**: mỗi tài sản thuộc một trong ba lớp con.
- **Disjoint**: một tài sản chỉ thuộc đúng một lớp con.
- `assets.kind` là thuộc tính phân loại: `ARTWORK`, `COLLECTIBLE`, `ELECTRONIC`.
- Ánh xạ bằng bảng cha `assets` và ba bảng con `artworks`, `collectibles`, `electronics`, trong đó `asset_id` đồng thời là PK và FK.
- Kiểm tra total/disjoint cần kiểm tra xuyên bảng ở cuối giao dịch. Chỉ có FK từ bảng con đến bảng cha chưa đủ để bảo đảm một tài sản có lớp con.

```mermaid
classDiagram
    class TaiSan {
        +id: bigint
        +seller_id: bigint
        +category_id: bigint
        +kind: AssetKind
        +title: text
    }
    class TacPhamNgheThuat
    class DoSuuTam
    class ThietBiDienTu
    TaiSan <|-- TacPhamNgheThuat
    TaiSan <|-- DoSuuTam
    TaiSan <|-- ThietBiDienTu
    note for TaiSan "Chuyên biệt hóa total, disjoint; giữ nguyên định danh cha"
```

## 2. Quan hệ và lực lượng

```mermaid
erDiagram
    USERS ||--o{ ASSETS : "so huu / ban"
    CATEGORIES o|--o{ CATEGORIES : "cha - con"
    CATEGORIES ||--o{ ASSETS : "phan loai"
    ASSETS ||--o| ARTWORKS : "ARTWORK"
    ASSETS ||--o| COLLECTIBLES : "COLLECTIBLE"
    ASSETS ||--o| ELECTRONICS : "ELECTRONIC"
    ASSETS ||--o{ AUCTIONS : "duoc dua ra dau gia"
    USERS ||--o{ REGISTRATIONS : "dang ky"
    AUCTIONS ||--o{ REGISTRATIONS : "co nguoi tham gia"
    AUCTIONS ||--o{ BIDS : "nhan luot tra gia"
    USERS ||--o{ BIDS : "tra gia"
    AUCTIONS ||--o| RESULTS : "chot ket qua"
    BIDS o|--o| RESULTS : "luot thang"
    AUCTIONS ||--o{ AUDIT_LOG : "ghi nhat ky"
    USERS {
        bigint id PK
        text email UK
        text full_name
    }
    CATEGORIES {
        bigint id PK
        bigint parent_id FK
        text name
    }
    ASSETS {
        bigint id PK
        bigint seller_id FK
        bigint category_id FK
        text kind
        text title
    }
    ARTWORKS {
        bigint asset_id PK,FK
    }
    COLLECTIBLES {
        bigint asset_id PK,FK
    }
    ELECTRONICS {
        bigint asset_id PK,FK
    }
    AUCTIONS {
        bigint id PK
        bigint asset_id FK
        numeric start_price
        numeric bid_step
        timestamptz opens_at
        timestamptz closes_at
        text status
        numeric current_price "cache, NULL khi chua co bid"
        bigint leading_bid_id FK
    }
    REGISTRATIONS {
        bigint auction_id PK,FK
        bigint user_id PK,FK
        text status
    }
    BIDS {
        bigint id PK
        bigint auction_id FK
        bigint bidder_id FK
        uuid request_id UK
        numeric amount
        timestamptz accepted_at
    }
    RESULTS {
        bigint auction_id PK,FK
        bigint winning_bid_id FK "NULL khi khong co bid"
        timestamptz closed_at
    }
    AUDIT_LOG {
        bigint id PK
        bigint auction_id FK
    }
```

Sơ đồ ER thể hiện mỗi bảng con là tùy chọn khi xét riêng; ràng buộc total/disjoint là ràng buộc bổ sung giữa **toàn bộ ba bảng con**. Đây là lý do cần mô tả chuyên biệt hóa riêng bên cạnh sơ đồ quan hệ.

## 3. Vai trò người dùng

Không tách `Seller` và `Bidder` thành hai loại người dùng loại trừ nhau. Vai trò người bán được suy ra qua `assets.seller_id`; vai trò người tham gia qua `registrations`. Một người có thể bán ở phiên A và trả giá ở phiên B. Quy tắc cấm người bán tự trả giá chỉ áp dụng cho tài sản của chính người đó.

`registrations` biểu diễn quan hệ nhiều-nhiều; khóa ghép `(auction_id, user_id)` ngăn đăng ký trùng. Một lượt trả giá hợp lệ cần người tham gia đã được duyệt tại phiên tương ứng.

## 4. Cây danh mục và kết quả

Danh mục có tối đa một cha; gốc có `parent_id IS NULL`. Cấm tự làm cha và cấm chu trình. Truy vấn đệ quy duyệt hậu duệ để tổng hợp số phiên, số lượt trả và doanh thu theo danh mục gốc.

Các sửa đổi cây là thao tác quản trị. Trigger đồng bộ bằng advisory lock và đọc trạng thái mới ở READ COMMITTED; SERIALIZABLE phải retry khi xung đột. Trigger từ chối sửa cây ở REPEATABLE READ vì snapshot có thể cũ dù đã chờ advisory lock. Quy tắc này ngăn hai quản trị viên đồng thời tạo chu trình bằng hai cạnh khác nhau.

`results.auction_id` là PK, bảo đảm tối đa một kết quả cho một phiên. Kết quả không có người thắng vẫn có một dòng với `winning_bid_id IS NULL`. Cần kiểm tra thêm rằng lượt thắng thuộc đúng phiên, là lượt cao nhất, và phiên đã đóng; PK một mình không chứng minh đầy đủ điều này.

## 5. Dữ liệu suy diễn

`auctions.current_price` và `leading_bid_id` là cache của lịch sử `bids`. Không lưu bản sao họ tên/email người thắng trong kết quả. Lấy người thắng qua `results -> bids -> users`, giá thắng qua `bids.amount`.

Ba bất biến liên bảng:

1. Chưa có bid: `current_price IS NULL AND leading_bid_id IS NULL`.
2. Có bid: cache bằng `MAX(bids.amount)`, `leading_bid_id` trỏ tới lượt đó của cùng phiên.
3. Phiên đóng: đúng một dòng kết quả; lượt thắng bằng leader tại thời điểm chốt hoặc NULL khi không có bid.
