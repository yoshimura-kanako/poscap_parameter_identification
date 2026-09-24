"""条件表Excel読み取りのユニットテスト。"""

from __future__ import annotations

from pathlib import Path

import pytest
from openpyxl import Workbook

from poscap_calibration.condition_table import (
    ConditionTableError,
    get_shear_condition,
    load_shear_conditions,
)


def _create_condition_table(path: Path, rows: list[list[object]]) -> Path:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "設定・集計"

    worksheet["D1"] = "条件"
    worksheet["E2"] = "転がり抵抗"
    worksheet["F2"] = "動摩擦係数"
    worksheet["G2"] = "静止摩擦係数"
    for offset, row in enumerate(rows):
        for column_offset, value in enumerate(row):
            worksheet.cell(row=3 + offset, column=4 + column_offset, value=value)

    path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(path)
    workbook.close()
    return path


def test_load_shear_conditions_reads_all_rows(tmp_path: Path) -> None:
    path = _create_condition_table(
        tmp_path / "shear_analysis.xlsx",
        [
            [2, 0.2, 0.45, 0.49424],
            [1, 0.2, 0.2, 0.21966],
            [3, 0.7, 0.7, 0.76881],
        ],
    )

    conditions = load_shear_conditions(path)

    assert [condition.condition_id for condition in conditions] == [1, 2, 3]
    assert conditions[0].rolling_resistance == pytest.approx(0.2)
    assert conditions[0].dynamic_friction == pytest.approx(0.2)
    assert conditions[0].static_friction == pytest.approx(0.21966)
    assert conditions[0].directory_name == "condition_01"


def test_get_shear_condition_returns_requested_condition(tmp_path: Path) -> None:
    path = _create_condition_table(
        tmp_path / "shear_analysis.xlsx",
        [[1, 0.2, 0.2, 0.21966], [5, 0.45, 0.45, 0.49424]],
    )

    condition = get_shear_condition(path, 5)

    assert condition.condition_id == 5
    assert condition.rolling_resistance == pytest.approx(0.45)
    assert condition.directory_name == "condition_05"


def test_get_shear_condition_raises_for_unknown_id(tmp_path: Path) -> None:
    path = _create_condition_table(tmp_path / "shear_analysis.xlsx", [[1, 0.2, 0.2, 0.21966]])

    with pytest.raises(ConditionTableError):
        get_shear_condition(path, 9)


def test_load_shear_conditions_raises_when_formula_not_calculated(tmp_path: Path) -> None:
    path = _create_condition_table(tmp_path / "shear_analysis.xlsx", [[1, 0.2, 0.2, None]])

    with pytest.raises(ConditionTableError):
        load_shear_conditions(path)


def test_load_shear_conditions_raises_when_file_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_shear_conditions(tmp_path / "missing.xlsx")
