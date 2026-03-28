"""
dark-card 模板包
暗色卡片：大标题 + 插画居中 + 字幕底部
"""

import os
import yaml

from templates.base import BaseTemplate
from templates import register


@register("dark-card")
class DarkCardTemplate(BaseTemplate):
    name = "dark-card"

    def get_default_config(self) -> dict:
        defaults_path = os.path.join(os.path.dirname(__file__), "defaults.yaml")
        with open(defaults_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_manim_script(self) -> str:
        return "templates/dark_card/scene.py"

    def get_scene_classes(self) -> list[str]:
        return ["DarkCardScene"]

    def get_positionable_elements(self) -> list[dict]:
        defaults = self.get_default_config()
        return defaults.get("positionable_elements", [])
