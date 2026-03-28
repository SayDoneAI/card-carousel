"""
sketch-card 模板包
"""

import os
import yaml

from templates.base import BaseTemplate
from templates import register


@register("sketch-card")
class SketchCardTemplate(BaseTemplate):
    name = "sketch-card"

    def get_default_config(self) -> dict:
        defaults_path = os.path.join(os.path.dirname(__file__), "defaults.yaml")
        with open(defaults_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def get_manim_script(self) -> str:
        return "templates/sketch_card/scene.py"

    def get_scene_classes(self) -> list[str]:
        return ["Scene01_Cards"]

    def get_cover_manim_script(self) -> str | None:
        return "templates/sketch_card/cover.py"

    def get_cover_scene_class(self) -> str | None:
        return "SketchCardCover"

    def get_positionable_elements(self) -> list[dict]:
        config = self.get_default_config()
        return config.get("positionable_elements", [])
