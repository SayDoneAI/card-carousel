"""
portrait-notebook 模板包
人像笔记本：真人照片背景 + 速写本插画 + 字幕
"""

import os
import yaml

from templates.base import BaseTemplate
from templates import register


@register("portrait-notebook")
class PortraitNotebookTemplate(BaseTemplate):
    name = "portrait-notebook"

    def get_default_config(self) -> dict:
        defaults_path = os.path.join(os.path.dirname(__file__), "defaults.yaml")
        with open(defaults_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_manim_script(self) -> str:
        return "templates/portrait_notebook/scene.py"

    def get_scene_classes(self) -> list[str]:
        return ["PortraitNotebookScene"]

    def get_positionable_elements(self) -> list[dict]:
        """返回可定位元素的元数据"""
        defaults = self.get_default_config()
        return defaults.get("positionable_elements", [])
