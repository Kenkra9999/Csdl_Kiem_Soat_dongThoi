"""Loopback-only HTTP interface for the existing PostgreSQL auction project."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import re
import secrets
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

import psycopg

from .web_service import ApiError, AuctionWebService, encoded_json, positive_integer

MAX_BODY = 32 * 1024


class AuctionHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, service: AuctionWebService):
        self.service = service
        super().__init__(address, AuctionRequestHandler)


class AuctionRequestHandler(BaseHTTPRequestHandler):
    server_version = 'Auction19'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    @property
    def service(self):
        return self.server.service

    def log_message(self, format, *args):
        # Avoid logging request bodies, token headers or database exceptions.
        return

    def _headers(self, status, content_type, length):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(length))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.end_headers()

    def _json(self, value, status=200, head=False):
        body = encoded_json(value)
        self._headers(status, 'application/json; charset=utf-8', len(body))
        if not head:
            self.wfile.write(body)

    def _error(self, exc: ApiError, *, head=False):
        self._json({'ok': False, 'error': {'code': exc.code, 'message': exc.message}}, exc.status, head)

    def _host(self):
        port = self.server.server_address[1]
        hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
        if port == 80:
            hosts |= {'127.0.0.1', 'localhost'}
        if self.headers.get('Host', '').lower() not in hosts:
            raise ApiError('INVALID_HOST', 'Ứng dụng chỉ nhận kết nối từ địa chỉ cục bộ.', 403)
        return hosts

    def _body(self):
        hosts = self._host()
        origin = self.headers.get('Origin')
        if origin is not None and origin not in {'http://' + host for host in hosts}:
            raise ApiError('INVALID_ORIGIN', 'Nguồn gửi yêu cầu không hợp lệ.', 403)
        token = self.headers.get('X-Auction-Token', '')
        if not secrets.compare_digest(token, self.service.csrf_token):
            raise ApiError('CSRF_REJECTED', 'Phiên kết nối đã thay đổi. Vui lòng tải lại trang.', 403)
        if self.headers.get('Transfer-Encoding'):
            raise ApiError('INVALID_BODY', 'Định dạng gửi dữ liệu không được hỗ trợ.')
        if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise ApiError('INVALID_CONTENT_TYPE', 'Yêu cầu phải gửi dữ liệu JSON.', 415)
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            raise ApiError('INVALID_BODY', 'Thiếu độ dài dữ liệu JSON.', 411) from None
        if length < 0 or length > MAX_BODY:
            raise ApiError('BODY_TOO_LARGE', 'Dữ liệu yêu cầu vượt giới hạn 32 KB.', 413)
        raw = self.rfile.read(length)
        self._body_consumed = True
        try:
            payload = json.loads(raw.decode('utf-8'), parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (UnicodeDecodeError, ValueError):
            raise ApiError('INVALID_JSON', 'Dữ liệu JSON không hợp lệ.') from None
        if not isinstance(payload, dict):
            raise ApiError('INVALID_JSON', 'Dữ liệu JSON phải là một đối tượng.')
        return payload

    def _static(self, path, *, head=False):
        path = unquote(path)
        if '\\' in path or '\x00' in path or '..' in Path(path).parts:
            raise ApiError('FORBIDDEN_PATH', 'Đường dẫn không được phép.', 403)
        relative = 'index.html' if path == '/' else path.lstrip('/')
        target = (self.service.web_root / relative).resolve()
        if not target.is_relative_to(self.service.web_root) or target.suffix.lower() not in {'.html', '.css', '.js', '.svg', '.png', '.ico', '.woff', '.woff2'}:
            raise ApiError('NOT_FOUND', 'Không tìm thấy tài nguyên.', 404)
        if not target.is_file():
            raise ApiError('NOT_FOUND', 'Không tìm thấy tài nguyên.', 404)
        content = target.read_bytes()
        content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
        if target.suffix in {'.html', '.css', '.js', '.svg'}:
            content_type += '; charset=utf-8'
        self._headers(200, content_type, len(content))
        if not head:
            self.wfile.write(content)

    def _discard_unread_body(self):
        """Đọc bỏ phần thân chưa đọc (có giới hạn) trước khi đóng kết nối.

        Nếu từ chối sớm (sai token, sai Origin, ...) rồi đóng socket khi thân yêu
        cầu còn trong bộ đệm, Windows gửi RST và client mất luôn phản hồi lỗi
        (WinError 10053/10054). Chỉ đọc tối đa 4 x MAX_BODY để không bị lợi dụng.
        """
        if self._body_consumed:
            return
        try:
            remaining = min(int(self.headers.get('Content-Length', '0')), 4 * MAX_BODY)
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 8192))
                if not chunk:
                    break
                remaining -= len(chunk)
        except (ValueError, OSError):
            pass

    def _dispatch(self, *, post=False, head=False):
        self._body_consumed = False      # một kết nối keep-alive có thể chứa nhiều yêu cầu
        try:
            self._host()
            parsed = urlsplit(self.path)
            path = parsed.path
            if not path.startswith('/api/'):
                if post:
                    raise ApiError('NOT_FOUND', 'Không tìm thấy thao tác.', 404)
                return self._static(path, head=head)
            if post:
                payload = self._body()
                if path == '/api/system/stop':
                    self._json({'ok': True, 'data': {'status': 'STOPPING'}})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                elif path == '/api/experiments/race':
                    data = self.service.race(payload)
                else:
                    match = re.fullmatch(r'/api/auctions/(\d+)/(bids|close)', path)
                    if not match:
                        raise ApiError('NOT_FOUND', 'Không tìm thấy thao tác.', 404)
                    auction_id = positive_integer(int(match[1]), 'Phiên đấu giá')
                    data = self.service.bid(auction_id, payload) if match[2] == 'bids' else self.service.close(auction_id, payload)
            elif path == '/api/health':
                # Shutdown must stay available if PostgreSQL has stopped. The
                # local token is already readable by same-origin bootstrap;
                # Host checks and lack of CORS still prevent foreign-page use.
                data = {'application': 'auction19', 'version': '1.0.0',
                        'csrf_token': self.service.csrf_token}
            elif path == '/api/bootstrap':
                data = self.service.bootstrap()
            elif path == '/api/auctions':
                query = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
                data = self.service.auctions(query)
            elif path == '/api/checks':
                data = self.service.checks()
            elif path == '/api/experiments/latest':
                data = self.service.latest_experiments()
            elif match := re.fullmatch(r'/api/auctions/(\d+)', path):
                data = self.service.detail(positive_integer(int(match[1]), 'Phiên đấu giá'))
            else:
                raise ApiError('NOT_FOUND', 'Không tìm thấy API.', 404)
            self._json({'ok': True, 'data': data}, head=head)
        except ApiError as exc:
            if post:
                self._discard_unread_body()
            self.close_connection = post  # Không tái sử dụng kết nối sau yêu cầu ghi bị từ chối.
            self._error(exc, head=head)
        except psycopg.OperationalError:
            self._error(ApiError('DATABASE_UNAVAILABLE', 'Chưa kết nối được PostgreSQL. Kiểm tra dịch vụ và cấu hình .env trên máy.', 503), head=head)
        except psycopg.Error:
            self._error(ApiError('DATABASE_ERROR', 'CSDL không hoàn tất được thao tác. Vui lòng tải lại và kiểm tra kết nối.', 500), head=head)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._error(ApiError('SERVER_ERROR', 'Không hoàn tất được thao tác. Vui lòng thử lại.', 500), head=head)

    def do_GET(self):
        self._dispatch()

    def do_HEAD(self):
        self._dispatch(head=True)

    def do_POST(self):
        self._dispatch(post=True)


def create_server(*, port: int = 8765, service: AuctionWebService | None = None):
    return AuctionHTTPServer(('127.0.0.1', port), service or AuctionWebService())


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Giao diện Đấu Giá Việt - Đề tài 19')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true', help='Mở trình duyệt sau khi máy chủ sẵn sàng')
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('port phải nằm trong khoảng 1..65535')
    try:
        service = AuctionWebService()
        service.health()
        server = create_server(port=args.port, service=service)
    except OSError:
        print(f'Không mở được cổng {args.port}. Nếu chương trình đã chạy, mở http://127.0.0.1:{args.port}; hoặc chọn --port khác.', file=sys.stderr)
        return 1
    except psycopg.Error:
        print('Không kết nối được PostgreSQL. Kiểm tra dịch vụ và .env, sau đó mở lại chương trình.', file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    url = f'http://127.0.0.1:{server.server_address[1]}'
    print(f'Đấu Giá Việt đã sẵn sàng: {url}', flush=True)
    print('Giữ cửa sổ này mở. Nhấn Ctrl+C để dừng. PostgreSQL sử dụng nguyên các quy tắc hiện có.', flush=True)
    if args.open:
        threading.Timer(.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        print('\nĐã dừng giao diện.')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
