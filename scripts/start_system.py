"""Open/reuse the local auction website, or stop only this application's server."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import webbrowser

ROOT = Path(__file__).resolve().parents[1]


def request_json(url, *, data=None, token=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['X-Auction-Token'] = token
    if data is not None:
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers)
    with urlopen(request, timeout=2) as response:
        return json.load(response)


def is_our_server(base):
    try:
        result = request_json(base + '/api/health')
        return result.get('ok') is True and result.get('data', {}).get('application') == 'auction19'
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return False


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='Mở giao diện hệ thống đấu giá trên máy này')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--no-browser', action='store_true', help='Chỉ khởi động máy chủ, không mở tab')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port phải nằm trong khoảng 1..65535')
    base = f'http://127.0.0.1:{args.port}'
    if args.stop:
        if not is_our_server(base):
            print('Hệ thống hiện chưa chạy tại ' + base)
            return 0
        try:
            token = request_json(base + '/api/health')['data']['csrf_token']
            request_json(base + '/api/system/stop', data={}, token=token)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError):
            print('Chưa dừng được máy chủ. Kiểm tra kết nối và thử lại.')
            return 1
        deadline = time.monotonic() + 5
        while is_our_server(base) and time.monotonic() < deadline:
            time.sleep(.1)
        if is_our_server(base):
            print('Máy chủ đang hoàn tất thao tác dừng. Vui lòng thử lại sau vài giây.')
            return 1
        print('Đã dừng hệ thống đấu giá.')
        return 0
    if not is_our_server(base):
        if not (ROOT / '.env').exists() and not os.environ.get('DATABASE_URL'):
            print('Chưa có cấu hình PostgreSQL. Xem README.md để tạo .env và cài đặt CSDL.')
            return 1
        temp = ROOT / 'tmp'
        temp.mkdir(exist_ok=True)
        environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        with (temp / 'web-server.log').open('ab') as logfile:
            process = subprocess.Popen(
                [sys.executable, '-m', 'auction_lab.web', '--port', str(args.port)],
                cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                stdout=logfile, stderr=logfile, **options,
            )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if is_our_server(base):
                break
            if process.poll() is not None:
                print('Không khởi động được hệ thống. Kiểm tra PostgreSQL hoặc cổng đang được dùng.')
                print('Chi tiết nằm trong tmp/web-server.log.')
                return 1
            time.sleep(.25)
        else:
            # This exact child belongs to this launcher, so terminating it cannot
            # accidentally stop another process or a reused server instance.
            process.terminate()
            print('Máy chủ chưa sẵn sàng. Kiểm tra PostgreSQL và tmp/web-server.log.')
            return 1
    print('Hệ thống sẵn sàng: ' + base)
    if not args.no_browser:
        webbrowser.open(base)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
