"""
向后兼容入口 — 实际代码在 templates/minimal_insight/scene.py

保留此文件使已有的 config.yaml (manim_script: "explainer.py") 继续工作。
"""
from templates.minimal_insight.scene import *  # noqa: F401, F403
