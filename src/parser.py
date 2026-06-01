from datetime import date, datetime
from typing import Any

import openpyxl

from config import AppConfig, DateFilter, FilterConfig, NumberFilter, TextFilter
from utils import OPERATOR_MAP, clean_text


def _evaluate_filter(raw_cell_value: Any, filter: FilterConfig) -> bool:
    if raw_cell_value is None:
        return False

    try:
        match filter:
            case NumberFilter():
                cell_val = float(raw_cell_value)
                target_val = filter.value

            case TextFilter():
                cell_val = clean_text(str(raw_cell_value))
                target_val = filter.value

            case DateFilter():
                if isinstance(raw_cell_value, datetime):
                    cell_val = raw_cell_value
                else:
                    cell_val = datetime.fromisoformat(str(raw_cell_value).strip())

                val_str = filter.value.strip().lower()
                if val_str == 'now':
                    target_val = datetime.now()
                elif val_str == 'today':
                    target_val = date.today()
                elif 't' in val_str or ':' in val_str:
                    target_val = datetime.fromisoformat(val_str)
                else:
                    target_val = date.fromisoformat(val_str)

        op_fn = OPERATOR_MAP[filter.operator]
        return op_fn(cell_val, target_val)

    except ValueError, TypeError:
        return False


async def get_sheet_data(
    config: AppConfig, filters: list[FilterConfig], context: APIRequestContext
) -> list[tuple[int, str]]:
    url = config.spreadsheet.url.split('/edit')[0] + '/export?format=xlsx'
    response = await context.get(url)
    if not response.ok:
        raise RuntimeError(f'Fetch failed: {response.status}')

    body = await response.body()
    wb = openpyxl.load_workbook(BytesIO(body), data_only=True)

    sheet = None
    if (target_name := config.spreadsheet.sheet) is not None:
        for idx, name in enumerate(wb.sheetnames):
            if clean_text(name) == target_name:
                sheet = wb.worksheets[idx]
                break

    if sheet is None:
        sheet = wb.active
    assert sheet is not None

    col_map = {clean_text(str(cell.value)): idx + 1 for idx, cell in enumerate(sheet[1])}
    link_col = config.spreadsheet.link_column
    needed_cols = {link_col}
    for filter in config.filters:
        needed_cols.add(filter.column)
    for rule in config.rules:
        if column := getattr(rule, 'column', None):
            needed_cols.add(column)

    links = []
    for row in range(2, sheet.max_row + 1):
        row_data = {col: sheet.cell(row=row, column=col_map[col]).value for col in needed_cols}
        for filter in filters:
            keep_row = _evaluate_filter(row_data[filter.column], filter)
            if not keep_row:
                continue

        link_cell = sheet.cell(row=row, column=col_map[link_col])
        if link_cell.hyperlink:
            links.append((row, link_cell.hyperlink.target))

    return links
