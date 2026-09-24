"""安息角の実験データ点を解析Excel(saor_analysis.xlsx)の条件シートへ転記する。

CSVのA〜F列(ヘッダー行を含む)を、対応する条件番号シートのA〜F列へそのまま書き込む。
シート内の数式・書式・グラフは変更せず、値のみを更新する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook

logger = logging.getLogger(__name__)

SETTINGS_SHEET_NAME = "設定・集計"
_CONDITION_HEADER = "条件"
_SHEET_NAME_HEADER = "シート名"
_HEADER_SEARCH_ROWS = 20
_HEADER_SEARCH_COLUMNS = 30
_MAX_CONDITION_ROWS = 200

#: 転記対象の列(``experiment_data_points.csv``の列順と一致させる)。
EXPERIMENT_POINT_COLUMNS: tuple[str, ...] = (
    "x_coord",
    "min_y_coordinate",
    "max_y_coordinate",
    "avg_y_coordinate",
    "fit_top",
    "fit_bottom",
)
#: 書き込み開始位置(A1からヘッダー行を含めて書き込む)。
_START_ROW = 1
_START_COLUMN = 1

#: 条件シートで安息角が入るセルを特定するためのラベル。
_ANGLE_LABEL = "安息角"

#: FILTER(動的配列)数式が置かれたセルと、そのスピル先(K列)の範囲。
_DYNAMIC_ARRAY_CELL = "K2"
_SPILL_COLUMN = 11
_SPILL_FIRST_ROW = 2
_SPILL_LAST_ROW = 200

#: Excel COMが数式エラーを返す際の値。数値として扱うと誤った結果になるため名前へ変換する。
_EXCEL_ERROR_VALUES: dict[int, str] = {
    -2146826288: "#NULL!",
    -2146826281: "#DIV/0!",
    -2146826273: "#VALUE!",
    -2146826265: "#REF!",
    -2146826259: "#NAME?",
    -2146826252: "#NUM!",
    -2146826246: "#N/A",
}


class SaorAnalysisExcelError(RuntimeError):
    """安息角解析Excelへの転記に失敗した場合に送出する例外。"""


def get_condition_sheet_name(workbook_path: str | Path, condition_id: int) -> str:
    """「設定・集計」シートの``シート名``列から条件番号に対応するシート名を取得する。"""
    path = Path(workbook_path)
    if not path.is_file():
        raise FileNotFoundError(f"安息角解析Excelが見つかりません: {path}")

    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        if SETTINGS_SHEET_NAME not in workbook.sheetnames:
            raise SaorAnalysisExcelError(
                f"「{SETTINGS_SHEET_NAME}」シートがありません: {path}"
            )
        rows = [
            list(row)
            for row in workbook[SETTINGS_SHEET_NAME].iter_rows(
                min_row=1,
                max_row=_HEADER_SEARCH_ROWS + _MAX_CONDITION_ROWS,
                max_col=_HEADER_SEARCH_COLUMNS,
                values_only=True,
            )
        ]
        available_sheets = list(workbook.sheetnames)
    finally:
        workbook.close()

    condition_column, sheet_name_column, data_start_row = _find_layout(rows, path)

    for row_index in range(data_start_row, len(rows)):
        value = _cell(rows, row_index, condition_column)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if int(value) != condition_id:
            continue

        sheet_value = _cell(rows, row_index, sheet_name_column)
        if sheet_value is None:
            raise SaorAnalysisExcelError(
                f"条件{condition_id}のシート名が空です。"
                "Excelを開いて保存し、数式の計算結果を確定させてください。"
            )
        sheet_name = _normalize_sheet_name(sheet_value)
        if sheet_name not in available_sheets:
            raise SaorAnalysisExcelError(
                f"条件{condition_id}のシート '{sheet_name}' が存在しません。"
                f"利用可能なシート: {available_sheets}"
            )
        return sheet_name

    raise SaorAnalysisExcelError(
        f"「{SETTINGS_SHEET_NAME}」シートに条件{condition_id}の行が見つかりません。"
    )


def _cell(rows: list[list[Any]], row_index: int, column_index: int) -> Any:
    if row_index >= len(rows) or column_index >= len(rows[row_index]):
        return None
    return rows[row_index][column_index]


def _find_layout(rows: list[list[Any]], path: Path) -> tuple[int, int, int]:
    """``条件``列・``シート名``列と、データ開始行(0始まり)を特定する。"""
    for row_index in range(min(_HEADER_SEARCH_ROWS, len(rows))):
        condition_column = _find_header(rows, row_index, _CONDITION_HEADER)
        if condition_column is None:
            continue
        sheet_name_column = _find_header(rows, row_index, _SHEET_NAME_HEADER)
        if sheet_name_column is not None:
            return condition_column, sheet_name_column, row_index + 1

    raise SaorAnalysisExcelError(
        f"「{SETTINGS_SHEET_NAME}」シートに見出し"
        f"({_CONDITION_HEADER}、{_SHEET_NAME_HEADER})が見つかりません: {path}"
    )


def _find_header(rows: list[list[Any]], row_index: int, header: str) -> int | None:
    for column_index, value in enumerate(rows[row_index]):
        if isinstance(value, str) and value.strip() == header:
            return column_index
    return None


def _normalize_sheet_name(value: Any) -> str:
    """``1``のような数値シート名を文字列へ正規化する。"""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        rounded = round(float(value), 10)
        return str(int(rounded)) if rounded.is_integer() else repr(rounded)
    return str(value).strip()


def load_experiment_points(csv_path: str | Path, condition_id: int) -> pd.DataFrame:
    """実験データ点CSVを読み込み、必須列の有無を確認する。"""
    path = Path(csv_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"条件{condition_id}: 実験データ点CSVが見つかりません: {path}"
        )

    frame = pd.read_csv(path)
    missing = [column for column in EXPERIMENT_POINT_COLUMNS if column not in frame.columns]
    if missing:
        raise SaorAnalysisExcelError(
            f"条件{condition_id}: CSVに必要な列がありません: {missing}"
            f"(CSVの列: {list(frame.columns)}、ファイル: {path})"
        )
    if frame.empty:
        raise SaorAnalysisExcelError(f"条件{condition_id}: CSVにデータがありません: {path}")

    return frame.loc[:, list(EXPERIMENT_POINT_COLUMNS)]


def write_experiment_points(
    workbook_path: str | Path,
    condition_id: int,
    csv_path: str | Path,
    *,
    sheet_name: str | None = None,
) -> dict[str, Any]:
    """CSVのA〜F列を条件シートのA〜F列へ転記し、上書き保存する。

    数式・書式・グラフは変更せず値のみを書き込む。DataFrameのindexは出力しない。
    """
    path = Path(workbook_path)
    frame = load_experiment_points(csv_path, condition_id)
    resolved_sheet_name = sheet_name or get_condition_sheet_name(path, condition_id)

    workbook = load_workbook(path)
    try:
        if resolved_sheet_name not in workbook.sheetnames:
            raise SaorAnalysisExcelError(
                f"条件{condition_id}: シート '{resolved_sheet_name}' が存在しません。"
                f"利用可能なシート: {workbook.sheetnames}"
            )
        worksheet = workbook[resolved_sheet_name]

        _clear_previous_values(worksheet, len(frame))

        for column_offset, column_name in enumerate(EXPERIMENT_POINT_COLUMNS):
            worksheet.cell(
                row=_START_ROW, column=_START_COLUMN + column_offset, value=column_name
            )

        for row_offset, record in enumerate(frame.itertuples(index=False), start=1):
            for column_offset, value in enumerate(record):
                worksheet.cell(
                    row=_START_ROW + row_offset,
                    column=_START_COLUMN + column_offset,
                    value=float(value),
                )

        workbook.save(path)
    finally:
        workbook.close()

    logger.info(
        "saor experiment points written: condition=%d sheet=%s rows=%d",
        condition_id,
        resolved_sheet_name,
        len(frame),
    )
    return {
        "workbook": str(path.resolve()),
        "condition_id": condition_id,
        "sheet_name": resolved_sheet_name,
        "csv": str(Path(csv_path).resolve()),
        "row_count": int(len(frame)),
        "columns": list(EXPERIMENT_POINT_COLUMNS),
    }


def _clear_previous_values(worksheet: Any, new_row_count: int) -> None:
    """前回転記した値のうち、今回より下の行を消して古いデータを残さない。"""
    last_row = _START_ROW + new_row_count
    for row_index in range(last_row + 1, worksheet.max_row + 1):
        for column_offset in range(len(EXPERIMENT_POINT_COLUMNS)):
            worksheet.cell(row=row_index, column=_START_COLUMN + column_offset).value = None


def is_recalculation_available() -> bool:
    """Excel COMによる再計算が利用できるかを返す。"""
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        return False
    return True


def recalculate_and_read_angles(
    workbook_path: str | Path, sheet_names_by_condition: dict[int, str]
) -> dict[str, Any]:
    """ブックを再計算し、各条件シートの安息角を読み取る。

    openpyxlでは数式を再計算できないため、COMが使えない場合は値を確定させず
    ``recalculation_required``を返す。
    """
    path = Path(workbook_path).resolve()
    result: dict[str, Any] = {"workbook": str(path), "recalculated": False}

    if not is_recalculation_available():
        result["recalculation_required"] = True
        result["note"] = (
            "Excel COM(pywin32)が利用できないため再計算していません。"
            "古いキャッシュ値は結果として採用しません。"
        )
        return result

    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    excel = None
    workbook = None
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        workbook = excel.Workbooks.Open(str(path))
        excel.Application.CalculateFullRebuild()

        spill_results: dict[str, Any] = {}
        angles: dict[str, float | None] = {}
        errors: dict[str, str] = {}
        for condition_id, sheet_name in sorted(sheet_names_by_condition.items()):
            worksheet = workbook.Worksheets(sheet_name)
            spill_results[str(condition_id)] = _restore_dynamic_array(worksheet)
            value, error = _find_angle_value(worksheet)
            angles[str(condition_id)] = value
            if error is not None:
                errors[str(condition_id)] = error

        workbook.Save()

        result["recalculated"] = True
        result["angles_deg"] = angles
        result["dynamic_array"] = spill_results
        if errors:
            result["formula_errors"] = errors
            result["recalculation_required"] = True

        not_spilled = [
            condition_id
            for condition_id, spill in spill_results.items()
            if spill.get("spilled_rows", 0) <= 1
        ]
        if not_spilled:
            result["not_spilled_condition_ids"] = not_spilled
            result["recalculation_required"] = True
    finally:
        # COM側で例外が起きた後はプロキシが切断されていることがあるため、後始末も保護する。
        for closer in (
            lambda: workbook.Close(SaveChanges=False) if workbook is not None else None,
            lambda: excel.Quit() if excel is not None else None,
        ):
            try:
                closer()
            except Exception:  # noqa: BLE001 - 後始末の失敗で本来の例外を隠さない
                logger.warning("Excel COMの後始末に失敗しました", exc_info=True)
        pythoncom.CoUninitialize()

    return result


def _restore_dynamic_array(worksheet: Any) -> dict[str, Any]:
    """FILTER等の動的配列数式を再確定し、スピル範囲を復元する。

    openpyxlで保存するとスピル結果が失われるため、再計算だけでは展開されないことがある。
    その場合は``Formula2``を取得して同じセルへ再設定し、F2→Enter相当の再確定を行う。
    """
    cell = worksheet.Range(_DYNAMIC_ARRAY_CELL)
    formula = cell.Formula2
    if not isinstance(formula, str) or not formula.startswith("="):
        return {"cell": _DYNAMIC_ARRAY_CELL, "formula": formula, "spilled_rows": 0}

    spilled_rows = _count_spilled_rows(worksheet)
    reapplied = False
    if spilled_rows <= 1:
        cell.Formula2 = formula
        worksheet.Calculate()
        spilled_rows = _count_spilled_rows(worksheet)
        reapplied = True

    return {
        "cell": _DYNAMIC_ARRAY_CELL,
        "formula": cell.Formula2,
        "formula_preserved": isinstance(cell.Formula2, str)
        and cell.Formula2.startswith("="),
        "spilled_rows": spilled_rows,
        "formula_reapplied": reapplied,
    }


def _count_spilled_rows(worksheet: Any) -> int:
    """スピル先(K列)に展開された数値セル数を数える。"""
    count = 0
    for row_index in range(_SPILL_FIRST_ROW, _SPILL_LAST_ROW + 1):
        value = worksheet.Cells(row_index, _SPILL_COLUMN).Value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if int(value) in _EXCEL_ERROR_VALUES:
            continue
        count += 1
    return count


def _find_angle_value(worksheet: Any) -> tuple[float | None, str | None]:
    for row_index in range(1, _HEADER_SEARCH_ROWS + 1):
        for column_index in range(1, _HEADER_SEARCH_COLUMNS + 1):
            label = worksheet.Cells(row_index, column_index).Value
            if not isinstance(label, str) or label.strip() != _ANGLE_LABEL:
                continue
            value = worksheet.Cells(row_index, column_index + 1).Value
            return _coerce_excel_value(value)
    return None, f"'{_ANGLE_LABEL}' ラベルが見つかりません"


def _coerce_excel_value(value: Any) -> tuple[float | None, str | None]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, None
    error_name = _EXCEL_ERROR_VALUES.get(int(value))
    if error_name is not None:
        return None, error_name
    return float(value), None
