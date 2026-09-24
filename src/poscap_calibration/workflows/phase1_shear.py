"""フェーズ1: せん断試験1条件分のワークフロー。"""

from __future__ import annotations

import logging
import math
import shutil
from pathlib import Path

from openpyxl import load_workbook

from poscap_calibration.project_layout import ProjectLayout


def create_shear_analysis_workbook(
	project_id: str,
	peak_ratio: float,
	*,
	project_root: str | Path = "projects",
	template_path: str | Path = "templates/excel/shear_analysis_template.xlsx",
	work_filename: str = "shear_analysis_working.xlsx",
	result_filename: str = "shear_analysis.xlsx",
) -> Path:
	"""ピーク比を設定したせん断試験条件表を作成し、shear_testのパスを返す。"""
	if not project_id.strip():
		raise ValueError("project_idは空にできません。")
	if not math.isfinite(peak_ratio) or peak_ratio <= 0:
		raise ValueError("peak_ratioは0より大きい有限値で指定してください。")

	template = Path(template_path)
	shear_test_directory = ProjectLayout(project_id, Path(project_root)).shear_test_directory
	work_directory = shear_test_directory / "work"
	work_path = work_directory / work_filename
	result_path = shear_test_directory / result_filename
	log_path = shear_test_directory / "step1_shear_analysis.log"

	if not template.is_file():
		raise FileNotFoundError(f"Excelテンプレートが見つかりません: {template}")

	work_directory.mkdir(parents=True, exist_ok=True)
	shear_test_directory.mkdir(parents=True, exist_ok=True)
	shutil.copy2(template, work_path)

	workbook = load_workbook(work_path)
	try:
		if "設定・集計" not in workbook.sheetnames:
			raise ValueError("Excelに「設定・集計」シートがありません。")
		workbook["設定・集計"]["B3"] = peak_ratio
		workbook.save(work_path)
		shutil.copy2(work_path, result_path)
	finally:
		workbook.close()

	logger = logging.getLogger(__name__)
	logger.setLevel(logging.INFO)
	handler = logging.FileHandler(log_path, encoding="utf-8")
	handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
	logger.addHandler(handler)
	try:
		logger.info(
			"step1 shear analysis: input=%s output=%s peak_ratio=%s",
			template.resolve(),
			result_path.resolve(),
			peak_ratio,
		)
	finally:
		handler.close()
		logger.removeHandler(handler)

	return result_path
