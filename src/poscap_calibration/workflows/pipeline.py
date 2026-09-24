"""フェーズ0→1→2を通しで自動実行するパイプライン(docs/workflow.md 3章)。

各工程は``scripts/``配下のスクリプトを子プロセスとして起動する。理由は以下の通り。

- スクリプト側が持つ入力検証・既定値をそのまま使える(ロジックの二重化を避ける)
- Rockyが異常終了しても親プロセスは生き残り、次工程へ進むか安全に中断できる
- 標準出力/標準エラーを工程ごとのログファイルへそのまま残せる

工程の成否は``projects/{id}/pipeline/{stage}/status.json``へ保存し、
再実行時は完了済み工程を自動でスキップする(``--force``で再実行)。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from poscap_calibration.project_layout import (
    RSM_COMBINED_NAME,
    RSM_SAOR_NAME,
    RSM_SHEAR_NAME,
    ProjectLayout,
    condition_directory_name,
)
from poscap_calibration.run_session import PIPELINE_ENV_FLAG
from poscap_calibration.state.identified_parameters import (
    PHASE1,
    load_identified_parameters,
)
from poscap_calibration.state.run_journal import get_journal
from poscap_calibration.state.state_manager import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_SKIPPED,
    read_status,
    write_status,
)
from poscap_calibration.workflows.phase1_shear import create_shear_analysis_workbook

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIRECTORY = REPO_ROOT / "scripts"
PIPELINE_DIRECTORY_NAME = "pipeline"
PIPELINE_SUMMARY_FILENAME = "pipeline_summary.json"
STAGE_LOG_FILENAME = "stage.log"
#: 失敗時にstatus.jsonへ残すログ末尾の行数。
ERROR_EXCERPT_LINES = 40

DEFAULT_LOADS_KPA: tuple[float, ...] = (3.0, 5.0, 7.0)
DEFAULT_SHEAR_CONDITION_IDS: tuple[int, ...] = tuple(range(1, 10))
DEFAULT_WALL_CONDITION_IDS: tuple[int, ...] = (1, 2, 3)


class PipelineError(RuntimeError):
    """工程の失敗によりパイプラインを中断した場合に送出する。"""


@dataclass
class PipelineOptions:
    """通し実行に必要な入力値と実行設定。"""

    layout: ProjectLayout
    #: 実験ピーク比(せん断条件表と壁面摩擦条件表の両方に使う)。
    peak_ratio: float
    #: 実験定常傾き(せん断の目標値。壁面摩擦条件表にも渡す)。
    shear_target: float
    #: 実験安息角の代表値(安息角の目標値)。
    saor_target: float
    distribution_csv: Path
    shear_condition_ids: tuple[int, ...] = DEFAULT_SHEAR_CONDITION_IDS
    saor_condition_ids: tuple[int, ...] = DEFAULT_SHEAR_CONDITION_IDS
    wall_condition_ids: tuple[int, ...] = DEFAULT_WALL_CONDITION_IDS
    loads_kpa: tuple[float, ...] = DEFAULT_LOADS_KPA
    headless: bool = True
    python_executable: str = field(default_factory=lambda: sys.executable)
    scripts_directory: Path = SCRIPTS_DIRECTORY

    @property
    def project_id(self) -> str:
        return self.layout.project_id

    @property
    def project_root(self) -> Path:
        return Path(self.layout.project_root)

    @property
    def project_directory(self) -> Path:
        return self.layout.project_directory

    def project_arguments(self) -> list[str]:
        return [
            "--project-id",
            str(self.project_id),
            "--project-root",
            str(self.project_root),
        ]

    def headless_arguments(self) -> list[str]:
        return ["--headless"] if self.headless else []

    def load_arguments(self) -> list[str]:
        return ["--loads", *[f"{load:g}" for load in self.loads_kpa]]

    def identified_powder_parameters(self) -> dict[str, float]:
        """フェーズ1で同定した粉体パラメータを読み出す(未記録なら例外)。"""
        document = load_identified_parameters(self.project_directory)
        entry = (document.get("phases") or {}).get(PHASE1)
        values = (entry or {}).get("values") or {}
        missing = [
            name
            for name in ("rolling_resistance", "dynamic_friction", "static_friction")
            if name not in values
        ]
        if missing:
            raise PipelineError(
                "フェーズ1の同定値が記録されていません"
                f"(不足: {missing})。先に重ね合わせ工程(phase1_overlay)を完了させるか、"
                "`poscap record-params --phase phase1 ...`で記録してください。"
            )
        return {name: float(values[name]) for name in values}

    def powder_parameter_arguments(self) -> list[str]:
        values = self.identified_powder_parameters()
        return [
            "--rolling-resistance",
            repr(values["rolling_resistance"]),
            "--dynamic-friction",
            repr(values["dynamic_friction"]),
            "--static-friction",
            repr(values["static_friction"]),
        ]


@dataclass(frozen=True)
class Stage:
    """1工程の定義。``command``(子プロセス)か``action``(同一プロセス)のどちらかを持つ。"""

    key: str
    phase: str
    title: str
    command: Callable[[PipelineOptions], Sequence[str]] | None = None
    action: Callable[[PipelineOptions], dict[str, Any] | None] | None = None
    #: この工程が完了しているとみなすための成果物。未生成なら未完了として再実行する。
    outputs: Callable[[PipelineOptions], Sequence[Path]] = lambda options: ()
    requires_rocky: bool = False
    #: Trueなら失敗しても後続工程を続行する。
    optional: bool = False


# --- 各工程の定義 -------------------------------------------------------


def _script(options: PipelineOptions, name: str, *arguments: str) -> list[str]:
    return [
        options.python_executable,
        str(options.scripts_directory / name),
        *arguments,
    ]


def _create_shear_workbook(options: PipelineOptions) -> dict[str, Any]:
    path = create_shear_analysis_workbook(
        options.project_id,
        options.peak_ratio,
        project_root=options.project_root,
    )
    return {"workbook": str(path), "peak_ratio": options.peak_ratio}


def _particle_raw_csv(options: PipelineOptions) -> Path:
    return options.layout.particle_generation_results / "particle_generation_inlet_raw.csv"


def _particle_inlet_csv(options: PipelineOptions) -> Path:
    return options.layout.particle_generation_results / "particle_generation_inlet.csv"


def _filling_project(options: PipelineOptions) -> Path:
    return options.layout.filling_input_directory / "work" / "Filling.rocky"


STAGES: tuple[Stage, ...] = (
    Stage(
        key="phase0_shear_workbook",
        phase="phase0",
        title="せん断試験の条件表Excelを作成",
        action=_create_shear_workbook,
        outputs=lambda options: (options.layout.shear_workbook,),
    ),
    Stage(
        key="phase0_generate_particle",
        phase="phase0",
        title="粒子発生シミュレーション",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_generate_particle.py",
            "--distribution-csv",
            str(options.distribution_csv),
            "--work-project",
            str(options.layout.particle_generation_work / "Generate_Particle.rocky"),
            "--output-csv",
            str(_particle_raw_csv(options)),
            *options.headless_arguments(),
        ),
        outputs=lambda options: (_particle_raw_csv(options),),
    ),
    Stage(
        key="phase0_prepare_filling",
        phase="phase0",
        title="充填インプットファイルの作成",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_prepare_filling.py",
            "--raw-csv",
            str(_particle_raw_csv(options)),
            "--converted-csv",
            str(_particle_inlet_csv(options)),
            "--work-project",
            str(_filling_project(options)),
            *options.headless_arguments(),
        ),
        outputs=lambda options: (_particle_inlet_csv(options), _filling_project(options)),
    ),
    Stage(
        key="phase1_shear_batch",
        phase="phase1",
        title="せん断試験9条件(充填→プリせん断→本せん断)",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_all_conditions.py",
            *options.project_arguments(),
            "--condition-ids",
            *[str(value) for value in options.shear_condition_ids],
            *options.load_arguments(),
            "--filling-base-project",
            str(_filling_project(options)),
            *options.headless_arguments(),
        ),
        outputs=lambda options: (
            options.layout.shear_test_directory / "shear_batch_summary.json",
        ),
    ),
    Stage(
        key="phase1_shear_response_surface",
        phase="phase1",
        title="せん断試験の応答曲面用データ出力",
        command=lambda options: _script(
            options, "export_response_surface.py", *options.project_arguments()
        ),
        outputs=lambda options: (options.layout.shear_response_surface_csv,),
    ),
    Stage(
        key="phase1_saor",
        phase="phase1",
        title="安息角シミュレーション(ポスト処理込み)",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_saor.py",
            *options.project_arguments(),
            "--condition-ids",
            *[str(value) for value in options.saor_condition_ids],
            "--distribution-csv",
            str(options.distribution_csv),
            *options.headless_arguments(),
        ),
        outputs=lambda options: tuple(
            options.layout.saor_condition_directory(condition_id) / "status.json"
            for condition_id in options.saor_condition_ids
        ),
    ),
    Stage(
        key="phase1_saor_import_points",
        phase="phase1",
        title="安息角の測定点を解析Excelへ転記",
        command=lambda options: _script(
            options,
            "import_saor_points.py",
            *options.project_arguments(),
            "--condition-ids",
            *[str(value) for value in options.saor_condition_ids],
        ),
        outputs=lambda options: (
            options.layout.saor_test_directory / "saor_excel_summary.json",
        ),
    ),
    Stage(
        key="phase1_saor_response_surface",
        phase="phase1",
        title="安息角の応答曲面用データ出力",
        command=lambda options: _script(
            options, "export_saor_response_surface.py", *options.project_arguments()
        ),
        outputs=lambda options: (options.layout.saor_response_surface_csv,),
    ),
    Stage(
        key="phase1_rsm_shear",
        phase="phase1",
        title="せん断試験の応答曲面(3次多項式)作成",
        command=lambda options: _script(
            options, "rsm_cubic_polynomial_Shear.py", *options.project_arguments()
        ),
        outputs=lambda options: (options.layout.rsm_model_equation(RSM_SHEAR_NAME),),
    ),
    Stage(
        key="phase1_rsm_saor",
        phase="phase1",
        title="安息角の応答曲面(3次多項式)作成",
        command=lambda options: _script(
            options, "rsm_cubic_polynomial_SAOR.py", *options.project_arguments()
        ),
        outputs=lambda options: (options.layout.rsm_model_equation(RSM_SAOR_NAME),),
    ),
    Stage(
        key="phase1_overlay",
        phase="phase1",
        title="応答曲面の重ね合わせと粉体パラメータ同定",
        command=lambda options: _script(
            options,
            "overlay_targets.py",
            *options.project_arguments(),
            "--saor-target",
            repr(options.saor_target),
            "--shear-target",
            repr(options.shear_target),
            "--peak-ratio",
            repr(options.peak_ratio),
        ),
        outputs=lambda options: (
            options.layout.rsm_output_directory(RSM_COMBINED_NAME) / "overlay.png",
        ),
    ),
    Stage(
        key="phase2_workbook",
        phase="phase2",
        title="壁面摩擦試験の条件表Excelを作成",
        command=lambda options: _script(
            options,
            "create_wall_friction_workbook.py",
            *options.project_arguments(),
            "--peak-ratio",
            repr(options.peak_ratio),
            "--steady-slope",
            repr(options.shear_target),
        ),
        outputs=lambda options: (options.layout.wall_friction_workbook,),
    ),
    Stage(
        key="phase2_fill",
        phase="phase2",
        title="壁面摩擦試験の充填(3条件共通)",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_wall_friction_filling.py",
            *options.project_arguments(),
            *options.powder_parameter_arguments(),
            "--inlet-csv",
            str(_particle_inlet_csv(options)),
            *options.headless_arguments(),
        ),
        outputs=lambda options: (
            options.layout.wall_friction_fill_directory / "status.json",
        ),
    ),
    Stage(
        key="phase2_pre_shear",
        phase="phase2",
        title="壁面摩擦試験のプリせん断(9kPa)",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_wall_friction_pre_shear.py",
            *options.project_arguments(),
            "--condition-ids",
            *[str(value) for value in options.wall_condition_ids],
            *options.powder_parameter_arguments(),
            *options.headless_arguments(),
        ),
        outputs=lambda options: tuple(
            options.layout.wall_friction_test_directory
            / condition_directory_name(condition_id)
            / "pre_shear"
            / "status.json"
            for condition_id in options.wall_condition_ids
        ),
    ),
    Stage(
        key="phase2_shear",
        phase="phase2",
        title="壁面摩擦試験の本せん断(3/5/7kPa)",
        requires_rocky=True,
        command=lambda options: _script(
            options,
            "run_wall_friction_shear_test.py",
            *options.project_arguments(),
            "--condition-ids",
            *[str(value) for value in options.wall_condition_ids],
            *options.load_arguments(),
            *options.powder_parameter_arguments(),
            *options.headless_arguments(),
        ),
        outputs=lambda options: tuple(
            options.layout.wall_friction_test_directory
            / condition_directory_name(condition_id)
            / f"shear_{load:g}kpa"
            / "status.json"
            for condition_id in options.wall_condition_ids
            for load in options.loads_kpa
        ),
    ),
)

STAGE_KEYS: tuple[str, ...] = tuple(stage.key for stage in STAGES)
PHASE_KEYS: tuple[str, ...] = ("phase0", "phase1", "phase2")


# --- 実行 ---------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def select_stages(
    *,
    stage_keys: Sequence[str] | None = None,
    phases: Sequence[str] | None = None,
    start_from: str | None = None,
    stop_after: str | None = None,
) -> list[Stage]:
    """実行対象の工程を絞り込む。"""
    stages = list(STAGES)
    if phases:
        unknown = sorted(set(phases) - set(PHASE_KEYS))
        if unknown:
            raise ValueError(f"未知のフェーズです: {unknown} (利用可能: {list(PHASE_KEYS)})")
        stages = [stage for stage in stages if stage.phase in set(phases)]
    if stage_keys:
        unknown = sorted(set(stage_keys) - set(STAGE_KEYS))
        if unknown:
            raise ValueError(f"未知の工程です: {unknown} (利用可能: {list(STAGE_KEYS)})")
        stages = [stage for stage in stages if stage.key in set(stage_keys)]
    if start_from:
        keys = [stage.key for stage in stages]
        if start_from not in keys:
            raise ValueError(f"開始工程が対象に含まれていません: {start_from} (対象: {keys})")
        stages = stages[keys.index(start_from) :]
    if stop_after:
        keys = [stage.key for stage in stages]
        if stop_after not in keys:
            raise ValueError(f"終了工程が対象に含まれていません: {stop_after} (対象: {keys})")
        stages = stages[: keys.index(stop_after) + 1]
    return stages


def _stage_directory(options: PipelineOptions, stage: Stage) -> Path:
    return options.project_directory / PIPELINE_DIRECTORY_NAME / stage.key


def _outputs_exist(options: PipelineOptions, stage: Stage) -> bool:
    paths = list(stage.outputs(options))
    return all(path.exists() for path in paths)


def _is_stage_completed(options: PipelineOptions, stage: Stage) -> bool:
    directory = _stage_directory(options, stage)
    try:
        status = read_status(directory)
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    if status.get("status") != STATUS_COMPLETED:
        return False
    # 成果物が消えている場合は「完了」を信用せず作り直す。
    return _outputs_exist(options, stage)


def _read_log_excerpt(log_path: Path, lines: int = ERROR_EXCERPT_LINES) -> list[str]:
    if not log_path.is_file():
        return []
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-lines:]


def _run_command(
    command: Sequence[str], *, log_path: Path, cwd: Path
) -> int:
    """子プロセスを起動し、出力をログファイルと親のログへ同時に流す。"""
    # 子の標準出力はパイプなので既定ではcp932になり、日本語が文字化けする。
    environment = {
        **os.environ,
        PIPELINE_ENV_FLAG: "1",
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_stream:
        log_stream.write(f"$ {' '.join(command)}\n")
        log_stream.flush()
        process = subprocess.Popen(  # noqa: S603 - 実行するのは同梱スクリプトのみ
            list(command),
            cwd=str(cwd),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            line = line.rstrip("\n")
            log_stream.write(line + "\n")
            log_stream.flush()
            logger.info("%s", line)
        return process.wait()


def run_stage(
    options: PipelineOptions, stage: Stage, *, force: bool = False
) -> dict[str, Any]:
    """1工程を実行し、``status.json``の内容を返す。"""
    directory = _stage_directory(options, stage)
    directory.mkdir(parents=True, exist_ok=True)
    log_path = directory / STAGE_LOG_FILENAME

    if not force and _is_stage_completed(options, stage):
        status = {
            "stage": stage.key,
            "phase": stage.phase,
            "title": stage.title,
            "status": STATUS_SKIPPED,
            "reason": "完了済み(成果物あり)",
            "checked_at": _now(),
            "outputs": [str(path) for path in stage.outputs(options)],
        }
        logger.info("スキップ: %s (完了済み)", stage.title)
        return status

    status: dict[str, Any] = {
        "stage": stage.key,
        "phase": stage.phase,
        "title": stage.title,
        "status": STATUS_FAILED,
        "started_at": _now(),
        "requires_rocky": stage.requires_rocky,
        "log": str(log_path),
    }

    try:
        if stage.command is not None:
            command = list(stage.command(options))
            status["command"] = command
            logger.info("実行: %s", " ".join(command))
            return_code = _run_command(command, log_path=log_path, cwd=REPO_ROOT)
            status["return_code"] = return_code
            if return_code != 0:
                raise PipelineError(
                    f"{stage.title} が異常終了しました(終了コード {return_code})。ログ: {log_path}"
                )
        elif stage.action is not None:
            status["result"] = stage.action(options) or {}
        else:
            raise PipelineError(f"工程 {stage.key} に command も action も定義されていません。")

        missing = [str(path) for path in stage.outputs(options) if not path.exists()]
        if missing:
            raise PipelineError(f"{stage.title} の成果物が生成されていません: {missing}")

        status["status"] = STATUS_COMPLETED
        status["outputs"] = [str(path) for path in stage.outputs(options)]

    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
        status["error_excerpt"] = _read_log_excerpt(log_path)
        raise
    finally:
        status["finished_at"] = _now()
        write_status(directory, status)

    return status


def run_pipeline(
    options: PipelineOptions,
    *,
    stages: Sequence[Stage] | None = None,
    force: bool = False,
    stop_on_error: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """選択した工程を順に実行し、実行サマリを返す。"""
    targets = list(stages if stages is not None else STAGES)
    journal = get_journal()
    options.project_directory.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "started_at": _now(),
        "project_id": options.project_id,
        "project_directory": str(options.project_directory.resolve()),
        "inputs": {
            "peak_ratio": options.peak_ratio,
            "shear_target": options.shear_target,
            "saor_target": options.saor_target,
            "distribution_csv": str(Path(options.distribution_csv).resolve()),
            "shear_condition_ids": list(options.shear_condition_ids),
            "saor_condition_ids": list(options.saor_condition_ids),
            "wall_condition_ids": list(options.wall_condition_ids),
            "loads_kpa": list(options.loads_kpa),
        },
        "stages": {},
    }

    if dry_run:
        summary["dry_run"] = True
        summary["planned_stages"] = [
            {
                "stage": stage.key,
                "phase": stage.phase,
                "title": stage.title,
                "completed": _is_stage_completed(options, stage),
            }
            for stage in targets
        ]
        return summary

    _verify_prerequisites(options, targets)

    total = len(targets)
    current_phase: str | None = None
    phase_context = None
    failed_phases: set[str] = set()
    try:
        for index, stage in enumerate(targets, start=1):
            if stage.phase != current_phase:
                if phase_context is not None:
                    phase_context.__exit__(None, None, None)
                current_phase = stage.phase
                phase_context = journal.phase(current_phase, _phase_title(current_phase))
                phase_context.__enter__()

            try:
                with journal.step(stage.key, stage.title, index=index, total=total):
                    status = run_stage(options, stage, force=force)
                summary["stages"][stage.key] = status
            except Exception as error:  # noqa: BLE001 - 工程単位で失敗を隔離する
                failed_phases.add(stage.phase)
                summary["stages"][stage.key] = {
                    "stage": stage.key,
                    "phase": stage.phase,
                    "title": stage.title,
                    "status": STATUS_FAILED,
                    "error": f"{type(error).__name__}: {error}",
                    "log": str(_stage_directory(options, stage) / STAGE_LOG_FILENAME),
                }
                if stop_on_error and not stage.optional:
                    summary["stopped_at_stage"] = stage.key
                    break
    finally:
        if phase_context is not None:
            phase_context.__exit__(None, None, None)
        for phase in sorted(failed_phases):
            journal.mark_phase(phase, STATUS_FAILED, error="1つ以上の工程が失敗しました")

    summary["finished_at"] = _now()
    summary["completed_stages"] = [
        key
        for key, status in summary["stages"].items()
        if status.get("status") in (STATUS_COMPLETED, STATUS_SKIPPED)
    ]
    summary["failed_stages"] = [
        key for key, status in summary["stages"].items() if status.get("status") == STATUS_FAILED
    ]
    summary["identified_parameters"] = load_identified_parameters(options.project_directory)
    summary["status"] = STATUS_FAILED if summary["failed_stages"] else STATUS_COMPLETED

    summary_path = options.project_directory / PIPELINE_SUMMARY_FILENAME
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    journal.record_result("pipeline_summary", str(summary_path), status=summary["status"])
    return summary


def _phase_title(phase: str) -> str:
    return {
        "phase0": "フェーズ0: 粒度分布・粒子発生",
        "phase1": "フェーズ1: 粉体特性の同定",
        "phase2": "フェーズ2: 壁面摩擦特性の同定",
    }.get(phase, phase)


def _verify_prerequisites(options: PipelineOptions, stages: Sequence[Stage]) -> None:
    """実行前に、後半で初めて気づくと痛い前提だけを確認する。"""
    missing: list[str] = []
    if not Path(options.distribution_csv).is_file():
        missing.append(f"粒度分布CSV: {options.distribution_csv}")
    if any(stage.command is not None for stage in stages) and not options.scripts_directory.is_dir():
        missing.append(f"scriptsフォルダ: {options.scripts_directory}")
    if missing:
        raise PipelineError("実行前チェックに失敗しました: " + " / ".join(missing))


def format_summary(summary: dict[str, Any]) -> str:
    """実行サマリを端末表示用へ整形する。"""
    lines = ["=" * 72, f"パイプライン結果: {summary.get('status', '-')}", "=" * 72]
    for key, status in summary.get("stages", {}).items():
        mark = {
            STATUS_COMPLETED: "完了",
            STATUS_SKIPPED: "スキップ",
            STATUS_FAILED: "失敗",
        }.get(status.get("status"), status.get("status"))
        lines.append(f"  [{mark:^6}] {status.get('title', key)}")
        if status.get("status") == STATUS_FAILED:
            lines.append(f"           エラー: {status.get('error')}")
            lines.append(f"           ログ  : {status.get('log')}")

    values = (
        (summary.get("identified_parameters") or {}).get("phases", {}).get(PHASE1, {}).get("values")
    )
    lines.append("")
    if values:
        lines.append("同定値(フェーズ1 粉体パラメータ):")
        for name, value in values.items():
            lines.append(f"    {name} = {value}")
    else:
        lines.append("同定値(フェーズ1): 未記録")
    lines.append("")
    lines.append(f"詳細: poscap status --project-id {summary.get('project_id')} --verbose")
    lines.append(f"失敗のみ: poscap errors --project-id {summary.get('project_id')}")
    return "\n".join(lines)
