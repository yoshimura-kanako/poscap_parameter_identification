"""フェーズ1: 安息角シミュレーションワークフロー(FR-11)。

解析Excelから条件パラメータを読み取り、SAORテンプレートを条件別フォルダへ複製して
粒度分布と粉体パラメータを設定し、シミュレーションを実行する。
ポスト処理と解析Excelへの結果書込みは対象外。
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poscap_calibration.models import ShearCondition
from poscap_calibration.particle_distribution import load_particle_distribution
from poscap_calibration.project_layout import SAOR_WORKBOOK_FILENAME
from poscap_calibration.rocky.client import RockyClient
from poscap_calibration.rocky.simulation_runner import (
    copy_rocky_project,
    verify_powder_parameters,
)
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    write_status,
)
from poscap_calibration.workflows.saor_post_process import (
    DEFAULT_SCRIPT_PATH,
    run_saor_post_process,
)

logger = logging.getLogger(__name__)

#: 元スクリプトの慣例に合わせ、条件フォルダ配下のResults/saor/へ出力する。
POST_PROCESS_RELATIVE_PATH = Path("Results") / "saor"


def create_saor_analysis_workbook(
    template_path: str | Path,
    saor_test_directory: str | Path,
    *,
    workbook_filename: str = SAOR_WORKBOOK_FILENAME,
) -> Path:
    """安息角解析Excelテンプレートを``saor_test``フォルダへ複製する。

    テンプレート原本は変更しない。既に複製済みの場合は上書きせず既存を返す。
    """
    template = Path(template_path)
    if not template.is_file():
        raise FileNotFoundError(f"安息角解析Excelテンプレートが見つかりません: {template}")

    directory = Path(saor_test_directory)
    directory.mkdir(parents=True, exist_ok=True)
    workbook_path = directory / workbook_filename

    if not workbook_path.exists():
        shutil.copy2(template, workbook_path)
        logger.info("saor workbook created: %s", workbook_path)

    return workbook_path


def run_saor(
    client: RockyClient,
    condition: ShearCondition,
    template_project_path: str | Path,
    distribution_csv_path: str | Path,
    output_root: str | Path,
    *,
    cgm_scale_factor: float | None = None,
    post_process: bool = True,
    post_process_output_directory: str | Path | None = None,
    post_process_script_path: str | Path = DEFAULT_SCRIPT_PATH,
    project_filename: str = "SAOR.rocky",
    log_filename: str = "saor.log",
    host: str = "127.0.0.1",
    port: int = 0,
) -> Path:
    """1条件分の安息角シミュレーションを実行し、作業用プロジェクトのパスを返す。

    テンプレート原本は開かず条件別フォルダへ複製して使用するため、
    条件を変えて繰り返し実行しても原本と他条件の結果に影響しない。
    ``cgm_scale_factor``を指定すると粒子数を調整できる(未指定ならテンプレートの値)。
    ポスト処理はRockyを再起動せず同一セッション内で実行する。
    """
    distribution = load_particle_distribution(distribution_csv_path)

    condition_directory = Path(output_root) / condition.directory_name
    project_path = condition_directory / "project" / project_filename
    log_path = condition_directory / log_filename
    post_process_directory = Path(
        post_process_output_directory
        if post_process_output_directory is not None
        else condition_directory / POST_PROCESS_RELATIVE_PATH
    )

    condition_directory.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.setLevel(logging.INFO)
    logger.addHandler(file_handler)

    status: dict[str, Any] = {
        "condition_id": condition.condition_id,
        "step": "saor",
        "status": STATUS_FAILED,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "requested_parameters": {
            "rolling_resistance": condition.rolling_resistance,
            "dynamic_friction": condition.dynamic_friction,
            "static_friction": condition.static_friction,
        },
        "template_project": str(Path(template_project_path)),
        "distribution_csv": str(Path(distribution_csv_path).resolve()),
        "distribution_point_count": len(distribution),
        "cgm_scale_factor": cgm_scale_factor,
        "post_process": post_process,
    }

    try:
        logger.info(
            "saor start: condition=%d template=%s distribution=%s",
            condition.condition_id,
            template_project_path,
            distribution_csv_path,
        )
        copy_rocky_project(template_project_path, project_path)

        client.connect(host, port)
        try:
            client.open_project(project_path)
            client.delete_results()

            client.set_particle_property("size_distribution", distribution)

            if cgm_scale_factor is not None:
                client.set_particle_property("cgm_scale_factor", cgm_scale_factor)
                logger.info("saor cgm scale factor applied: %s", cgm_scale_factor)

            applied = client.set_powder_parameters(
                condition.rolling_resistance,
                condition.dynamic_friction,
                condition.static_friction,
            )
            verify_powder_parameters(condition, applied)
            status["applied_parameters"] = applied
            logger.info("saor parameters applied: %s", applied)

            client.save_project_as(project_path)
            client.run_simulation()
            if not client.is_completed():
                raise RuntimeError(
                    f"条件{condition.condition_id}の安息角シミュレーションが正常終了しませんでした。"
                )

            # Rockyの再起動を避け、結果を保持したまま同一セッションでポスト処理する。
            if post_process:
                status["post_process_result"] = run_saor_post_process(
                    client.get_project(),
                    post_process_directory,
                    script_path=post_process_script_path,
                )
        finally:
            client.disconnect()

        status.update(
            {
                "status": STATUS_COMPLETED,
                "outputs": {
                    "project": str(project_path),
                    "log": str(log_path),
                    **(
                        {"post_process_directory": str(post_process_directory)}
                        if post_process
                        else {}
                    ),
                },
            }
        )
        logger.info(
            "saor completed: condition=%d project=%s",
            condition.condition_id,
            project_path,
        )
        return project_path

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        logger.exception("saor failed: condition=%d", condition.condition_id)
        raise
    finally:
        status["finished_at"] = datetime.now(timezone.utc).isoformat()
        write_status(condition_directory, status)
        file_handler.close()
        logger.removeHandler(file_handler)

