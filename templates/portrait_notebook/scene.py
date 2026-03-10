"""人像卡片 — 真人照片背景 + AI插画 + 字幕"""

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


class PortraitNotebookScene(GenericCardScene):
    SCENE_NAME = "PortraitNotebookScene"
