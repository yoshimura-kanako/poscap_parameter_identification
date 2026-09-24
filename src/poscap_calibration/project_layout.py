"""プロジェクトのフォルダ構成を一元管理する。

::

    projects/{project_id}/
    ├─ shear_test/          せん断試験(粒子発生・充填・プリせん断・本せん断)
    ├─ saor_test/           安息角試験
    ├─ wall_friction_test/  壁面摩擦試験(フェーズ2)
    └─ rsm/{phase}/{test}/  応答曲面作成結果
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROJECT_ROOT = Path("projects")
DEFAULT_PROJECT_ID = "0"

SHEAR_TEST_DIRECTORY_NAME = "shear_test"
SAOR_TEST_DIRECTORY_NAME = "saor_test"
WALL_FRICTION_TEST_DIRECTORY_NAME = "wall_friction_test"
RSM_DIRECTORY_NAME = "rsm"
RSM_OUTPUTS_DIRECTORY_NAME = "outputs"
DEFAULT_RSM_PHASE = "phase1"
RSM_SHEAR_NAME = "shear"
RSM_SAOR_NAME = "saor"
RSM_COMBINED_NAME = "combined"
RSM_MODEL_EQUATION_FILENAME = "cubic_poly_RSM_model_equation.txt"
#: どちらの試験の成果物かファイル名だけで判別できるよう付与する接頭辞。
RSM_OUTPUT_PREFIXES = {RSM_SHEAR_NAME: "Shear_", RSM_SAOR_NAME: "SAOR_"}

SHEAR_WORKBOOK_FILENAME = "shear_analysis.xlsx"
SAOR_WORKBOOK_FILENAME = "saor_analysis.xlsx"
WALL_FRICTION_WORKBOOK_FILENAME = "wall_friction_analysis.xlsx"
SHEAR_RESPONSE_SURFACE_CSV_FILENAME = "shear_response_surface_data.csv"
SAOR_RESPONSE_SURFACE_CSV_FILENAME = "saor_response_surface_data.csv"


def condition_directory_name(condition_id: int) -> str:
    """``condition_01``形式のフォルダ名を返す。"""
    return f"condition_{condition_id:02d}"


@dataclass(frozen=True)
class ProjectLayout:
    """1プロジェクト分のフォルダ構成。"""

    project_id: str = DEFAULT_PROJECT_ID
    project_root: Path = DEFAULT_PROJECT_ROOT

    @property
    def project_directory(self) -> Path:
        return Path(self.project_root) / self.project_id

    # --- せん断試験 -------------------------------------------------
    @property
    def shear_test_directory(self) -> Path:
        return self.project_directory / SHEAR_TEST_DIRECTORY_NAME

    @property
    def shear_workbook(self) -> Path:
        return self.shear_test_directory / SHEAR_WORKBOOK_FILENAME

    @property
    def shear_response_surface_csv(self) -> Path:
        return self.shear_test_directory / SHEAR_RESPONSE_SURFACE_CSV_FILENAME

    @property
    def particle_generation_directory(self) -> Path:
        """粒子発生。粒度分布ごとに1回実行し、9条件で共通利用する。"""
        return self.shear_test_directory / "particle_generation"

    @property
    def particle_generation_work(self) -> Path:
        return self.particle_generation_directory / "work"

    @property
    def particle_generation_results(self) -> Path:
        return self.particle_generation_directory / "results"

    @property
    def filling_input_directory(self) -> Path:
        """充填インプット(Particle Custom Inlet設定済みプロジェクト)。9条件で共通。"""
        return self.shear_test_directory / "filling_input"

    def shear_condition_directory(self, condition_id: int) -> Path:
        return self.shear_test_directory / condition_directory_name(condition_id)

    # --- 安息角試験 -------------------------------------------------
    @property
    def saor_test_directory(self) -> Path:
        return self.project_directory / SAOR_TEST_DIRECTORY_NAME

    @property
    def saor_workbook(self) -> Path:
        return self.saor_test_directory / SAOR_WORKBOOK_FILENAME

    @property
    def saor_response_surface_csv(self) -> Path:
        return self.saor_test_directory / SAOR_RESPONSE_SURFACE_CSV_FILENAME

    def saor_condition_directory(self, condition_id: int) -> Path:
        return self.saor_test_directory / condition_directory_name(condition_id)

    # --- 壁面摩擦試験(フェーズ2) -----------------------------------
    @property
    def wall_friction_test_directory(self) -> Path:
        return self.project_directory / WALL_FRICTION_TEST_DIRECTORY_NAME

    @property
    def wall_friction_workbook(self) -> Path:
        return self.wall_friction_test_directory / WALL_FRICTION_WORKBOOK_FILENAME

    @property
    def wall_friction_fill_directory(self) -> Path:
        """壁面摩擦3条件で共通利用する充填シミュレーションの保存先。"""
        return self.wall_friction_test_directory / "fill"

    def wall_friction_condition_directory(self, condition_id: int) -> Path:
        return self.wall_friction_test_directory / condition_directory_name(condition_id)

    # --- 応答曲面(RSM) ---------------------------------------------
    def rsm_output_directory(
        self, test_name: str, *, phase: str = DEFAULT_RSM_PHASE
    ) -> Path:
        """``rsm/phase1/shear/outputs``形式のRSM出力先を返す。"""
        return (
            self.project_directory
            / RSM_DIRECTORY_NAME
            / phase
            / test_name
            / RSM_OUTPUTS_DIRECTORY_NAME
        )

    def rsm_model_equation(
        self, test_name: str, *, phase: str = DEFAULT_RSM_PHASE
    ) -> Path:
        """RSMが出力したモデル式ファイル(接頭辞付き)のパスを返す。"""
        try:
            prefix = RSM_OUTPUT_PREFIXES[test_name]
        except KeyError:
            raise KeyError(
                f"未知の試験名: {test_name}。"
                f"利用可能: {sorted(RSM_OUTPUT_PREFIXES)}"
            ) from None
        return self.rsm_output_directory(test_name, phase=phase) / (
            prefix + RSM_MODEL_EQUATION_FILENAME
        )
