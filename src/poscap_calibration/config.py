"""YAML設定の読込みと検証(FR-01)。数値条件は本モジュール経由でのみ参照する(NFR-04)。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: Rockyオブジェクト名設定(docs/Rocky.md 15章)。コードへ直書きしない。
ROCKY_OBJECTS_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "rocky_2025r2.yaml"
)

SHEAR_SECTION = "shear"
WALL_SECTION = "wall"


class ConfigError(RuntimeError):
    """設定ファイルの読込み・参照に失敗した場合に送出する例外。"""


@lru_cache(maxsize=None)
def load_rocky_config(config_path: str | Path = ROCKY_OBJECTS_CONFIG_PATH) -> dict[str, Any]:
    """Rockyオブジェクト名設定を読み込む。"""
    path = Path(config_path)
    if not path.is_file():
        raise ConfigError(f"Rocky設定ファイルが見つかりません: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"Rocky設定ファイルの形式が不正です: {path}")
    return data


def get_object_name(
    section: str, key: str, *, config_path: str | Path = ROCKY_OBJECTS_CONFIG_PATH
) -> str | None:
    """``objects.<section>.<key>``のオブジェクト名を取得する。"""
    return _lookup("objects", section, key, config_path)


def get_template_path(
    section: str, key: str, *, config_path: str | Path = ROCKY_OBJECTS_CONFIG_PATH
) -> Path:
    """``templates.<section>.<key>``のテンプレートパスをリポジトリ基点で解決する。"""
    value = _lookup("templates", section, key, config_path)
    if value is None:
        raise ConfigError(f"templates.{section}.{key}が未設定です: {config_path}")
    path = Path(value)
    if not path.is_absolute():
        path = Path(config_path).resolve().parents[1] / path
    return path


def _lookup(
    group: str, section: str, key: str, config_path: str | Path
) -> Any:
    config = load_rocky_config(config_path)
    try:
        section_data = config[group][section]
    except (KeyError, TypeError):
        available = list(config.get(group, {}) or {})
        raise ConfigError(
            f"{group}.{section}が設定ファイルにありません: {config_path}。"
            f"利用可能なセクション: {available}"
        ) from None
    if key not in section_data:
        raise ConfigError(
            f"{group}.{section}.{key}が設定ファイルにありません: {config_path}。"
            f"利用可能なキー: {sorted(section_data)}"
        )
    return section_data[key]
