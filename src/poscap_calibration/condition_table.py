"""shear_analysis.xlsxの「設定・集計」シートから条件別の粉体パラメータを読み取る。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from poscap_calibration.models import ShearCondition

SETTINGS_SHEET_NAME = "設定・集計"
_CONDITION_HEADER = "条件"
_PARAMETER_HEADERS = {
    "rolling_resistance": "転がり抵抗",
    "dynamic_friction": "動摩擦係数",
    "static_friction": "静止摩擦係数",
}
# ヘッダーは表の左上にあるため、探索範囲を限定して読み込み量を抑える。
_HEADER_SEARCH_ROWS = 20
_HEADER_SEARCH_COLUMNS = 30
_MAX_DATA_ROWS = 200


class ConditionTableError(ValueError):
    """条件表の読み取りに失敗した場合に送出する例外。"""


def _read_cells(workbook_path: Path) -> list[tuple[Any, ...]]:
    """「設定・集計」シートの左上領域をタプルのリストとして読み込む。

    Excelで開いたままでも読めるよう``read_only``で開き、原本は変更しない。
    """
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        if SETTINGS_SHEET_NAME not in workbook.sheetnames:
            raise ConditionTableError(
                f"「{SETTINGS_SHEET_NAME}」シートがありません: {workbook_path}"
            )
        worksheet = workbook[SETTINGS_SHEET_NAME]
        return list(
            worksheet.iter_rows(
                min_row=1,
                max_row=_HEADER_SEARCH_ROWS + _MAX_DATA_ROWS,
                max_col=_HEADER_SEARCH_COLUMNS,
                values_only=True,
            )
        )
    finally:
        workbook.close()


def _cell(rows: list[tuple[Any, ...]], row_index: int, column_index: int) -> Any:
    if row_index >= len(rows) or column_index >= len(rows[row_index]):
        return None
    return rows[row_index][column_index]


def _find_header_layout(rows: list[tuple[Any, ...]]) -> tuple[int, int, dict[str, int]]:
    """「条件」見出しの位置と、各パラメータ列、データ開始行を特定する。

    パラメータ見出しは「条件」と同じ行(安息角試験)にも、
    1行下(せん断試験)にも置かれるため、両方を探索する。
    戻り値の第1要素はデータ開始行(0始まり)。
    """
    for row_index in range(min(_HEADER_SEARCH_ROWS, len(rows))):
        for column_index, value in enumerate(rows[row_index]):
            if not isinstance(value, str) or value.strip() != _CONDITION_HEADER:
                continue

            for parameter_row in (row_index, row_index + 1):
                columns = _find_parameter_columns(rows, parameter_row)
                if columns is not None:
                    return parameter_row + 1, column_index, columns

    raise ConditionTableError(
        f"条件表の見出し({_CONDITION_HEADER}、{'、'.join(_PARAMETER_HEADERS.values())})が見つかりません。"
    )


def _find_parameter_columns(
    rows: list[tuple[Any, ...]], row_index: int
) -> dict[str, int] | None:
    """指定行から各パラメータ列を探す。すべて揃わなければNoneを返す。"""
    if row_index >= len(rows):
        return None

    columns: dict[str, int] = {}
    for key, header in _PARAMETER_HEADERS.items():
        for candidate, cell_value in enumerate(rows[row_index]):
            if isinstance(cell_value, str) and cell_value.strip() == header:
                columns[key] = candidate
                break
    return columns if len(columns) == len(_PARAMETER_HEADERS) else None


def load_shear_conditions(workbook_path: str | Path) -> list[ShearCondition]:
    """条件表の全条件を読み取り、``condition_id``の昇順で返す。"""
    path = Path(workbook_path)
    if not path.is_file():
        raise FileNotFoundError(f"条件表Excelが見つかりません: {path}")

    rows = _read_cells(path)
    data_start_row, condition_column, parameter_columns = _find_header_layout(rows)

    conditions: list[ShearCondition] = []
    for row_index in range(data_start_row, len(rows)):
        condition_value = _cell(rows, row_index, condition_column)
        if condition_value is None:
            if conditions:
                break
            continue
        if isinstance(condition_value, bool) or not isinstance(condition_value, (int, float)):
            break

        values: dict[str, float] = {}
        for key, column_index in parameter_columns.items():
            cell_value = _cell(rows, row_index, column_index)
            if cell_value is None:
                raise ConditionTableError(
                    f"条件{int(condition_value)}の{_PARAMETER_HEADERS[key]}が空です。"
                    "Excelで開いて保存し、計算結果を確定させてください。"
                )
            if isinstance(cell_value, bool) or not isinstance(cell_value, (int, float)):
                raise ConditionTableError(
                    f"条件{int(condition_value)}の{_PARAMETER_HEADERS[key]}が数値ではありません: {cell_value!r}"
                )
            values[key] = float(cell_value)

        conditions.append(ShearCondition(condition_id=int(condition_value), **values))

    if not conditions:
        raise ConditionTableError(f"条件表に条件が1件もありません: {path}")

    return sorted(conditions, key=lambda condition: condition.condition_id)


def get_shear_condition(workbook_path: str | Path, condition_id: int) -> ShearCondition:
    """条件表から指定した``condition_id``の粉体パラメータを取得する。"""
    conditions = load_shear_conditions(workbook_path)
    for condition in conditions:
        if condition.condition_id == condition_id:
            return condition

    available = [condition.condition_id for condition in conditions]
    raise ConditionTableError(f"条件{condition_id}が見つかりません。利用可能な条件: {available}")
