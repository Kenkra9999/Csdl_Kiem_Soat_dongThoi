"""Build the Vietnamese submission report and vector EER diagram.

Install requirements-report.txt, then run from any working directory. The report
embeds actual benchmark files when available; it never invents measurements.
"""
from __future__ import annotations
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import html
import json
import os
import re
import textwrap

from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, PageBreak,
    NextPageTemplate, Table, TableStyle, Preformatted, KeepTogether,
)
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Rect, Line, String, Polygon
from reportlab.graphics import renderSVG

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf/BAO_CAO_DE_TAI_19.pdf'
INK = colors.HexColor('#163447')
ACCENT = colors.HexColor('#087f83')
LIGHT = colors.HexColor('#edf4f5')
MUTED = colors.HexColor('#526372')


def register_fonts():
    windows = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts'
    linux = Path('/usr/share/fonts/truetype/dejavu')
    for base, bold, italic, mono in (
        (windows/'arial.ttf', windows/'arialbd.ttf', windows/'ariali.ttf', windows/'consola.ttf'),
        (linux/'DejaVuSans.ttf', linux/'DejaVuSans-Bold.ttf', linux/'DejaVuSans-Oblique.ttf', linux/'DejaVuSansMono.ttf'),
    ):
        if all(p.exists() for p in (base, bold, italic, mono)):
            for name, path in (('Body', base), ('Body-Bold', bold), ('Body-Italic', italic), ('Mono', mono)):
                pdfmetrics.registerFont(TTFont(name, str(path)))
            pdfmetrics.registerFontFamily('Body', normal='Body', bold='Body-Bold', italic='Body-Italic', boldItalic='Body-Bold')
            return
    raise RuntimeError('Cần Arial trên Windows hoặc DejaVu trên Linux để hiển thị tiếng Việt.')


def diagram():
    d = Drawing(730, 445)
    boxes = {}
    def entity(key, x, y, width, title, fields):
        height = 27 + 12 * len(fields)
        boxes[key] = (x, y, width, height)
        d.add(Rect(x, y, width, height, fillColor=colors.white, strokeColor=INK, strokeWidth=.7))
        d.add(Rect(x, y+height-22, width, 22, fillColor=INK, strokeColor=INK))
        d.add(String(x+8, y+height-15, title, fontName='Body-Bold', fontSize=9, fillColor=colors.white))
        for i, field in enumerate(fields):
            d.add(String(x+7, y+height-36-i*12, field, fontName='Body', fontSize=8, fillColor=INK))
    def connect(a, b, label, side='vertical'):
        x,y,w,h=boxes[a]; X,Y,W,H=boxes[b]
        if side == 'horizontal':
            x1,y1,x2,y2=x+w,y+h/2,X,Y+H/2
        else:
            x1,y1,x2,y2=x+w/2,y,X+W/2,Y+H
        d.add(Line(x1,y1,x2,y2,strokeColor=ACCENT,strokeWidth=.9))
        d.add(String((x1+x2)/2+3,(y1+y2)/2+3,label,fontName='Body',fontSize=7,fillColor=ACCENT))
    entity('users', 0, 337, 155, 'USERS', ['PK id; UK email', 'full_name'])
    entity('assets', 285, 325, 170, 'ASSETS', ['PK id; FK seller_id', 'FK category_id; kind', 'title'])
    entity('categories', 575, 337, 155, 'CATEGORIES', ['PK id; FK parent_id', 'name; cây cha - con'])
    entity('art', 200, 211, 155, 'ARTWORKS', ['PK/FK asset_id', 'artist; material; year'])
    entity('col', 385, 211, 155, 'COLLECTIBLES', ['PK/FK asset_id', 'origin; rarity; year'])
    entity('ele', 575, 211, 155, 'ELECTRONICS', ['PK/FK asset_id', 'brand; model; serial'])
    entity('auctions', 0, 153, 174, 'AUCTIONS', ['PK id; FK asset_id', 'start_price; bid_step', 'opens_at; closes_at; status', 'current_price; leading_bid_id'])
    entity('reg', 0, 23, 174, 'REGISTRATIONS', ['PK/FK auction_id, user_id', 'status; registered_at'])
    entity('bids', 235, 23, 210, 'BIDS', ['PK id; UK request_id', 'FK auction_id, bidder_id', 'amount; accepted_at'])
    entity('results', 500, 77, 230, 'RESULTS', ['PK/FK auction_id', 'FK winning_bid_id (có thể NULL)', 'closed_at'])
    entity('audit', 500, 0, 230, 'AUDIT_LOG', ['PK id; FK auction_id, actor_id', 'action; details; transaction_id'])
    connect('users', 'assets', '1 : N (người bán)', 'horizontal')
    # Category relation drawn from right to left, separate from subtype links.
    d.add(Line(575,365,455,365,strokeColor=ACCENT,strokeWidth=.9))
    d.add(String(474,371,'1 : N',fontName='Body',fontSize=7,fillColor=ACCENT))
    for b in ('art','col','ele'):
        connect('assets',b,'1 : 0..1')
    d.add(String(480,307,'ISA: TOTAL + DISJOINT',fontName='Body-Bold',fontSize=8,fillColor=ACCENT))
    d.add(Line(285,343,185,343,strokeColor=ACCENT,strokeWidth=.9))
    d.add(Line(185,343,185,210,strokeColor=ACCENT,strokeWidth=.9))
    d.add(Line(185,210,174,210,strokeColor=ACCENT,strokeWidth=.9))
    d.add(String(187,274,'1 : N',fontName='Body',fontSize=7,fillColor=ACCENT))
    connect('auctions','reg','1 : N')
    connect('reg','bids','1 : N','horizontal')
    connect('bids','results','0..1 : 0..1','horizontal')
    d.add(String(0,427,'EER / LƯỢC ĐỒ QUAN HỆ - ĐỀ TÀI 19',fontName='Body-Bold',fontSize=13,fillColor=INK))
    d.add(String(0,409,'PK: khóa chính  |  UK: duy nhất  |  FK: khóa ngoại  |  N: nhiều',fontName='Body',fontSize=9,fillColor=MUTED))
    return d


class Report(BaseDocTemplate):
    def beforeDocument(self):
        self.in_appendix = False

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name in ('Heading1', 'Heading2'):
            level = 0 if flowable.style.name == 'Heading1' else 1
            title = flowable.getPlainText()
            if title in ('Mục lục', 'BÁO CÁO ĐỒ ÁN CƠ SỞ DỮ LIỆU NÂNG CAO'):
                return
            if title.startswith('Phụ lục '):
                self.in_appendix = True
            elif self.in_appendix and level == 1:
                return
            key = f'h{self.seq.nextf("heading")}'
            self.canv.bookmarkPage(key)
            self.notify('TOCEntry', (level, title, self.page, key))


def inline(text):
    text = html.escape(text)
    text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+)\)', r'<link href="\2" color="#087f83">\1</link>', text)
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', text)
    text = re.sub(r'`([^`]+)`', r'<font name="Mono" size="8">\1</font>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<b>\1</b>', text)
    text = text.replace('→', '-&gt;').replace('≤','&lt;=').replace('≥','&gt;=')
    return text


def markdown_blocks(source, styles, width=487):
    lines=source.splitlines(); out=[]; paragraph=[]; i=0; references=False
    def flush():
        if paragraph:
            out.append(Paragraph(inline(' '.join(paragraph)),styles['Small'] if references else styles['Normal']))
            paragraph.clear()
    while i < len(lines):
        line=lines[i].rstrip()
        if line.strip().startswith('<!--'):
            flush()
        elif line.startswith('```'):
            flush(); language=line[3:].strip(); code=[]; i+=1
            while i<len(lines) and not lines[i].startswith('```'):
                code.append(lines[i]); i+=1
            if language=='mermaid':
                out.append(Paragraph('Sơ đồ được trình bày ở trang EER; mã Mermaid đầy đủ có trong docs/EER.md.',styles['Small']))
            else:
                for raw in code:
                    parts=textwrap.wrap(raw.expandtabs(4),width=91,replace_whitespace=False,drop_whitespace=False) or ['']
                    out.append(Preformatted('\n'.join(parts),styles['Code'],maxLineLength=94))
                out.append(Spacer(1,7))
        elif line.startswith('|'):
            flush(); rows=[]
            while i<len(lines) and lines[i].lstrip().startswith('|'):
                cells=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells): rows.append(cells)
                i+=1
            i-=1
            if rows:
                count=max(map(len,rows))
                cell_style=styles['WideCell'] if count>=8 else styles['Cell']
                data=[[Paragraph(inline(c),cell_style) for c in (r+['']*(count-len(r)))] for r in rows]
                weights=[.65,1.35,.85,.85,.85,.65,1,1,1,1] if count==10 else [1]*count
                widths=[width*w/sum(weights) for w in weights]
                table=Table(data,colWidths=widths,repeatRows=1,hAlign='LEFT')
                table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),LIGHT),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.8,ACCENT),('LINEBELOW',(0,1),(-1,-1),.25,colors.HexColor('#d6e0e5')),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),5),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
                if count>=8:
                    table.setStyle(TableStyle([('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3)]))
                out.extend([KeepTogether([table]) if count>=8 and len(rows)<=8 else table,Spacer(1,10)])
        elif line.startswith('#'):
            flush(); m=re.match(r'^(#+)\s+(.*)',line)
            if m:
                references = m[2].strip() == 'Tài liệu tham khảo'
                level=min(len(m[1]),3)
                out.append(Paragraph(inline(m[2]),styles[f'Heading{level}']))
        elif re.match(r'^\s*[-*] ',line) or re.match(r'^\s*\d+\. ',line):
            flush(); out.append(Paragraph(inline(line.strip()),styles['Small'] if references else styles['Bullet']))
        elif line.startswith('>'):
            flush(); out.append(Paragraph(inline(line.lstrip('> ')),styles['Quote']))
        elif not line.strip(): flush()
        elif line.strip()=='---': flush(); out.append(Spacer(1,10))
        else: paragraph.append(line.strip())
        i+=1
    flush(); return out


def main():
    register_fonts()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    styles=getSampleStyleSheet()
    for name in ('Normal','BodyText'):
        styles[name].fontName='Body'; styles[name].fontSize=10; styles[name].leading=15; styles[name].spaceAfter=7
    for name,size in (('Heading1',18),('Heading2',14),('Heading3',11)):
        styles[name].fontName='Body-Bold';styles[name].fontSize=size;styles[name].leading=size+5;styles[name].textColor=INK;styles[name].spaceBefore=15;styles[name].spaceAfter=9
    for name,size,leading in (('Small',8.5,12),('Cell',8.3,12),('Bullet',9.5,14),('Quote',9,14)):
        if name not in styles:
            styles.add(ParagraphStyle(name))
        for key,value in dict(fontName='Body',fontSize=size,leading=leading,spaceAfter=6,textColor=INK).items():
            setattr(styles[name],key,value)
    styles['Bullet'].leftIndent=12
    styles.add(ParagraphStyle('WideCell',fontName='Body',fontSize=7.4,leading=10.5,textColor=INK))
    styles['Quote'].leftIndent=14;styles['Quote'].textColor=MUTED
    for key,value in dict(fontName='Mono',fontSize=7.7,leading=10,backColor=LIGHT,leftIndent=7,rightIndent=7,spaceAfter=0).items():
        setattr(styles['Code'],key,value)
    styles.add(ParagraphStyle('Cover',fontName='Body-Bold',fontSize=29,leading=38,textColor=INK,spaceAfter=20))
    if 'Subtitle' not in styles:
        styles.add(ParagraphStyle('Subtitle'))
    for key,value in dict(fontName='Body',fontSize=14,leading=22,textColor=MUTED,spaceAfter=16).items():
        setattr(styles['Subtitle'],key,value)
    W,H=A4; margin=54
    def footer(c,doc):
        w,h=c._pagesize
        c.setStrokeColor(ACCENT);c.line(42,36,w-42,36)
        c.setFont('Body',8);c.setFillColor(MUTED)
        c.drawString(42,23,'CSDL NÂNG CAO | ĐỀ TÀI 19 | PostgreSQL 18')
        c.drawRightString(w-42,23,f'Trang {doc.page}')
    doc=Report(str(OUT),pagesize=A4,leftMargin=margin,rightMargin=margin,topMargin=48,bottomMargin=49,title='Đề tài 19 - Đấu giá và kiểm soát đồng thời',author='Dự án mô phỏng CSDL nâng cao')
    doc.addPageTemplates([
        PageTemplate(id='portrait',frames=[Frame(margin,49,W-2*margin,H-97,id='normal')],onPage=footer,pagesize=A4),
        PageTemplate(id='landscape',frames=[Frame(48,49,landscape(A4)[0]-96,landscape(A4)[1]-97,id='wide')],onPage=footer,pagesize=landscape(A4)),
    ])
    story=[Spacer(1,65),Paragraph('ĐỀ TÀI 19',styles['Subtitle']),Paragraph('Thiết kế CSDL hệ thống đấu giá trực tuyến',styles['Cover']),Paragraph('Kiểm soát trả giá đồng thời<br/>Khóa dòng và SERIALIZABLE có thử lại',styles['Subtitle']),Spacer(1,25)]
    for text in ('BÁO CÁO ĐỒ ÁN CƠ SỞ DỮ LIỆU NÂNG CAO','PostgreSQL 18 - Python 3.12 - Dữ liệu giả lập','Phạm vi: chỉ bài 19 của tài liệu hướng dẫn được cung cấp.','Thông tin sinh viên, lớp và giảng viên: bổ sung theo thực tế trước khi nộp.'):
        story.append(Paragraph(text,styles['Normal']))
    story += [Spacer(1,25),Paragraph('Ngày tạo: '+datetime.now(ZoneInfo('Asia/Ho_Chi_Minh')).strftime('%d/%m/%Y %H:%M')+' (Việt Nam)',styles['Small']),PageBreak(),Paragraph('Mục lục',styles['Heading1'])]
    toc=TableOfContents();toc.levelStyles=[ParagraphStyle('Toc1',fontName='Body-Bold',fontSize=9,leading=13,spaceBefore=4),ParagraphStyle('Toc2',fontName='Body',fontSize=8,leading=11,leftIndent=16)]
    story += [toc,NextPageTemplate('landscape'),PageBreak(),diagram(),Paragraph('Quan hệ bổ sung: USERS 1:N REGISTRATIONS; USERS 1:N BIDS; AUCTIONS 1:N BIDS; AUCTIONS 1:0..1 RESULTS; AUCTIONS 1:N AUDIT_LOG. FK kép của leader và winner bảo đảm lượt trả thuộc đúng phiên. Mỗi tài sản có đúng một lớp con; một người có thể bán ở phiên này và tham gia phiên khác.',styles['Small']),NextPageTemplate('portrait'),PageBreak()]
    report=ROOT/'docs/BAO_CAO.md'
    if not report.exists(): raise RuntimeError('Chưa có docs/BAO_CAO.md')
    story += markdown_blocks(report.read_text(encoding='utf-8'),styles)
    for path,title in ((ROOT/'docs/MO_HINH_DOI_TUONG_OQL.md','Phụ lục A - Mô hình đối tượng và OQL'),(ROOT/'docs/HUONG_DAN_PGADMIN.md','Phụ lục B - Thao tác pgAdmin'),(ROOT/'docs/BAO_VE.md','Phụ lục C - Kịch bản trình bày'),(ROOT/'docs/GIAO_DIEN.md','Phụ lục D - Giao diện và thao tác trực quan')):
        if path.exists():
            story += [PageBreak(),Paragraph(title,styles['Heading1'])]
            source=re.sub(r'^# [^\n]*\n','',path.read_text(encoding='utf-8'),count=1)
            story += markdown_blocks(source,styles)
    measured=ROOT/'docs/KET_QUA_THUC_NGHIEM.md'
    if measured.exists():
        story += [PageBreak(),Paragraph('Phụ lục E - Kết quả thực đo',styles['Heading1'])]
        story += markdown_blocks(measured.read_text(encoding='utf-8'),styles)
    doc.multiBuild(story)
    renderSVG.drawToFile(diagram(),str(ROOT/'docs/EER.svg'))
    print(f'Created {OUT}')


if __name__=='__main__':
    main()
