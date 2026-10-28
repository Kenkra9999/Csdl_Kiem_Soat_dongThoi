-- Chay sau 01_tao_bang.sql. Tep chi doc, khong thay doi du lieu.
SELECT current_database() AS "CoSoDuLieu", current_user AS "TaiKhoan";

-- Ket qua: 11 bang co so, rieng VIEW khong tinh la bang du lieu.
SELECT table_name AS "TenBang"
FROM information_schema.tables
WHERE table_schema = 'dau_gia' AND table_type = 'BASE TABLE'
ORDER BY table_name;

-- Kiem tra KC, KN, DN va CHECK duoc PostgreSQL thuc su tao.
SELECT c.conrelid::regclass AS "Bang", c.conname AS "RangBuoc",
       CASE c.contype WHEN 'p' THEN 'KhoaChinh' WHEN 'f' THEN 'KhoaNgoai'
           WHEN 'u' THEN 'DuyNhat' WHEN 'c' THEN 'DieuKien' END AS "Loai",
       pg_get_constraintdef(c.oid) AS "DinhNghia"
FROM pg_constraint AS c
JOIN pg_namespace AS n ON n.oid = c.connamespace
WHERE n.nspname = 'dau_gia' AND c.contype IN ('p', 'f', 'u', 'c')
ORDER BY c.conrelid::regclass::text, c.contype, c.conname;

-- Xem gia hien tai/nguoi dan dau qua VIEW sau khi co du lieu mau.
SELECT "MaPhien", "GiaKhoiDiem", "BuocGia", "GiaHienTai", "MaLuotDanDau"
FROM dau_gia."ThongTinPhienDauGia" ORDER BY "MaPhien";

-- VIEW khong luu du lieu; khong co cot gia suy dien trong bang phien co so.
SELECT column_name AS "CotCuaBangPhien"
FROM information_schema.columns
WHERE table_schema = 'dau_gia' AND table_name = 'PhienDauGia'
ORDER BY ordinal_position;
