"""Rocky操作の抽象インターフェース。

第1版はAnsys Rocky 2025 R2のみを対象とする(docs/requirements.md 5.3節)。
未確認のPyRocky APIを推測実装しないこと(docs/Rocky.md 17章)。
実装は実機での動作確認が取れた操作から追加する。
"""

from __future__ import annotations

import logging
import math
import platform
import re
import shutil
import stat
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class RockyClient(ABC):
    """PyRockyを介したRocky操作の契約を定義するインターフェース。"""

    @abstractmethod
    def connect(self, host: str, port: int) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def open_project(self, project_path: Path) -> None: ...

    @abstractmethod
    def get_project(self) -> Any: ...

    @abstractmethod
    def save_project_as(self, destination_path: Path) -> None: ...

    @abstractmethod
    def delete_results(self) -> None: ...

    @abstractmethod
    def set_particle_property(self, name: str, value: Any) -> None: ...

    @abstractmethod
    def set_powder_parameters(
        self,
        rolling_resistance: float,
        dynamic_friction: float,
        static_friction: float,
    ) -> dict[str, float]: ...

    @abstractmethod
    def set_wall_friction_parameters(
        self,
        dynamic_friction: float,
        static_friction: float,
        *,
        geometry_name: str | None = None,
        wall_material_name: str | None = None,
    ) -> dict[str, float]: ...

    @abstractmethod
    def set_custom_inlet_csv(self, csv_path: Path) -> None: ...

    @abstractmethod
    def run_simulation(self) -> None: ...

    @abstractmethod
    def is_completed(self) -> bool: ...

    @abstractmethod
    def export_user_process_particles(
        self, user_process_name: str | None, time_step: int
    ) -> Path: ...

    @abstractmethod
    def get_geometry_max_y(self, geometry_name: str, time_step: int) -> dict[str, Any]: ...

    @abstractmethod
    def get_time_plot(self, name: str) -> Path: ...

    @abstractmethod
    def get_curve(
        self, entity_name: str, curve_name: str
    ) -> tuple[list[float], list[float]]: ...

    @abstractmethod
    def get_geometry_translation_y(self, geometry_name: str) -> float: ...

    @abstractmethod
    def set_geometry_translation_y(self, geometry_name: str, value: float) -> None: ...


# 粒度分布CSVのparticle_sizeはµm単位のため、Rocky設定(SetSize, unit="m")前にm換算する。
_PARTICLE_SIZE_UM_TO_M = 1e-6

# 最終出力時刻が設定終了時刻のこの割合以上なら完走とみなす(出力間隔による端数を許容)。
_SIMULATION_COMPLETION_RATIO = 0.999

# ソルバー終了後、最終時刻がCross Plot/出力時刻リストへ反映されるまでの最大待ち時間(秒)。
_RESULTS_REFRESH_TIMEOUT_S = 300.0

#: 結果反映待ちのポーリング間隔(秒)。
_RESULTS_REFRESH_POLL_INTERVAL_S = 2.0

#: ソルバー実行中(IsSimulating)のポーリング間隔(秒)。
_SOLVER_POLL_INTERVAL_S = 5.0

#: StartSimulation直後、IsSimulating()がTrueになるまで待つ猶予(秒)。
_SOLVER_STARTUP_GRACE_S = 60.0

#: OneDriveのファイルロックと競合した際に保存を試みる回数。
_SAVE_RETRY_COUNT = 5

#: 保存リトライの間隔(秒)。OneDriveがハンドルを解放するのを待つ。
_SAVE_RETRY_INTERVAL_S = 5.0

#: 粒子ごとに取得するRockyのProperty名と単位。
_PARTICLE_PROPERTIES: dict[str, tuple[str, str | None]] = {
    "id": ("Particle ID", None),
    "x": ("Particle X-Coordinate", "m"),
    "y": ("Particle Y-Coordinate", "m"),
    "z": ("Particle Z-Coordinate", "m"),
    "size": ("Particle Size", "m"),
}

#: GeometryのTranslationを読み書きする際の単位。
_TRANSLATION_UNIT = "m"

#: GeometryのY座標Grid Functionを実際の一覧から選ぶためのパターン。
#: Geometryは粒子側の``Coordinate : Y``ではなく``Coordinate : Nodal : Y``を持つ(実機確認済み)。
_Y_COORDINATE_PATTERN = re.compile(r"^coordinate\s*:\s*(nodal\s*:\s*)?y$", re.IGNORECASE)


def _is_access_denied(error: Exception) -> bool:
    """Rocky(Pyro)から伝播した例外がアクセス拒否かを判定する。"""
    if isinstance(error, PermissionError):
        return True
    text = f"{type(error).__name__}: {error}"
    return "PermissionError" in text or "WinError 5" in text


def _clear_particle_cache(project_path: Path) -> None:
    """保存を妨げる粒子テセレーションキャッシュを削除する(Rockyが必要時に再生成する)。"""
    cache_directory = project_path.with_suffix(project_path.suffix + ".files") / "particle"
    if not cache_directory.exists():
        return

    for target in (cache_directory, *cache_directory.rglob("*")):
        try:
            target.chmod(stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            continue
    shutil.rmtree(cache_directory, ignore_errors=True)


def _is_process_running(process_id: int) -> bool:
    """指定PIDのプロセスが生存しているかを判定する(Windows)。"""
    try:
        completed = subprocess.run(  # noqa: S603,S607 - OS標準のプロセス一覧照会のみ
            ["tasklist", "/FI", f"PID eq {process_id}", "/NH"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        # 判定できない場合は「生存している」とみなし、ロックを消さない方に倒す。
        return True
    return str(process_id) in completed.stdout


def _remove_stale_project_lock(project_path: Path) -> None:
    """異常終了で残った``.rocky.lock``を削除する。

    ロックが残っているとRockyの``OpenProject``が応答を返さずハングするため、
    「同じPCで作成され、かつ記録されたプロセスが既に終了している」場合のみ取り除く。
    他プロセスが使用中のロックは削除しない。
    """
    lock_path = project_path.with_suffix(project_path.suffix + ".lock")
    if not lock_path.is_file():
        return

    try:
        lines = lock_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return

    host = lines[0].strip() if lines else ""
    if host and host.upper() != platform.node().upper():
        logger.warning("他PC(%s)が保持しているロックのため削除しません: %s", host, lock_path)
        return

    process_id: int | None = None
    for line in reversed(lines):
        if line.strip().isdigit():
            process_id = int(line.strip())
            break

    if process_id is not None and _is_process_running(process_id):
        logger.warning(
            "使用中のロックのため削除しません(PID=%s): %s", process_id, lock_path
        )
        return

    try:
        lock_path.unlink()
    except OSError:
        logger.warning("残存ロックを削除できませんでした: %s", lock_path, exc_info=True)
        return
    logger.info("異常終了で残ったロックを削除しました(PID=%s): %s", process_id, lock_path)


# pyrocky_test/scripts/SAOR_PyRocky.pyで実機動作確認済みのプロキシ設定(社内ネットワーク環境で必要)。
_PROXY_ENV_DEFAULTS = {
    "HTTP_PROXY": "http://proxy.mei.co.jp:8080",
    "HTTPS_PROXY": "http://proxy.mei.co.jp:8080",
    "NO_PROXY": "localhost,127.0.0.1,::1",
}


class PyRockyClient(RockyClient):
    """PyRocky(``ansys.rocky.core``)によるRockyClient実装。

    自動化レベルの区分は docs/Rocky.md 2.3節を参照。

    - CONFIRMED: ``connect``、``disconnect``、``open_project``、``save_project_as``、
      ``run_simulation``、``is_completed``、``set_particle_property``(粒度分布の設定)、
      ``set_powder_parameters``(転がり抵抗・摩擦係数の設定)、
      ``export_user_process_particles``(User Process単位の粒子データ取得)
      (pyrocky_test/scripts/pyrocky_launch_check.pyおよびSAOR_PyRocky.pyで実機確認済み、
      粒度分布設定はRocky実機同梱のPrePost Scripting型スタブ
      ``prepost_scripting_stubs/rocky30/plugins/api/ra_size_distribution.pyi``
      ``ra_list.pyi``で仕様確認済み。User Process単位の粒子データ取得は
      scripts/diagnose_first_20deg.pyで実機確認済み)。
    """

    def __init__(self, executable_path: str | None = None, *, headless: bool = True) -> None:
        self._executable_path = executable_path
        self._headless = headless
        self._rocky: Any = None
        self._project: Any = None
        self._study: Any = None
        self._last_simulation_result: bool | None = None
        self._results_ready: bool = False

    def connect(self, host: str, port: int) -> None:
        # host/portによる既存Rockyセッションへの接続は未確認のため、
        # 実機確認済みのlaunch_rocky(rocky_exe=...)経由の起動のみを行う(docs/Rocky.md 3.2節)。
        del host, port
        import os

        import ansys.rocky.core as pyrocky

        for key, value in _PROXY_ENV_DEFAULTS.items():
            os.environ.setdefault(key, value)

        if self._executable_path:
            self._rocky = pyrocky.launch_rocky(
                rocky_exe=self._executable_path, headless=self._headless
            )
        else:
            self._rocky = pyrocky.launch_rocky(headless=self._headless)

    def disconnect(self) -> None:
        if self._rocky is not None:
            self._rocky.close()
            self._rocky = None
            self._project = None
            self._study = None

    def open_project(self, project_path: Path) -> None:
        if self._rocky is None:
            raise RuntimeError("Rockyに接続していません。先にconnect()を呼んでください。")
        _remove_stale_project_lock(project_path)
        self._project = self._rocky.api.OpenProject(str(project_path))
        self._study = self._project.GetStudy()
        self._last_simulation_result = None
        self._results_ready = False

    def save_project_as(self, destination_path: Path) -> None:
        if self._project is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        destination_path.parent.mkdir(parents=True, exist_ok=True)

        # OneDriveがテセレーションキャッシュをクラウド化していると、Rockyが保存時に
        # 行うキャッシュ削除がWinError 5で失敗する。キャッシュを消してから数回やり直す。
        last_error: Exception | None = None
        for attempt in range(1, _SAVE_RETRY_COUNT + 1):
            try:
                self._project.SaveProject(str(destination_path))
                return
            except Exception as error:  # noqa: BLE001 - Pyro経由の例外型を限定できない
                if not _is_access_denied(error):
                    raise
                last_error = error
                logger.warning(
                    "プロジェクト保存がアクセス拒否で失敗しました(%d/%d回目): %s",
                    attempt,
                    _SAVE_RETRY_COUNT,
                    destination_path,
                )
                _clear_particle_cache(destination_path)
                time.sleep(_SAVE_RETRY_INTERVAL_S)

        raise RuntimeError(
            f"プロジェクトを保存できませんでした: {destination_path}。"
            "OneDriveの同期対象から作業フォルダを外すか、"
            "'常にこのデバイス上に保持する'を設定してください。"
        ) from last_error

    def get_project(self) -> Any:
        # Rocky同梱のポスト処理スクリプトはRAProjectを直接受け取るため公開する。
        if self._project is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        return self._project

    def delete_results(self) -> None:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        # 結果が残っているとプロパティ変更が
        # 「This operation would invalidate the results」で拒否されるため先に削除する
        # (ra_study.pyiのDeleteResultsで仕様確認済み)。
        if self._study.HasResults():
            self._study.DeleteResults()
        self._results_ready = False

    def set_particle_property(self, name: str, value: Any) -> None:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        if name == "cgm_scale_factor":
            # 粗視化倍率。粒子数は倍率の3乗に反比例する
            # (ra_particle.pyiのGet/SetCgmScaleFactorで仕様確認済み)。
            particle = next(iter(self._study.GetParticleCollection()))
            particle.SetCgmScaleFactor(float(value))
            applied = float(particle.GetCgmScaleFactor())
            if not math.isclose(applied, float(value), rel_tol=1e-9, abs_tol=1e-9):
                raise RuntimeError(
                    f"粗視化倍率が設定値と一致しません(設定={value} 読み戻し={applied})。"
                )
            return
        if name != "size_distribution":
            raise NotImplementedError(f"未対応のプロパティです: {name}")
        # RAList.New()でRASizeDistributionを追加し、SetSize/SetCumulativePercentageで
        # 値を設定する(Rocky実機同梱のPrePost Scripting型スタブ
        # ra_size_distribution.pyi / ra_list.pyiで仕様確認済み)。
        particle = next(iter(self._study.GetParticleCollection()))
        size_distribution_list = particle.GetSizeDistributionList()
        size_distribution_list.Clear()
        for size_um, cumulative_percentage in value:
            point = size_distribution_list.New()
            point.SetSize(size_um * _PARTICLE_SIZE_UM_TO_M, unit="m")
            point.SetCumulativePercentage(cumulative_percentage)

    def set_powder_parameters(
        self,
        rolling_resistance: float,
        dynamic_friction: float,
        static_friction: float,
    ) -> dict[str, float]:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        # 転がり抵抗は粒子、摩擦係数は粒子材料同士のMaterials Interactionに設定する
        # (Rocky実機同梱のPrePost Scripting型スタブ ra_particle.pyi /
        # ra_materials_interaction.pyi / ra_materials_interaction_collection.pyiで仕様確認済み)。
        particle = next(iter(self._study.GetParticleCollection()))
        particle.SetRollingResistance(rolling_resistance)

        particle_material = particle.GetMaterial()
        interaction = self._study.GetMaterialsInteractionCollection().GetMaterialsInteraction(
            particle_material, particle_material
        )
        interaction.SetDynamicFriction(dynamic_friction)
        interaction.SetStaticFriction(static_friction)

        return {
            "rolling_resistance": float(particle.GetRollingResistance()),
            "dynamic_friction": float(interaction.GetDynamicFriction()),
            "static_friction": float(interaction.GetStaticFriction()),
        }

    def set_wall_friction_parameters(
        self,
        dynamic_friction: float,
        static_friction: float,
        *,
        geometry_name: str | None = None,
        wall_material_name: str | None = None,
    ) -> dict[str, float]:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        if geometry_name is None and wall_material_name is None:
            raise ValueError("geometry_nameかwall_material_nameのいずれかを指定してください。")

        # 粒子材料と壁面材料のMaterials Interactionへ設定する
        # (ra_materials_collection.pyi / ra_wall.pyi / ra_materials_interaction.pyiで仕様確認済み)。
        particle = next(iter(self._study.GetParticleCollection()))
        particle_material = particle.GetMaterial()
        wall_material = self._resolve_wall_material(geometry_name, wall_material_name)

        interaction = self._study.GetMaterialsInteractionCollection().GetMaterialsInteraction(
            particle_material, wall_material
        )
        interaction.SetDynamicFriction(dynamic_friction)
        interaction.SetStaticFriction(static_friction)

        return {
            "wall_material": str(wall_material.GetName()),
            "dynamic_friction": float(interaction.GetDynamicFriction()),
            "static_friction": float(interaction.GetStaticFriction()),
        }

    def _resolve_wall_material(
        self, geometry_name: str | None, wall_material_name: str | None
    ) -> Any:
        material_collection = self._study.GetMaterialCollection()
        if wall_material_name is not None:
            return self._get_material_by_name(material_collection, wall_material_name)

        geometry = self._study.GetGeometry(geometry_name)
        if geometry is None:
            raise RuntimeError(f"Geometry '{geometry_name}' が見つかりません。")
        material = geometry.GetMaterial()
        # GetMaterialは材料オブジェクトまたは材料名を返し得るため、名前の場合は引き当てる。
        if isinstance(material, str):
            return self._get_material_by_name(material_collection, material)
        return material

    @staticmethod
    def _get_material_by_name(material_collection: Any, material_name: str) -> Any:
        try:
            return material_collection.GetMaterial(material_name)
        except Exception as error:  # noqa: BLE001 - リモートAPIの例外種別が確定していないため
            available = [material.GetName() for material in material_collection]
            raise RuntimeError(
                f"材料 '{material_name}' が見つかりません。利用可能な材料: {available}"
            ) from error

    def set_custom_inlet_csv(self, csv_path: Path) -> None:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        resolved_path = Path(csv_path).resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"Particle Custom Inlet CSVが見つかりません: {resolved_path}")

        # Particle Custom Inlet(RACustomInput)はInlets and Outlets配下に既存のものがあるため
        # 新規作成せず既存オブジェクトを探して使う。GetFilePathはRACustomInputのみが持つため
        # (ra_custom_input.pyiで確認済み)、呼び出せるかどうかで種別を判定する。
        custom_inputs: list[tuple[str, Any]] = []
        found_names: list[str] = []
        for item in self._study.GetInletsOutletsCollection():
            item_name = item.GetName()
            found_names.append(item_name)
            try:
                item.GetFilePath()
            except Exception:  # noqa: BLE001 - リモートAPIの例外種別が確定していないため
                continue
            custom_inputs.append((item_name, item))

        if not custom_inputs:
            raise RuntimeError(
                "Particle Custom Inletが見つかりません。"
                f"Inlets and Outlets配下の要素名一覧: {found_names}"
            )
        if len(custom_inputs) > 1:
            raise RuntimeError(
                "Particle Custom Inletが複数見つかりました: "
                f"{[name for name, _ in custom_inputs]}"
            )

        custom_inputs[0][1].SetFilePath(str(resolved_path))

    def run_simulation(self) -> None:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        # テンプレートに既存の結果が焼き込まれている場合、delete_results省略時は
        # 再シミュレーションされず古い結果が使い回されるため、明示的に破棄する。
        # skip_summaryを指定しないとGUIのSimulation Summary画面で処理が戻り、
        # ソルバーが起動しないまま完了扱いになる(ra_study.pyiのStartSimulation引数で仕様確認済み)。
        self._results_ready = False
        self._last_simulation_result = self._study.StartSimulation(
            skip_summary=True, delete_results=True
        )
        # StartSimulationはソルバーの起動だけで戻ることがあるため、
        # IsSimulating()がFalseになるまで待つ(ra_study.pyiで仕様確認済み)。
        self._wait_for_solver()
        # ソルバー終了直後はCross Plot/出力時刻リストへの反映が遅れることがあるため、
        # 最終時刻が現れるまでRefreshResultsを繰り返す。
        if self._last_simulation_result:
            self._results_ready = self._wait_for_final_results()
        else:
            self._study.RefreshResults()

    def _wait_for_solver(
        self,
        poll_interval_s: float = _SOLVER_POLL_INTERVAL_S,
        startup_grace_s: float = _SOLVER_STARTUP_GRACE_S,
    ) -> None:
        """ソルバーが停止するまで待機し、進捗をログへ出す。

        実行時間はモデル次第で数十分に及ぶため、上限は設けずソルバーの状態を基準にする。
        """
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        # 起動直後はまだIsSimulating()がFalseのことがあるため、少し待って立ち上がりを捉える。
        deadline = time.monotonic() + startup_grace_s
        while not self._study.IsSimulating() and time.monotonic() < deadline:
            time.sleep(poll_interval_s)

        last_logged = -1.0
        while self._study.IsSimulating():
            progress = self._study.GetProgress()
            if progress is not None and float(progress) - last_logged >= 0.05:
                last_logged = float(progress)
                logger.info("simulation progress: %.1f%%", last_logged * 100.0)
            time.sleep(poll_interval_s)

        logger.info("solver finished")

    def _get_last_output_time(self) -> float | None:
        """現在反映済みの最終出力時刻[s]を返す(結果が無ければNone)。"""
        if self._study is None or not self._study.HasResults():
            return None
        time_set = self._study.GetTimeSet()
        if time_set is None or len(time_set) == 0:
            return None
        return float(time_set[len(time_set) - 1])

    def _wait_for_final_results(
        self,
        timeout_s: float = _RESULTS_REFRESH_TIMEOUT_S,
        poll_interval_s: float = _RESULTS_REFRESH_POLL_INTERVAL_S,
    ) -> bool:
        """最終出力時刻が設定終了時刻へ到達するまでRefreshResultsを繰り返す。

        反映途中の状態で``time_step=-1``を解決すると途中時刻の結果を掴むため、
        終了時刻が出力時刻リストへ現れるまで待ってから結果取得へ進む。
        """
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        # ra_simulator_run.pyiのGetSimulationDurationで仕様確認済み。
        duration = float(self._study.GetSolver().GetSimulationDuration(unit="s"))
        target_time = duration * _SIMULATION_COMPLETION_RATIO
        deadline = time.monotonic() + timeout_s
        while True:
            self._study.RefreshResults()
            last_time = self._get_last_output_time()
            if last_time is not None and last_time >= target_time:
                logger.info(
                    "results ready: last_output_time=%ss duration=%ss", last_time, duration
                )
                return True
            if time.monotonic() >= deadline:
                logger.warning(
                    "results not ready within %ss: last_output_time=%s duration=%ss",
                    timeout_s,
                    last_time,
                    duration,
                )
                return False
            time.sleep(poll_interval_s)

    def is_completed(self) -> bool:
        # StartSimulationの戻り値やHasResultsだけでは、ソルバー未実行で時刻0の
        # 初期状態だけが出力された場合を完了と誤判定するため、最終出力時刻が
        # 設定終了時刻へ到達したかを確認する。
        if not self._last_simulation_result:
            return False
        if self._study is None:
            return False
        if not self._results_ready:
            self._results_ready = self._wait_for_final_results(timeout_s=0.0)
        return self._results_ready

    def _resolve_time_step(self, time_step: int) -> int:
        """負値をPythonのインデックスと同様に末尾から数えた出力時刻へ解決する。"""
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        # 末尾指定は反映遅れがあると途中時刻を指すため、終了時刻の反映を待ってから解決する。
        if time_step < 0 and self._last_simulation_result and not self._results_ready:
            self._results_ready = self._wait_for_final_results()
        if not self._study.HasResults():
            raise RuntimeError("プロジェクトにシミュレーション結果がありません。")

        time_set = self._study.GetTimeSet()
        if time_set is None or len(time_set) == 0:
            raise RuntimeError("シミュレーションの出力時刻を取得できませんでした。")

        resolved = time_step if time_step >= 0 else len(time_set) + time_step
        if not 0 <= resolved < len(time_set):
            raise ValueError(
                f"time_step={time_step}は範囲外です(出力時刻数: {len(time_set)})。"
            )
        return resolved

    def get_time_at_step(self, time_step: int) -> float:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        resolved = self._resolve_time_step(time_step)
        return float(self._study.GetTimeSet()[resolved])

    def get_geometry_max_y(self, geometry_name: str, time_step: int) -> dict[str, Any]:
        # Geometry(RAWall)はRABaseGeometry経由でRAGridProcessElementItemを継承しており、
        # GetGridFunctionNames()/GetGridFunction()を持つ(ra_wall.pyi/ra_base_geometry.pyiで確認)。
        # Y座標のGrid Function名は実際の一覧から選ぶため、名前を推測しない。
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        resolved_time_step = self._resolve_time_step(time_step)
        geometry = self._study.GetGeometry(geometry_name)
        if geometry is None:
            raise RuntimeError(f"Geometry '{geometry_name}' が見つかりません。")

        grid_function_names = list(geometry.GetGridFunctionNames())
        matches = [
            name for name in grid_function_names if _Y_COORDINATE_PATTERN.search(str(name))
        ]
        if not matches:
            raise RuntimeError(
                f"Geometry '{geometry_name}' にY座標のGrid Functionが見つかりません。"
                f"利用可能なGrid Function: {grid_function_names}"
            )

        values = list(
            geometry.GetGridFunction(matches[0]).GetArray(
                unit="m", time_step=resolved_time_step
            )
        )
        if not values:
            raise ValueError(
                f"Geometry '{geometry_name}' のY座標が取得できませんでした"
                f"(time_step={resolved_time_step})。"
            )

        return {
            "geometry": geometry_name,
            "grid_function": matches[0],
            "time_step": resolved_time_step,
            "time_s": float(self._study.GetTimeSet()[resolved_time_step]),
            "maximum_y_m": float(max(values)),
            "unit": "m",
        }

    def export_user_process_particles(
        self, user_process_name: str | None, time_step: int
    ) -> Path:
        # Cross Plot自体はプロジェクトツリーに存在せずCSV出力APIも無いため、
        # Cross Plotが参照しているUser Process(例: First_20deg、Split)から同じ粒子データを
        # 直接取得する。User Process(RAUserProcess)はRAGridProcessElementItemを継承し
        # GetGridFunction()を持つため、その工程に含まれる粒子だけが得られる
        # (ra_process_element.pyiで仕様確認、実機確認済み)。
        # ``user_process_name``がNoneの場合は全粒子(study.GetParticles())を対象にする。
        if self._study is None or self._project is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        resolved_time_step = self._resolve_time_step(time_step)

        if user_process_name is None:
            source = self._study.GetParticles()
            if source is None:
                raise RuntimeError("Particlesオブジェクトを取得できませんでした。")
            label = "all_particles"
        else:
            collection = self._project.GetUserProcessCollection()
            if collection is None:
                raise RuntimeError("User Processコレクションを取得できませんでした。")

            process_names = list(collection.GetProcessNames())
            if user_process_name not in process_names:
                raise RuntimeError(
                    f"User Process '{user_process_name}' が見つかりません。"
                    f"利用可能なUser Process: {process_names}"
                )
            source = collection.GetProcess(user_process_name)
            label = user_process_name

        columns: dict[str, list[Any]] = {}
        for key, (property_name, unit) in _PARTICLE_PROPERTIES.items():
            grid_function = source.GetGridFunction(property_name)
            if grid_function is None:
                raise RuntimeError(f"Propertyを取得できませんでした: {property_name}")
            if unit is None:
                values = grid_function.GetArray(time_step=resolved_time_step)
            else:
                values = grid_function.GetArray(unit=unit, time_step=resolved_time_step)
            columns[key] = list(values)

        lengths = {key: len(values) for key, values in columns.items()}
        if len(set(lengths.values())) != 1:
            raise ValueError(f"取得したProperty配列のデータ数が一致していません: {lengths}")

        row_count = lengths["id"]
        if row_count == 0:
            raise ValueError(
                f"'{label}' の粒子数が0です(time_step={resolved_time_step})。"
            )

        export_path = (
            Path(tempfile.gettempdir())
            / f"{_sanitize_filename(label)}_t{resolved_time_step}.csv"
        )
        logger.info(
            "export particles: source=%s time_step=%s time=%ss particles=%d",
            label,
            resolved_time_step,
            float(self._study.GetTimeSet()[resolved_time_step]),
            row_count,
        )
        with export_path.open("w", encoding="utf-8", newline="") as f:
            f.write("Particle ID,Coordinate : X,Coordinate : Y,Coordinate : Z,Particle Size\n")
            for index in range(row_count):
                f.write(
                    f"{columns['id'][index]},{columns['x'][index]},{columns['y'][index]},"
                    f"{columns['z'][index]},{columns['size'][index]}\n"
                )

        return export_path

    def get_time_plot(self, name: str) -> Path:
        raise NotImplementedError("Time Plot取得は本タスクの対象外です。")

    def get_curve(self, entity_name: str, curve_name: str) -> tuple[list[float], list[float]]:
        # Time Plotが参照するEntity(例: Lid Translational Motion)はStudy要素として存在し、
        # GetCurveNames()/GetNumpyCurve()で時系列を取得できる(実機確認済み)。
        # GetNumpyCurveは(x配列, y配列)のタプルを返す。
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")

        element_names = list(self._study.GetElementNames())
        if entity_name not in element_names:
            raise RuntimeError(
                f"Entity '{entity_name}' が見つかりません。利用可能な要素: {element_names}"
            )

        element = self._study.GetElement(entity_name, raise_if_no_found=False)
        if element is None:
            raise RuntimeError(f"Entity '{entity_name}' を取得できませんでした。")

        curve_names = list(element.GetCurveNames())
        if curve_name not in curve_names:
            raise RuntimeError(
                f"Entity '{entity_name}' にCurve '{curve_name}' がありません。"
                f"利用可能なCurve: {curve_names}"
            )

        x_values, y_values = element.GetNumpyCurve(curve_name)
        return [float(value) for value in x_values], [float(value) for value in y_values]

    def get_geometry_translation_y(self, geometry_name: str) -> float:
        return float(self._get_geometry_translation(geometry_name)[1])
    def set_geometry_translation_y(self, geometry_name: str, value: float) -> None:
        # X・Zは現在値を保持し、Yのみ差し替える(ra_wall.pyiのGet/SetTranslationで仕様確認済み)。
        translation = self._get_geometry_translation(geometry_name)
        translation[1] = float(value)
        geometry = self._study.GetGeometry(geometry_name)
        geometry.SetTranslation(translation, unit=_TRANSLATION_UNIT)

    def _get_geometry_translation(self, geometry_name: str) -> list[float]:
        if self._study is None:
            raise RuntimeError("プロジェクトが開かれていません。")
        geometry = self._study.GetGeometry(geometry_name)
        if geometry is None:
            raise RuntimeError(f"Geometry '{geometry_name}' が見つかりません。")

        translation = [float(value) for value in geometry.GetTranslation(unit=_TRANSLATION_UNIT)]
        if len(translation) != 3:
            raise RuntimeError(
                f"Geometry '{geometry_name}' のTranslationが3要素ではありません: {translation}"
            )
        return translation


def _sanitize_filename(name: str) -> str:
    """User Process名等をファイル名として使える形式に変換する。"""
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in name)
