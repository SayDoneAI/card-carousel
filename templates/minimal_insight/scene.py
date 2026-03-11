"""极简洞见 — 竖屏白底大字卡片 + 水墨插画 + 底栏标签"""

# ruff: noqa: F403, F405, E402
from manim import *
import os
import sys
from pathlib import Path as _Path

_DIR = os.environ.get(
    "CARD_CAROUSEL_PROJECT_DIR", str(_Path(__file__).resolve().parents[2])
)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from templates.shared import GenericCardScene


# 动态生成 SceneXX_Cards 类，供 pipeline 按场景名调用
for _i in range(1, 20):
    _name = f"Scene{_i:02d}_Cards"
    globals()[_name] = type(_name, (GenericCardScene,), {"SCENE_NAME": _name})

del _i, _name
