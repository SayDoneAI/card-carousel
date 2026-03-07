"""
minimal-insight 模板包
"""

import os
import yaml

from templates.base import BaseTemplate
from templates import register


@register("minimal-insight")
class MinimalInsightTemplate(BaseTemplate):
    name = "minimal-insight"

    def get_default_config(self) -> dict:
        defaults_path = os.path.join(os.path.dirname(__file__), "defaults.yaml")
        with open(defaults_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_manim_script(self) -> str:
        return "templates/minimal_insight/scene.py"

    def get_scene_classes(self) -> list[str]:
        return ["Scene01_Cards"]
