"""Bounded local document skills for OptiChat Agent."""
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from itertools import islice
import re
from uuid import uuid4

from opti_pdf import read_pdf


MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
TEXT_TYPES = {'.txt', '.md', '.markdown', '.csv'}
MAX_EXCEL_SCAN_ROWS = 5000
MAX_EXCEL_SCAN_COLUMNS = 24
MAX_EXCEL_OVERVIEW_SHEETS = 4
MAX_EXCEL_PAGE_ROWS = 15
MAX_EXCEL_RESULT = 3200
EXCEL_TERM_STOP = {'問題', '詢問', '是否', '可以', '需要', '如何', '收到', '提供', '已經', '沒有',
                   '先生', '小姐', '相關', '反映', '因為', '請問', '請他', '以及', '之前'}


def _excel_value(value, length=64):
    text = ' '.join(str(value).split())
    return text[:length] + ('…' if len(text) > length else '')


def _excel_sheet_rows(sheet):
    """Read bounded physical rows, even when worksheet dimension is absent."""
    rows = []
    scanned = 0
    truncated = False
    for row in islice(sheet.iter_rows(min_row=1, max_col=MAX_EXCEL_SCAN_COLUMNS),
                      MAX_EXCEL_SCAN_ROWS + 1):
        if scanned == MAX_EXCEL_SCAN_ROWS:
            truncated = True
            break
        scanned += 1
        values = [cell.value for cell in row]
        if any(value is not None and str(value).strip() for value in values):
            rows.append((scanned, values))
    return scanned, rows, truncated


def _excel_common_terms(rows, index):
    """Count recurring Chinese phrases per row, without treating overlaps as totals."""
    occurrences = Counter()
    for _, values in rows[1:]:
        value = values[index]
        if not isinstance(value, str) or len(value) < 8:
            continue
        found = set()
        for block in re.findall(r'[\u4e00-\u9fff]{2,}', value[:250]):
            for width in range(2, 6):
                found.update(block[start:start + width] for start in range(len(block) - width + 1))
        occurrences.update(term for term in found if not any(stop in term for stop in EXCEL_TERM_STOP))
    picked = []
    threshold = max(3, len(rows) // 50)
    for term, count in sorted(occurrences.items(), key=lambda item: (-item[1], -len(item[0]), item[0])):
        if count < threshold:
            break
        if any(term in prior or prior in term for prior, _ in picked):
            continue
        picked.append((term, count))
        if len(picked) == 8:
            break
    return picked


def _excel_sheet_overview(sheet):
    from openpyxl.utils import get_column_letter
    scanned, rows, truncated = _excel_sheet_rows(sheet)
    counts = [0] * MAX_EXCEL_SCAN_COLUMNS
    short_values = [Counter() for _ in counts]
    dates = [[] for _ in counts]
    for _, values in rows:
        for index, value in enumerate(values):
            if value is None or not str(value).strip():
                continue
            counts[index] += 1
            if isinstance(value, (date, datetime)):
                dates[index].append(value.date() if isinstance(value, datetime) else value)
            elif len(str(value)) <= 32:
                short_values[index][str(value).strip()] += 1
    last = max((index for index, count in enumerate(counts, 1) if count), default=0)
    lines = [f'【{sheet.title}】已掃描 {scanned} 列，{len(rows)} 列有內容；資料至 '
             f'{get_column_letter(last) if last else "無"} 欄。'
             + ('已達 5,000 列上限，後續未讀取。' if truncated else '')]
    if rows:
        number, values = rows[0]
        first = '、'.join(f'{get_column_letter(index)}={_excel_value(value, 18)}'
                         for index, value in enumerate(values, 1) if value is not None and str(value).strip())
        lines.append(f'首列（原始第 {number} 列）：{first[:185]}')
        lines.append('各欄有值列數（含首列）：' + '、'.join(
            f'{get_column_letter(index)}:{count}' for index, count in enumerate(counts, 1) if count))
    date_ranges = [f'{get_column_letter(index)} {min(items)} 至 {max(items)}'
                   for index, items in enumerate(dates, 1) if len(items) >= 2]
    if date_ranges:
        lines.append('日期範圍：' + '；'.join(date_ranges[:2]))
    common = []
    for index, values in enumerate(short_values):
        header = str(rows[0][1][index] or '') if rows else ''
        if any(word in header for word in ('姓名', '來電', '電話', '手機', '車號', '地址', '信箱', 'E-mail')):
            continue
        if counts[index] >= 5 and 1 < len(values) <= 40 and len(values) <= counts[index] / 2:
            frequent = [(value, count) for value, count in values.most_common(3)
                        if count >= 2 and value != header]
            if frequent:
                score = (3 if header in ('廠商', '類別') else
                         2 if '狀態' in header else
                         1 if any(word in header for word in ('單位', '回覆', '隸屬')) else 0)
                common.append((score, index, f'{get_column_letter(index+1)} {header}：' + '、'.join(
                    f'{_excel_value(value, 18)}({count})' for value, count in frequent)))
    if common:
        common.sort(key=lambda item: (-item[0], item[1]))
        lines.append('常見短值：' + '；'.join(item[2] for item in common[:3]))
    if rows:
        for index, heading in enumerate(rows[0][1]):
            if not isinstance(heading, str) or not any(
                    word in heading for word in ('問題', '內容', '描述', '說明', '備註')):
                continue
            terms = _excel_common_terms(rows, index)
            if terms:
                lines.append(f'{get_column_letter(index+1)} {heading}常見詞片段（按含詞列數，非互斥分類）：' +
                             '、'.join(f'{term}({count})' for term, count in terms))
                break
    # Distributed examples help the model describe the subject without implying
    # that the first rows alone represent the whole sheet.
    if len(rows) > 1:
        examples = []
        for position in sorted({1, len(rows) // 2, len(rows) - 1}):
            number, values = rows[position]
            candidates = [(index, value) for index, value in enumerate(values, 1)
                          if value is not None and len(str(value).strip()) > 18]
            if candidates:
                index, value = max(candidates, key=lambda item: len(str(item[1])))
                examples.append(f'{get_column_letter(index)}{number}={_excel_value(value, 70)}')
        if examples:
            lines.append('分段樣例：' + '；'.join(examples[:3]))
    return '\n'.join(lines)


def _excel_overview(book):
    names = book.sheetnames
    lines = [f'活頁簿共有 {len(names)} 個工作表：' + '、'.join(names[:MAX_EXCEL_OVERVIEW_SHEETS])]
    if len(names) > MAX_EXCEL_OVERVIEW_SHEETS:
        lines.append(f'僅概覽前 {MAX_EXCEL_OVERVIEW_SHEETS} 個工作表；其餘請指定 sheet 讀取。')
    lines.append('以下統計逐列掃描，文字樣例並非全部內容；每張表最多掃描 5,000 列、前 24 欄。')
    for name in names[:MAX_EXCEL_OVERVIEW_SHEETS]:
        lines.append(_excel_sheet_overview(book[name]))
    result = '\n'.join(lines)
    return result[:MAX_EXCEL_RESULT - 24] + ('\n…概覽已截斷，請指定工作表。' if len(result) > MAX_EXCEL_RESULT - 24 else '')


def _excel_page(book, sheet_name, page):
    from openpyxl.utils import get_column_letter
    if sheet_name not in book.sheetnames:
        raise ValueError('找不到指定的工作表。')
    try:
        number = int(1 if page is None else page)
    except (TypeError, ValueError) as error:
        raise ValueError('Excel 頁碼須為正整數。') from error
    if number < 1:
        raise ValueError('Excel 頁碼須為正整數。')
    scanned, rows, truncated = _excel_sheet_rows(book[sheet_name])
    pages = max(1, (len(rows) + MAX_EXCEL_PAGE_ROWS - 1) // MAX_EXCEL_PAGE_ROWS)
    if number > pages:
        raise ValueError(f'Excel 頁碼超出範圍；{sheet_name} 共有 {pages} 頁。')
    start = (number - 1) * MAX_EXCEL_PAGE_ROWS
    selected = rows[start:start + MAX_EXCEL_PAGE_ROWS]
    lines = [f'工作表：{sheet_name}；已掃描 {scanned} 列，其中 {len(rows)} 列有內容。',
             f'第 {number}/{pages} 頁（有內容的第 {start+1} 至 {start+len(selected)} 列；顯示原始儲存格位置）']
    if truncated:
        lines.append('已達 5,000 列上限，後續未讀取。')
    for row_number, values in selected:
        cells = [f'{get_column_letter(index)}{row_number}={_excel_value(value, 110)}'
                 for index, value in enumerate(values, 1) if value is not None and str(value).strip()]
        line = '  '.join(cells)
        if sum(len(item) + 1 for item in lines) + len(line) > MAX_EXCEL_RESULT - 100:
            lines.append('本頁內容較長，後續儲存格未顯示；請縮小範圍或搜尋。')
            break
        lines.append(line)
    if number < pages:
        lines.append(f'下一頁：read_excel，sheet="{sheet_name}"，page={number+1}。')
    return '\n'.join(lines)


def _check(path, suffixes):
    if path.suffix.lower() not in suffixes or not path.is_file():
        raise ValueError('檔案類型或路徑不支援。')
    if path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ValueError('文件超過 20 MB，請先縮小檔案。')


def _output(path):
    # A fresh sibling keeps the original untouched and stays in the selected folder.
    return path.with_name(f'{path.stem}-OptiChat-{uuid4().hex[:8]}{path.suffix}')


def read_document(path, kind, page=None, sheet=None):
    if kind == 'read_pdf':
        document = read_pdf(path)
        text = document['text']
        if page is not None:
            number = int(page)
            if not 1 <= number <= document['pages']:
                raise ValueError('PDF 頁碼超出範圍。')
            marker = f'\n[第 {number} 頁]\n'
            text = text.split(marker, 1)[1].split('\n[第 ', 1)[0] if marker in text else ''
        return (f"PDF 共 {document['pages']} 頁。" +
                (' 僅擷取到部分內容。' if document['truncated'] else '') + '\n' +
                (text[:3000] if text else '沒有可擷取的文字層；掃描 PDF 請在聊天中選頁使用圖片模型。'))
    if kind == 'read_excel':
        _check(path, {'.xlsx'})
        from openpyxl import load_workbook
        book = load_workbook(path, read_only=True, data_only=False, keep_links=False)
        try:
            if sheet is None and page is None:
                return _excel_overview(book)
            return _excel_page(book, sheet or book.sheetnames[0], page)
        finally:
            book.close()
    if kind == 'read_word':
        _check(path, {'.docx'})
        from docx import Document
        document = Document(path)
        lines = [f'段落 {i+1}：{p.text}' for i, p in enumerate(document.paragraphs[:80]) if p.text.strip()]
        for table_number, table in enumerate(document.tables[:5], 1):
            for row in table.rows[:15]:
                lines.append(f'表格 {table_number}：' + ' | '.join(cell.text[:100] for cell in row.cells[:10]))
        return '\n'.join(lines)[:3200] or 'Word 文件沒有可預覽的文字。'
    raise ValueError('不支援的文件讀取工具。')


def prepare_edit(path, action):
    """Validate and capture an edit. Returns a preview and a one-shot save function."""
    kind = action['action']
    target = _output(path)
    if kind == 'edit_text':
        _check(path, TEXT_TYPES)
    elif kind == 'edit_excel':
        _check(path, {'.xlsx'})
    elif kind == 'edit_word':
        _check(path, {'.docx'})
    else:
        raise ValueError('不支援的編輯工具。')
    original = path.read_bytes()
    if kind == 'edit_text':
        find = str(action.get('find') or '')
        replace = str(action.get('replace') or '')
        if not find or len(find) > 1000 or len(replace) > 3000:
            raise ValueError('請提供長度適當的原文和替換文字。')
        source = original.decode('utf-8-sig')
        if source.count(find) != 1:
            raise ValueError('原文必須恰好出現一次；請提供更明確的文字。')
        result = source.replace(find, replace, 1).encode('utf-8')
        preview = f'文字替換\n原文：{find[:180]}\n改為：{replace[:180]}'
        def write():
            with target.open('xb') as output:
                output.write(result)
    elif kind == 'edit_excel':
        from openpyxl import load_workbook
        sheet_name = str(action.get('sheet') or '').strip()
        edits = action.get('cells')
        if not sheet_name or not isinstance(edits, list) or not 1 <= len(edits) <= 30:
            raise ValueError('請指定工作表與 1 至 30 個儲存格。')
        book = load_workbook(path, keep_links=False)
        if sheet_name not in book.sheetnames:
            raise ValueError('找不到指定的工作表。')
        from openpyxl.utils.cell import coordinate_from_string, column_index_from_string
        sheet = book[sheet_name]
        lines = []
        for edit in edits:
            if not isinstance(edit, dict) or not isinstance(edit.get('cell'), str):
                raise ValueError('儲存格資料格式無效。')
            cell = edit['cell'].upper()
            try:
                column, row = coordinate_from_string(cell)
                if row > 100000 or column_index_from_string(column) > 1000:
                    raise ValueError()
            except ValueError as error:
                raise ValueError('儲存格座標無效或超出可編輯範圍。') from error
            value = edit.get('value')
            if not isinstance(value, (str, int, float, bool, type(None))) or isinstance(value, str) and len(value) > 2000:
                raise ValueError('儲存格內容只支援短文字、數字、布林值或空值。')
            previous = sheet[cell].value
            sheet[cell] = value
            lines.append(f'{cell}: {str(previous)[:60]} → {str(value)[:60]}')
        preview = 'Excel · ' + sheet_name + '\n' + '\n'.join(lines)
        def write():
            with target.open('xb') as output:
                book.save(output)
    elif kind == 'edit_word':
        from docx import Document
        document = Document(path)
        operation = action.get('operation')
        if operation == 'append':
            value = str(action.get('text') or '')
            if not value or len(value) > 3000:
                raise ValueError('請提供 1 至 3000 字的新段落。')
            document.add_paragraph(value)
            preview = 'Word · 新增段落\n' + value[:400]
        elif operation == 'replace':
            find = str(action.get('find') or '')
            replace = str(action.get('replace') or '')
            if not find or len(find) > 1000 or len(replace) > 3000:
                raise ValueError('請提供長度適當的原文和替換文字。')
            paragraphs = list(document.paragraphs)
            for table in document.tables:
                paragraphs.extend(p for row in table.rows for cell in row.cells for p in cell.paragraphs)
            runs = [run for paragraph in paragraphs for run in paragraph.runs if find in run.text]
            if len(runs) != 1 or runs[0].text.count(find) != 1:
                raise ValueError('原文須恰好位於一個格式片段中；跨格式文字請改用新增段落。')
            runs[0].text = runs[0].text.replace(find, replace, 1)
            preview = f'Word · 替換文字\n原文：{find[:180]}\n改為：{replace[:180]}'
        else:
            raise ValueError('Word 操作只支援 append 或 replace。')
        def write():
            with target.open('xb') as output:
                document.save(output)
    def apply():
        if path.read_bytes() != original:
            raise ValueError('確認期間原檔已改變，請重新讀取後再試。')
        write()
        return '已另存新檔：' + str(target)
    return preview + '\n原檔保留，將另存：' + str(target), apply
