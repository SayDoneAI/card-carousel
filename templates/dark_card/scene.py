"""暗色卡片模板 — 标题大字 + 插画居中 + 字幕底部"""

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


class DarkCardScene(GenericCardScene):
    SCENE_NAME = "DarkCardScene"


for _i in range(1, 20):
    _name = f"Scene{_i:02d}_Cards"
    globals()[_name] = type(_name, (GenericCardScene,), {"SCENE_NAME": _name})

del _i, _name
