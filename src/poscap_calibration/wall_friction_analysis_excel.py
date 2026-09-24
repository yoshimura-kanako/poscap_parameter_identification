"""壁面摩擦試験の解析Excel操作(手順書Phase2 1.2.4以降)。

条件1〜3の壁面動摩擦係数・壁面静止摩擦係数はテンプレート側の数式で算出されるため、
Python側では計算せず、設定値の書込みと再計算のみを行う。
本せん断の時系列書込みはせん断試験と列構造が同じため、``shear_analysis_excel``の
列探索・COM書込み処理を流用する。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from poscap_calibration.models import WallFrictionCondition
from poscap_calibration.response_surface_export import is_recalculation_available
from poscap_calibration.shear_analysis_excel import (
    _cell_value_com,
    _column_letter_to_index,
    _write_time_series_com,
    find_time_series_columns,
)

__all__ = [
    "SETTINGS_SHEET_NAME",
    "SHEAR_SHEET_HEADERS",
    "WallFrictionExcelError",
    "find_time_series_columns",
    "get_shear_sheet_name",
    "is_recalculation_available",
    "read_wall_friction_conditions",
    "update_shear_time_series",
    "write_settings_and_recalculate",
]

SETTINGS_SHEET_NAME = "設定・集計"
PEAK_RATIO_CELL = "B3"
EXPERIMENT_SLOPE_CELL = "B5"

#: 荷重ごとの本せん断シート名見出し。5/7 kPaへの展開はこの表だけで対応できる。
SHEAR_SHEET_HEADERS: dict[float, str] = {
    3.0: "本せん断3kPa",
    5.0: "本せん断5kPa",
    7.0: "本せん断7kPa",
}

_CONDITION_HEADER = "条件"
_DYNAMIC_FRICTION_HEADER = "動摩擦係数"
_STATIC_FRICTION_HEADER = "静止摩擦係数"
_STEADY_SLOPE_HEADER = "補正前"
_STEADY_SLOPE_CORRECTED_HEADER = "補正後"
_HEADER_SEARCH_ROWS = 10
_MAX_CONDITION_ROWS = 20


class WallFrictionExcelError(RuntimeError):
    """壁面摩擦解析Excelの操作に失敗した場合に送出する例外。"""


def write_settings_and_recalculate(
    workbook_path: str | Path,
    peak_ratio: float,
    experiment_steady_slope: float,
) -> dict[str, Any]:
    """ピーク比と実験定常傾きを書き込み、Excelを再計算して保存する。

    openpyxlではグラフや数式が失われるため、書込みから再計算までCOMで行う。
    """
    path = Path(workbook_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"壁面摩擦解析Excelが見つかりません: {path}")
    if not is_recalculation_available():
        raise WallFrictionExcelError(
            "Excel COM(pywin32)が利用できないため再計算できません。"
            "pywin32をインストールした環境で実行してください。"
        )

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
        try:
            worksheet = workbook.Worksheets(SETTINGS_SHEET_NAME)
        except Exception as error:
            available = [sheet.Name for sheet in workbook.Worksheets]
            raise WallFrictionExcelError(
                f"シート '{SETTINGS_SHEET_NAME}' がありません: {path}。"
                f"利用可能なシート: {available}"
            ) from error
        worksheet.Range(PEAK_RATIO_CELL).Value = float(peak_ratio)
        worksheet.Range(EXPERIMENT_SLOPE_CELL).Value = float(experiment_steady_slope)
        excel.Application.CalculateFullRebuild()
        workbook.Save()
    finally:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()

    return {
        "workbook": str(path),
        "peak_ratio": float(peak_ratio),
        "experiment_steady_slope": float(experiment_steady_slope),
        "recalculated": True,
    }


def read_wall_friction_conditions(
    workbook_path: str | Path,
) -> list[WallFrictionCondition]:
    """再計算済みの解析Excelから条件ごとの壁面摩擦係数を読み取る。"""
    path = Path(workbook_path)
    rows = _read_cells(path, _HEADER_SEARCH_ROWS + _MAX_CONDITION_ROWS)
    layout = _find_header_layout(rows, path)

    conditions: list[WallFrictionCondition] = []
    for row_index in range(layout["data_row"], len(rows)):
        condition_value = _cell(rows, row_index, layout["condition_column"])
        if not isinstance(condition_value, (int, float)) or isinstance(condition_value, bool):
            if conditions:
                break
            continue
        values: dict[str, float] = {}
        for key, column in (
            ("dynamic_friction", layout["dynamic_column"]),
            ("static_friction", layout["static_column"]),
        ):
            value = _cell(rows, row_index, column)
            if isinstance(value, str) and value.startswith("#"):
                raise WallFrictionExcelError(
                    f"条件{int(condition_value)}の{key}が数式エラーです: {value}。"
                    "Excelを再計算してから読み取ってください。"
                )
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise WallFrictionExcelError(
                    f"条件{int(condition_value)}の{key}が数値ではありません: {value!r}。"
                    "Excelを再計算してから読み取ってください。"
                )
            values[key] = float(value)
        conditions.append(
            WallFrictionCondition(condition_id=int(condition_value), **values)
        )

    if not conditions:
        raise WallFrictionExcelError(
            f"「{SETTINGS_SHEET_NAME}」シートから条件行を読み取れませんでした: {path}"
        )
    return sorted(conditions, key=lambda condition: condition.condition_id)


def get_shear_sheet_name(
    workbook_path: str | Path, condition_id: int, load_kpa: float
) -> str:
    """条件番号と荷重に対応する本せん断シート名を「設定・集計」から取得する。"""
    path = Path(workbook_path)
    if not path.is_file():
        raise FileNotFoundError(f"壁面摩擦解析Excelが見つかりません: {path}")

    header = SHEAR_SHEET_HEADERS.get(float(load_kpa))
    if header is None:
        raise WallFrictionExcelError(
            f"未対応の荷重です: {load_kpa}kPa。対応荷重: {sorted(SHEAR_SHEET_HEADERS)}"
        )

    rows = _read_cells(path, _HEADER_SEARCH_ROWS + _MAX_CONDITION_ROWS)
    condition_row = _locate_condition_row(rows, condition_id, path)

    column_index = None
    for header_row in range(min(_HEADER_SEARCH_ROWS, len(rows))):
        column_index = _find_header_column(rows, header_row, header)
        if column_index is not None:
            break
    if column_index is None:
        raise WallFrictionExcelError(
            f"「{SETTINGS_SHEET_NAME}」シートに見出し '{header}' が見つかりません: {path}"
        )

    value = _cell(rows, condition_row, column_index)
    if value is None:
        raise WallFrictionExcelError(
            f"条件{condition_id}の '{header}' シート名が空です。"
            "Excelを開いて保存し、数式の計算結果を確定させてください。"
        )

    sheet_name = _normalize_sheet_name(value)
    available = load_workbook(path, read_only=True).sheetnames
    if sheet_name not in available:
        raise WallFrictionExcelError(
            f"条件{condition_id} {load_kpa}kPaの本せん断シート '{sheet_name}' がありません。"
            f"利用可能なシート: {available}"
        )
    return sheet_name


def _locate_condition_row(
    rows: list[tuple[Any, ...]], condition_id: int, path: Path
) -> int:
    """「条件」見出し列から指定条件のデータ行(0始まり)を返す。"""
    layout = _find_header_layout(rows, path)
    for data_row in range(layout["data_row"], len(rows)):
        value = _cell(rows, data_row, layout["condition_column"])
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if int(value) == condition_id:
                return data_row
    raise WallFrictionExcelError(
        f"「{SETTINGS_SHEET_NAME}」シートに条件{condition_id}の行が見つかりません: {path}"
    )


def _normalize_sheet_name(value: Any) -> str:
    """``1.3``のような数値シート名を文字列へ正規化する。

    シート名は加算の連鎖で求められるため浮動小数点誤差を含む。丸めてから文字列化する。
    """
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        rounded = round(float(value), 10)
        return str(int(rounded)) if rounded.is_integer() else repr(rounded)
    return str(value).strip()


def update_shear_time_series(
    workbook_path: str | Path,
    condition_id: int,
    load_kpa: float,
    times: list[float],
    forces: list[float],
    moments: list[float],
) -> dict[str, Any]:
    """本せん断の時系列を対応シートへ書き込み、再計算して定常せん断応力を返す。

    列位置は``find_time_series_columns``がせん断応力の数式から特定するため決め打ちしない。
    時系列CSVのヘッダー行も含めて書き込む。
    """
    path = Path(workbook_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"壁面摩擦解析Excelが見つかりません: {path}")
    if not (len(times) == len(forces) == len(moments)):
        raise WallFrictionExcelError(
            f"時系列の長さが一致しません: time={len(times)} force={len(forces)} "
            f"moment={len(moments)}"
        )
    if not times:
        raise WallFrictionExcelError("時系列データが空です。")
    if not is_recalculation_available():
        raise WallFrictionExcelError(
            "Excel COM(pywin32)が利用できないため再計算できません。"
            "pywin32をインストールした環境で実行してください。"
        )

    sheet_name = get_shear_sheet_name(path, condition_id, load_kpa)
    columns = find_time_series_columns(path, sheet_name)
    steady_cell = _find_steady_slope_source_cell(path, condition_id)

    # CSVのヘッダーを読む(Time, Force Y, Moment Y)
    csv_header = _read_time_series_header(times, forces, moments, columns)

    result: dict[str, Any] = {
        "workbook": str(path),
        "condition_id": condition_id,
        "load_kpa": float(load_kpa),
        "sheet": sheet_name,
        "columns": columns,
        "row_count": len(times),
        "steady_slope_cell": steady_cell,
    }

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
        worksheet = workbook.Worksheets(sheet_name)
        
        # ヘッダーを最初に書き込む
        _write_header_com(worksheet, columns, csv_header)
        
        # 時系列データを書き込む
        _write_time_series_com(worksheet, columns, times, forces, moments)
        
        excel.Application.CalculateFullRebuild()
        workbook.Save()

        graph_sheet = workbook.Worksheets(steady_cell["sheet"])
        stress_value, stress_error = _cell_value_com(
            graph_sheet, steady_cell["steady_shear_stress_address"]
        )
        slope_value, slope_error = _cell_value_com(
            graph_sheet, steady_cell["steady_slope_address"]
        )
        result["steady_shear_stress_kpa"] = stress_value
        result["steady_slope"] = slope_value
        errors = {
            key: error
            for key, error in (
                ("steady_shear_stress_kpa", stress_error),
                ("steady_slope", slope_error),
            )
            if error is not None
        }
        if errors:
            result["formula_errors"] = errors
            result["note"] = (
                "再計算後も数式エラーが残っています。"
                f"条件{condition_id}の未実行荷重がある場合は3/5/7 kPaをすべて実行してください。"
            )
    finally:
        if workbook is not None:
            workbook.Close(SaveChanges=False)
        if excel is not None:
            excel.Quit()
        pythoncom.CoUninitialize()

    result["recalculated"] = True
    return result


def _read_time_series_header(
    times: list[float], forces: list[float], moments: list[float], columns: dict[str, int]
) -> dict[str, str]:
    """時系列用のヘッダー辞書を構築する。

    ``find_time_series_columns``が特定した列位置に対応するヘッダー名を返す。
    """
    # Moment Y列から逆算して Time / Force Y / Moment Y のヘッダーを推定する
    return {
        "time": "Date [s]",
        "force_y": "Force Y (Lid Translational Motion) [N]",
        "moment_y": "Moment Y (Lid Rotational Motion) [N.m]",
    }


def _write_header_com(worksheet: Any, columns: dict[str, int], header: dict[str, str]) -> None:
    """ヘッダー行(start_row - 1)を書き込む。"""
    header_row = columns["start_row"] - 1
    worksheet.Cells(header_row, columns["time"]).Value = header["time"]
    worksheet.Cells(header_row, columns["force_y"]).Value = header["force_y"]
    worksheet.Cells(header_row, columns["moment_y"]).Value = header["moment_y"]



def _find_steady_slope_source_cell(
    workbook_path: Path, condition_id: int
) -> dict[str, Any]:
    """定常傾き(補正前)の参照先を辿り、グラフシート上の該当セル番地を返す。

    定常せん断応力は定常傾きの1行上(3/5/7 kPa平均)に並ぶ、という
    テンプレートの配置を実ファイルの数式から辿って求める。
    """
    workbook = load_workbook(workbook_path, read_only=False, data_only=False)
    try:
        worksheet = workbook[SETTINGS_SHEET_NAME]
        rows = [
            tuple(row)
            for row in worksheet.iter_rows(
                max_row=_HEADER_SEARCH_ROWS + _MAX_CONDITION_ROWS, values_only=True
            )
        ]
        condition_row = _locate_condition_row(rows, condition_id, workbook_path)

        slope_column = None
        for header_row in range(min(_HEADER_SEARCH_ROWS, len(rows))):
            slope_column = _find_header_column(rows, header_row, _STEADY_SLOPE_HEADER)
            if slope_column is not None:
                break
        if slope_column is None:
            raise WallFrictionExcelError(
                f"「{SETTINGS_SHEET_NAME}」シートに見出し "
                f"'{_STEADY_SLOPE_HEADER}' が見つかりません: {workbook_path}"
            )

        formula = worksheet.cell(row=condition_row + 1, column=slope_column + 1).value
    finally:
        workbook.close()

    match = re.search(r"=\s*'?([^'!]+)'?!\$?([A-Z]{1,3})\$?(\d+)", str(formula))
    if match is None:
        raise WallFrictionExcelError(
            f"条件{condition_id}の定常傾きセルの参照先を解析できません: {formula!r}"
        )
    sheet_name, column_letter, row_text = match.groups()
    slope_row = int(row_text)
    return {
        "sheet": sheet_name,
        "steady_slope_address": f"{column_letter}{slope_row}",
        # 定常せん断応力(3/5/7 kPa平均)は定常傾きの1行上に配置される。
        "steady_shear_stress_address": f"{column_letter}{slope_row - 1}",
        "steady_slope_column": _column_letter_to_index(column_letter),
    }


def _read_cells(workbook_path: Path, max_row: int) -> list[tuple[Any, ...]]:
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    try:
        if SETTINGS_SHEET_NAME not in workbook.sheetnames:
            raise WallFrictionExcelError(
                f"シート '{SETTINGS_SHEET_NAME}' がありません: {workbook_path}。"
                f"利用可能なシート: {workbook.sheetnames}"
            )
        worksheet = workbook[SETTINGS_SHEET_NAME]
        return [
            row for row in worksheet.iter_rows(max_row=max_row, values_only=True)
        ]
    finally:
        workbook.close()


def _find_header_layout(rows: list[tuple[Any, ...]], path: Path) -> dict[str, int]:
    """「条件」見出しと、その右側にある摩擦係数見出しの位置を特定する。"""
    for row_index in range(min(_HEADER_SEARCH_ROWS, len(rows))):
        condition_column = _find_header_column(rows, row_index, _CONDITION_HEADER)
        if condition_column is None:
            continue
        # 摩擦係数の見出しは「条件」と同じ行か1行下に置かれる。
        for header_row in (row_index, row_index + 1):
            dynamic_column = _find_header_column(rows, header_row, _DYNAMIC_FRICTION_HEADER)
            static_column = _find_header_column(rows, header_row, _STATIC_FRICTION_HEADER)
            if dynamic_column is not None and static_column is not None:
                return {
                    "condition_column": condition_column,
                    "dynamic_column": dynamic_column,
                    "static_column": static_column,
                    "data_row": header_row + 1,
                }
    raise WallFrictionExcelError(
        f"「{SETTINGS_SHEET_NAME}」シートに"
        f"'{_CONDITION_HEADER}' / '{_DYNAMIC_FRICTION_HEADER}' / "
        f"'{_STATIC_FRICTION_HEADER}' の見出しが見つかりません: {path}"
    )


def _find_header_column(
    rows: list[tuple[Any, ...]], row_index: int, header: str
) -> int | None:
    if row_index >= len(rows):
        return None
    for column_index, value in enumerate(rows[row_index]):
        if isinstance(value, str) and value.strip() == header:
            return column_index
    return None


def _cell(rows: list[tuple[Any, ...]], row_index: int, column_index: int) -> Any:
    if row_index >= len(rows):
        return None
    row = rows[row_index]
    return row[column_index] if column_index < len(row) else None
