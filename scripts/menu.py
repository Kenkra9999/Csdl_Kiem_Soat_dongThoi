"""Small local launcher; every database action remains in the tested CLI."""
from pathlib import Path
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

COMMANDS = {
    '1': ('scenario',), '2': ('list',), '3': ('verify',),
    '4': ('test',), '5': ('benchmark',), '6': ('oql',),
}
while True:
    print('\nĐỀ TÀI 19 - ĐẤU GIÁ VÀ KIỂM SOÁT ĐỒNG THỜI')
    print('1. Kịch bản nghiệp vụ  2. Xem các phiên   3. Kiểm tra bất biến')
    print('4. Chạy kiểm thử    5. Đo hai giải pháp 6. Mô phỏng OQL')
    print('7. Mở báo cáo PDF   0. Thoát')
    choice = input('Chọn số: ').strip()
    if choice == '0':
        break
    if choice == '7':
        report = ROOT / 'output/pdf/BAO_CAO_DE_TAI_19.pdf'
        if report.exists():
            os.startfile(report)
        else:
            print('Xem docs/BAO_CAO.md; PDF chưa được sinh.')
    elif choice in COMMANDS:
        subprocess.run([sys.executable, '-m', 'auction_lab', *COMMANDS[choice]], cwd=ROOT)
    else:
        print('Vui lòng chọn số từ 0 đến 7.')
