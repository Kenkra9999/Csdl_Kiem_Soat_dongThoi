-- KIEM THU DDL BUOC 5: cac du lieu thu duoc ROLLBACK o cuoi tep.
-- Chay ca tep trong Query Tool tren database da cai 01_tao_bang.sql.
-- Chi xac minh rang buoc cau truc, khong thay cho kiem thu transaction nghiep vu.

BEGIN;

CREATE TEMP TABLE ket_qua_ddl (
    ten_kiem_tra text PRIMARY KEY,
    ket_qua text NOT NULL CHECK (ket_qua = 'DAT')
) ON COMMIT DROP;

CREATE FUNCTION pg_temp.phai_tu_choi(
    ten text, ma_loi_mong_doi text, cau_lenh text, kiem_tra_cuoi_giao_dich boolean DEFAULT false
) RETURNS void LANGUAGE plpgsql AS $$
DECLARE ma_loi text;
BEGIN
    BEGIN
        EXECUTE cau_lenh;
        IF kiem_tra_cuoi_giao_dich THEN
            SET CONSTRAINTS ALL IMMEDIATE;
        END IF;
    EXCEPTION WHEN OTHERS THEN
        GET STACKED DIAGNOSTICS ma_loi = RETURNED_SQLSTATE;
        IF ma_loi <> ma_loi_mong_doi THEN
            RAISE EXCEPTION '%: mong SQLSTATE %, nhan %', ten, ma_loi_mong_doi, ma_loi;
        END IF;
        INSERT INTO pg_temp.ket_qua_ddl VALUES (ten, 'DAT');
        RETURN;
    END;
    RAISE EXCEPTION '%: du lieu sai da duoc chap nhan', ten;
END;
$$;

DO $$
DECLARE
    ma bigint := -1000000000 - txid_current();
    thu text := 'buoc5-' || txid_current() || '@example.test';
    yeu_cau_1 uuid := gen_random_uuid();
    yeu_cau_2 uuid := gen_random_uuid();
    yeu_cau_3 uuid := gen_random_uuid();
    gia numeric;
    dan_dau bigint;
BEGIN
    INSERT INTO dau_gia."NguoiDung" ("MaNguoiDung", "HoTen", "DiaChiThuDienTu") VALUES
        (ma, 'Nguoi ban thu', thu),
        (ma-1, 'Nguoi tra A', 'a-' || thu),
        (ma-2, 'Nguoi tra B', 'b-' || thu);
    INSERT INTO dau_gia."DanhMuc" ("MaDanhMuc", "TenDanhMuc") VALUES (ma, 'Danh muc ' || ma);
    INSERT INTO dau_gia."TaiSan"
        ("MaTaiSan", "MaNguoiBan", "MaDanhMuc", "LoaiTaiSan", "TenTaiSan") VALUES
        (ma, ma, ma, 'NgheThuat', 'Tranh thu'),
        (ma-1, ma, ma, 'SuuTam', 'Do suu tam thu'),
        (ma-2, ma, ma, 'DienTu', 'Thiet bi thu');
    INSERT INTO dau_gia."TacPhamNgheThuat" ("MaTaiSan", "TacGia", "ChatLieu")
        VALUES (ma, 'Tac gia thu', 'Son dau');
    INSERT INTO dau_gia."DoSuuTam" ("MaTaiSan", "NguonGoc", "DoHiem")
        VALUES (ma-1, 'Nguon goc thu', 'Hiem');
    INSERT INTO dau_gia."ThietBiDienTu" ("MaTaiSan", "ThuongHieu", "MauThietBi", "TinhTrang")
        VALUES (ma-2, 'Nhan hieu thu', 'Mau thu', 'Moi');
    SET CONSTRAINTS ALL IMMEDIATE;
    SET CONSTRAINTS ALL DEFERRED;
    INSERT INTO pg_temp.ket_qua_ddl VALUES ('01. Tai san co dung lop con cung dinh danh', 'DAT');

    INSERT INTO dau_gia."PhienDauGia"
        ("MaPhien", "MaTaiSan", "GiaKhoiDiem", "BuocGia", "ThoiDiemMo", "ThoiDiemDong") VALUES
        (ma, ma, 100, 10, clock_timestamp()-interval '1 hour', clock_timestamp()+interval '1 hour'),
        (ma-1, ma, 100, 10, clock_timestamp()-interval '1 hour', clock_timestamp()+interval '1 hour');
    INSERT INTO pg_temp.ket_qua_ddl VALUES ('02. Mot tai san duoc co nhieu phien', 'DAT');
    SELECT "GiaHienTai", "MaLuotDanDau" INTO gia, dan_dau
    FROM dau_gia."ThongTinPhienDauGia" WHERE "MaPhien" = ma;
    IF gia IS NOT NULL OR dan_dau IS NOT NULL THEN
        RAISE EXCEPTION 'Phien chua co luot phai co gia/nguoi dan dau NULL';
    END IF;
    INSERT INTO pg_temp.ket_qua_ddl VALUES ('03. VIEW khong gia lam gia khoi diem thanh gia hien tai', 'DAT');
    INSERT INTO dau_gia."DangKyThamGia" ("MaPhien", "MaNguoiDung") VALUES
        (ma, ma-1), (ma, ma-2), (ma-1, ma-1);
    INSERT INTO dau_gia."LuotTraGia"
        ("MaLuotTraGia", "MaPhien", "MaNguoiTraGia", "SoTien", "MaYeuCau") VALUES
        (ma, ma, ma-1, 100, yeu_cau_1),
        (ma-1, ma, ma-2, 110, yeu_cau_2),
        (ma-2, ma-1, ma-1, 100, yeu_cau_3);
    SELECT "GiaHienTai", "MaLuotDanDau" INTO gia, dan_dau
    FROM dau_gia."ThongTinPhienDauGia" WHERE "MaPhien" = ma;
    IF gia <> 110 OR dan_dau <> ma-1 THEN RAISE EXCEPTION 'VIEW sai luot dan dau'; END IF;
    INSERT INTO pg_temp.ket_qua_ddl VALUES ('04. VIEW lay dung MAX va ma luot dan dau', 'DAT');
    INSERT INTO pg_temp.ket_qua_ddl VALUES ('05. Hai phien khac nhau duoc co cung muc gia', 'DAT');

    PERFORM pg_temp.phai_tu_choi('06. Email khong duoc trung', '23505', format(
        'INSERT INTO dau_gia."NguoiDung" ("MaNguoiDung","HoTen","DiaChiThuDienTu") VALUES (%s,''Nguoi thu'',%L)', ma-10, thu));
    PERFORM pg_temp.phai_tu_choi('07. Ho ten khong duoc rong', '23514', format(
        'INSERT INTO dau_gia."NguoiDung" ("MaNguoiDung","HoTen","DiaChiThuDienTu") VALUES (%s,'' '',%L)', ma-10, 'rong-'||thu));
    PERFORM pg_temp.phai_tu_choi('08. Nguoi ban phai ton tai', '23503', format(
        'INSERT INTO dau_gia."TaiSan" ("MaTaiSan","MaNguoiBan","MaDanhMuc","LoaiTaiSan","TenTaiSan") VALUES (%s,%s,%s,''NgheThuat'',''Thu'')',ma-10,ma-100,ma));
    PERFORM pg_temp.phai_tu_choi('09. Tai san bat buoc co lop con', '23514', format(
        'INSERT INTO dau_gia."TaiSan" ("MaTaiSan","MaNguoiBan","MaDanhMuc","LoaiTaiSan","TenTaiSan") VALUES (%s,%s,%s,''NgheThuat'',''Thu'')',ma-10,ma,ma),true);
    PERFORM pg_temp.phai_tu_choi('10. Khong duoc co hai lop con', '23514', format(
        'INSERT INTO dau_gia."DoSuuTam" ("MaTaiSan","NguonGoc","DoHiem") VALUES (%s,''Thu'',''Thu'')',ma),true);
    PERFORM pg_temp.phai_tu_choi('11. Lop con phai co tai san cha', '23503', format(
        'INSERT INTO dau_gia."TacPhamNgheThuat" ("MaTaiSan","TacGia","ChatLieu") VALUES (%s,''Thu'',''Thu'')',ma-100));
    PERFORM pg_temp.phai_tu_choi('12. Khong duoc dang ky trung cap phien-nguoi', '23505', format(
        'INSERT INTO dau_gia."DangKyThamGia" ("MaPhien","MaNguoiDung") VALUES (%s,%s)',ma,ma-1));
    PERFORM pg_temp.phai_tu_choi('13. Luot tra gia can dang ky dung phien', '23503', format(
        'INSERT INTO dau_gia."LuotTraGia" ("MaLuotTraGia","MaPhien","MaNguoiTraGia","SoTien","MaYeuCau") VALUES (%s,%s,%s,120,gen_random_uuid())',ma-10,ma-1,ma-2));
    PERFORM pg_temp.phai_tu_choi('14. Ma yeu cau duy nhat toan he thong', '23505', format(
        'INSERT INTO dau_gia."LuotTraGia" ("MaLuotTraGia","MaPhien","MaNguoiTraGia","SoTien","MaYeuCau") VALUES (%s,%s,%s,120,%L)',ma-10,ma-1,ma-1,yeu_cau_1));
    PERFORM pg_temp.phai_tu_choi('15. Muc gia khong duoc trung trong mot phien', '23505', format(
        'INSERT INTO dau_gia."LuotTraGia" ("MaLuotTraGia","MaPhien","MaNguoiTraGia","SoTien","MaYeuCau") VALUES (%s,%s,%s,100,gen_random_uuid())',ma-10,ma,ma-2));
    PERFORM pg_temp.phai_tu_choi('16. Khong chap nhan so tien NaN', '23514', format(
        'INSERT INTO dau_gia."LuotTraGia" ("MaLuotTraGia","MaPhien","MaNguoiTraGia","SoTien","MaYeuCau") VALUES (%s,%s,%s,''NaN'',gen_random_uuid())',ma-10,ma,ma-2));
    PERFORM pg_temp.phai_tu_choi('17. Buoc gia phai duong', '23514', format(
        'UPDATE dau_gia."PhienDauGia" SET "BuocGia"=0 WHERE "MaPhien"=%s',ma));
    PERFORM pg_temp.phai_tu_choi('18. Gia khoi diem phai duong', '23514', format(
        'UPDATE dau_gia."PhienDauGia" SET "GiaKhoiDiem"=-1 WHERE "MaPhien"=%s',ma));
    PERFORM pg_temp.phai_tu_choi('19. Dong phien phai sau mo phien', '23514', format(
        'UPDATE dau_gia."PhienDauGia" SET "ThoiDiemDong"="ThoiDiemMo" WHERE "MaPhien"=%s',ma));
    PERFORM pg_temp.phai_tu_choi('20. Luot thang phai thuoc dung phien', '23503', format(
        'INSERT INTO dau_gia."KetQuaDauGia" ("MaPhien","MaLuotThang") VALUES (%s,%s)',ma-1,ma));
    INSERT INTO dau_gia."KetQuaDauGia" ("MaPhien","MaLuotThang") VALUES (ma,ma-1);
    PERFORM pg_temp.phai_tu_choi('21. Moi phien toi da mot ket qua', '23505', format(
        'INSERT INTO dau_gia."KetQuaDauGia" ("MaPhien","MaLuotThang") VALUES (%s,%s)',ma,ma-1));
    PERFORM pg_temp.phai_tu_choi('22. Ten danh muc goc khong duoc trung', '23505', format(
        'INSERT INTO dau_gia."DanhMuc" ("MaDanhMuc","TenDanhMuc") VALUES (%s,%L)',ma-10,'Danh muc '||ma));

    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema='dau_gia' AND table_name='PhienDauGia'
                 AND column_name IN ('GiaHienTai','MaLuotDanDau')) THEN
        RAISE EXCEPTION 'Bang phien co du lieu suy dien thay vi VIEW';
    END IF;
    INSERT INTO pg_temp.ket_qua_ddl VALUES ('23. Bang phien khong luu lap du lieu suy dien', 'DAT');
END;
$$;

SET CONSTRAINTS ALL IMMEDIATE;
SELECT ten_kiem_tra AS "KiemTra", ket_qua AS "KetQua"
FROM pg_temp.ket_qua_ddl ORDER BY ten_kiem_tra;

-- Khong luu nguoi/tai san/phien/luot tra gia thu va khong tang identity sequence.
ROLLBACK;
