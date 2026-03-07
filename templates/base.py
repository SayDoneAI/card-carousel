"""
模板基类 — 所有 Manim 场景模板的抽象接口
"""

from abc import ABC, abstractmethod


class BaseTemplate(ABC):
    name: str

    @abstractmethod
    def get_default_config(self) -> dict:
        """返回模板默认配置（品牌/布局/颜色等）"""
        ...

    @abstractmethod
    def get_manim_script(self) -> str:
        """返回此模板的 Manim 脚本相对路径（相对于项目根目录）"""
        ...

    @abstractmethod
    def get_scene_classes(self) -> list[str]:
        """返回 Manim 场景类名列表"""
        ...
