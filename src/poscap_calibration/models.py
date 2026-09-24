"""条件表・実行状態・Particle Custom Inlet等の共通データモデルを定義する。"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ShearCondition:
    """せん断試験1条件分の粉体パラメータ(docs/Rocky.md 7.2節)。"""

    condition_id: int
    rolling_resistance: float
    dynamic_friction: float
    static_friction: float

    def __post_init__(self) -> None:
        if self.condition_id <= 0:
            raise ValueError(f"condition_idは1以上である必要があります: {self.condition_id}")
        for field_name in ("rolling_resistance", "dynamic_friction", "static_friction"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name}は数値である必要があります: {value!r}")
            if not math.isfinite(value):
                raise ValueError(f"{field_name}は有限値である必要があります: {value}")
            if value < 0:
                raise ValueError(f"{field_name}は負にできません: {value}")

    @property
    def directory_name(self) -> str:
        """``condition_01``形式のフォルダ名(docs/Rocky.md 7.6節)。"""
        return f"condition_{self.condition_id:02d}"


@dataclass(frozen=True)
class WallFrictionCondition:
    """壁面摩擦試験1条件分の壁面パラメータ(FR-16)。"""

    condition_id: int
    dynamic_friction: float
    static_friction: float

    def __post_init__(self) -> None:
        if self.condition_id <= 0:
            raise ValueError(f"condition_idは1以上である必要があります: {self.condition_id}")
        for field_name in ("dynamic_friction", "static_friction"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(f"{field_name}は数値である必要があります: {value!r}")
            if not math.isfinite(value):
                raise ValueError(f"{field_name}は有限値である必要があります: {value}")
            if value < 0:
                raise ValueError(f"{field_name}は負にできません: {value}")

    @property
    def directory_name(self) -> str:
        return f"condition_{self.condition_id:02d}"
