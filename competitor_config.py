"""
竞品账号配置：从 config/config.yaml 根级 `competitors` 加载。
支持两种结构：
  - 新结构（AI 产品）：competitors[].platforms[]（无 games 层级）
  - 旧结构（游戏竞品）：competitors[].platforms[] + competitors[].games[].platforms[]
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import yaml

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def resolve_config_yaml_path() -> Optional[str]:
    env = os.environ.get("CONFIG_PATH")
    if env and os.path.exists(env):
        return env
    p = os.path.join(_PROJECT_ROOT, "config", "config.yaml")
    if os.path.exists(p):
        return p
    docker = "/app/config/config.yaml"
    if os.path.exists(docker):
        return docker
    return None


def load_config_dict() -> Dict[str, Any]:
    path = resolve_config_yaml_path()
    if not path:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        print(f"⚠️ 读取 config.yaml 失败: {exc}")
        return {}


def get_competitors_from_config_yaml() -> List[Dict[str, Any]]:
    """从 config.yaml 读取根级 competitors。"""
    cfg = load_config_dict()
    raw = cfg.get("competitors")
    if not isinstance(raw, list):
        return []
    return [x for x in raw if isinstance(x, dict)]
