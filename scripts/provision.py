"""Provision isolated project databases without storing admin credentials.

For a new computer only. Existing project roles are never altered. Run once with
an administrator, then use the generated .env and `python -m auction_lab setup`.
"""
from pathlib import Path
from getpass import getpass
import secrets
import sys
from urllib.parse import quote
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    if (ROOT / '.env').exists():
        raise SystemExit('.env đã tồn tại; không ghi đè tài khoản. Dùng cấu hình hiện có.')
    host = input('PostgreSQL host [localhost]: ').strip() or 'localhost'
    port = int(input('Port [5432]: ').strip() or '5432')
    if not 1 <= port <= 65535:
        raise SystemExit('Port phải nằm trong khoảng 1..65535.')
    user = input('Tài khoản quản trị [postgres]: ').strip() or 'postgres'
    password = getpass('Mật khẩu PostgreSQL (không lưu mật khẩu quản trị): ')
    owner_password, app_password = secrets.token_hex(32), secrets.token_hex(32)
    uri_host = f'[{host}]' if ':' in host and not host.startswith('[') else host
    def uri(role, secret, database):
        return f'postgresql://{quote(role)}:{quote(secret)}@{uri_host}:{port}/{database}'
    config = '\n'.join([
        'DATABASE_URL=' + uri('auction19_owner', owner_password, 'auction19_demo'),
        'APP_DATABASE_URL=' + uri('auction19_app', app_password, 'auction19_demo'),
        'TEST_DATABASE_URL=' + uri('auction19_owner', owner_password, 'auction19_test'),
        'BENCH_DATABASE_URL=' + uri('auction19_owner', owner_password, 'auction19_bench'), '',
    ])
    with psycopg.connect(host=host, port=port, user=user, password=password,
                         dbname='postgres', autocommit=True) as conn:
        admin = conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user').fetchone()
        if not admin or not (admin[0] or (admin[1] and admin[2])):
            raise SystemExit('Tài khoản cài đặt cần CREATEDB và CREATEROLE; chưa thay đổi dữ liệu.')
        for role in ('auction19_owner', 'auction19_app'):
            if conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s', (role,)).fetchone():
                raise SystemExit(f'Tài khoản {role} đã tồn tại; dừng để không đổi quyền/mật khẩu có sẵn.')
        for name in ('auction19_demo', 'auction19_test', 'auction19_bench'):
            if conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (name,)).fetchone():
                raise SystemExit(f'CSDL {name} đã tồn tại; dừng để bảo toàn dữ liệu.')
        # Keep generated credentials before the first autocommit operation so a
        # partial provisioning failure never leaves an unrecoverable new role.
        with (ROOT / '.env').open('x', encoding='utf-8') as file:
            file.write(config)
        try:
            for role, secret in (('auction19_owner', owner_password), ('auction19_app', app_password)):
                conn.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(
                    sql.Identifier(role), sql.Literal(secret)))
            for name in ('auction19_demo', 'auction19_test', 'auction19_bench'):
                conn.execute(sql.SQL('CREATE DATABASE {} OWNER auction19_owner').format(sql.Identifier(name)))
        except psycopg.Error as exc:
            raise SystemExit('Cài đặt chưa hoàn tất. Thông tin tài khoản mới đã được giữ trong .env; '
                             'không xóa file này. Kiểm tra các role/CSDL auction19_* bằng pgAdmin. '
                             f'Mã lỗi PostgreSQL: {exc.sqlstate}') from None
    print('Đã tạo 3 CSDL riêng và .env. Chạy python -m auction_lab setup.')


if __name__ == '__main__':
    main()
