"""フェーズ2: 壁面摩擦試験ワークフロー(FR-17)。"""

from __future__ import annotations

import logging
import math
import shutil
from pathlib import Path

from poscap_calibration.models import WallFrictionCondition
from poscap_calibration.project_layout import (
    WALL_FRICTION_WORKBOOK_FILENAME,
    ProjectLayout,
)
from poscap_calibration.wall_friction_analysis_excel import (
    read_wall_friction_conditions,
    write_settings_and_recalculate,
)

DEFAULT_TEMPLATE_PATH = Path("templates/excel/wall_friction_analysis_template.xlsx")
LOG_FILENAME = "step1_wall_friction_analysis.log"


def create_wall_friction_analysis_workbook(
    project_id: str,
    peak_ratio: float,
    experiment_steady_slope: float,
    *,
    project_root: str | Path = "projects",
    template_path: str | Path = DEFAULT_TEMPLATE_PATH,
    workbook_filename: str = WALL_FRICTION_WORKBOOK_FILENAME,
) -> tuple[Path, list[WallFrictionCondition]]:
    """壁面摩擦試験の条件表を作成し、Excelのパスと条件1〜3の摩擦係数を返す(手順書1.2.4)。"""
    if not project_id.strip():
        raise ValueError("project_idは空にできません。")
    _validate_positive("peak_ratio", peak_ratio)
    _validate_positive("experiment_steady_slope", experiment_steady_slope)

    template = Path(template_path)
    if not template.is_file():
        raise FileNotFoundError(f"Excelテンプレートが見つかりません: {template}")

    test_directory = ProjectLayout(
        project_id, Path(project_root)
    ).wall_friction_test_directory
    test_directory.mkdir(parents=True, exist_ok=True)
    workbook_path = test_directory / workbook_filename
    shutil.copy2(template, workbook_path)

    write_settings_and_recalculate(workbook_path, peak_ratio, experiment_steady_slope)
    conditions = read_wall_friction_conditions(workbook_path)

    _log_result(
        test_directory / LOG_FILENAME,
        template,
        workbook_path,
        peak_ratio,
        experiment_steady_slope,
        conditions,
    )
    return workbook_path, conditions


def _validate_positive(name: str, value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name}は数値である必要があります: {value!r}")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name}は0より大きい有限値で指定してください: {value}")


def _log_result(
    log_path: Path,
    template: Path,
    workbook_path: Path,
    peak_ratio: float,
    experiment_steady_slope: float,
    conditions: list[WallFrictionCondition],
) -> None:
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    try:
        logger.info(
            "phase2 wall friction analysis: input=%s output=%s "
            "peak_ratio=%s experiment_steady_slope=%s",
            template.resolve(),
            workbook_path.resolve(),
            peak_ratio,
            experiment_steady_slope,
        )
        for condition in conditions:
            logger.info(
                "condition=%d wall_dynamic_friction=%.6f wall_static_friction=%.6f",
                condition.condition_id,
                condition.dynamic_friction,
                condition.static_friction,
            )
    finally:
        handler.close()
        logger.removeHandler(handler)
