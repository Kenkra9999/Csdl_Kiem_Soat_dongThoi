-- BUOC 5 - DE TAI 19: TAO CO SO DU LIEU RIENG CHO BAN DDL BCNF.
-- Mo Query Tool tai database postgres, bat Auto-commit, chay tep nay rieng.
-- Tai khoan can quyen CREATEDB. Khong dat CREATE DATABASE trong BEGIN/COMMIT.
-- Khong dung lenh \connect cua psql trong Query Tool cua pgAdmin.
-- Neu database da ton tai, PostgreSQL bao loi; tep khong xoa/ghi de database.

CREATE DATABASE dau_gia_19_bcnf
    WITH ENCODING = 'UTF8'
         TEMPLATE = template0;

-- Sau khi chay: Refresh Databases, mo Query Tool MOI tren dau_gia_19_bcnf,
-- roi chay 01_tao_bang.sql. Database auction19_demo dang chay web giu nguyen.
