"""テスト用のRockyClientモック実装。実機なしでworkflowsを検証するために使用する。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from poscap_calibration.rocky.client import RockyClient


class MockRockyClient(RockyClient):
    """呼び出し履歴を記録するRockyClientのモック実装。"""

    def __init__(
        self,
        *,
        completed: bool = True,
        particles_csv: Path | None = None,
        geometry_max_y: float = 0.0123,
    ) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._completed = completed
        self._particles_csv = particles_csv
        self._geometry_max_y = geometry_max_y
        self._geometry_translation_y = 0.0
        self._project: Any = None

    def connect(self, host: str, port: int) -> None:
        self.calls.append(("connect", (host, port)))

    def disconnect(self) -> None:
        self.calls.append(("disconnect", ()))

    def open_project(self, project_path: Path) -> None:
        self.calls.append(("open_project", (project_path,)))

    def get_project(self) -> Any:
        self.calls.append(("get_project", ()))
        return self._project

    def save_project_as(self, destination_path: Path) -> None:
        self.calls.append(("save_project_as", (destination_path,)))

    def delete_results(self) -> None:
        self.calls.append(("delete_results", ()))

    def set_particle_property(self, name: str, value: Any) -> None:
        self.calls.append(("set_particle_property", (name, value)))

    def set_powder_parameters(
        self,
        rolling_resistance: float,
        dynamic_friction: float,
        static_friction: float,
    ) -> dict[str, float]:
        self.calls.append(
            ("set_powder_parameters", (rolling_resistance, dynamic_friction, static_friction))
        )
        return {
            "rolling_resistance": rolling_resistance,
            "dynamic_friction": dynamic_friction,
            "static_friction": static_friction,
        }

    def set_wall_friction_parameters(
        self,
        dynamic_friction: float,
        static_friction: float,
        *,
        geometry_name: str | None = None,
        wall_material_name: str | None = None,
    ) -> dict[str, float]:
        self.calls.append(
            (
                "set_wall_friction_parameters",
                (dynamic_friction, static_friction, geometry_name, wall_material_name),
            )
        )
        return {
            "wall_material": wall_material_name or f"material_of:{geometry_name}",
            "dynamic_friction": dynamic_friction,
            "static_friction": static_friction,
        }

    def set_custom_inlet_csv(self, csv_path: Path) -> None:
        self.calls.append(("set_custom_inlet_csv", (csv_path,)))

    def run_simulation(self) -> None:
        self.calls.append(("run_simulation", ()))

    def is_completed(self) -> bool:
        return self._completed

    def export_user_process_particles(
        self, user_process_name: str | None, time_step: int
    ) -> Path:
        self.calls.append(("export_user_process_particles", (user_process_name, time_step)))
        if self._particles_csv is None:
            raise RuntimeError("particles_csvが設定されていません。")
        return self._particles_csv

    def get_geometry_max_y(self, geometry_name: str, time_step: int) -> dict[str, Any]:
        self.calls.append(("get_geometry_max_y", (geometry_name, time_step)))
        return {
            "geometry": geometry_name,
            "grid_function": "Coordinate : Y",
            "time_step": time_step,
            "time_s": 0.75,
            "maximum_y_m": self._geometry_max_y,
            "unit": "m",
        }

    def get_time_plot(self, name: str) -> Path:
        self.calls.append(("get_time_plot", (name,)))
        raise NotImplementedError

    def get_curve(self, entity_name: str, curve_name: str) -> tuple[list[float], list[float]]:
        self.calls.append(("get_curve", (entity_name, curve_name)))
        times = [round(0.001 * index, 3) for index in range(5)]
        values = [float(index) for index in range(5)]
        return times, values

    def get_geometry_translation_y(self, geometry_name: str) -> float:
        self.calls.append(("get_geometry_translation_y", (geometry_name,)))
        return self._geometry_translation_y

    def set_geometry_translation_y(self, geometry_name: str, value: float) -> None:
        self.calls.append(("set_geometry_translation_y", (geometry_name, value)))
        self._geometry_translation_y = value
