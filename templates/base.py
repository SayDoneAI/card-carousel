"""
模板基类 — 所有 Manim 场景模板的抽象接口
"""

from abc import ABC, abstractmethod


class BaseTemplate(ABC):
    name: str

    @property
    def description(self) -> str:
        """返回模板描述，默认从 defaults.yaml 读取。"""
        try:
            defaults = self.get_default_config() or {}
        except Exception:
            return ""
        value = defaults.get("description", "")
        return value if isinstance(value, str) else str(value)

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

    def get_cover_manim_script(self) -> str | None:
        """返回模板封面脚本相对路径；不支持封面时返回 None。"""
        return None

    def get_cover_scene_class(self) -> str | None:
        """返回模板封面 Scene 类名；不支持封面时返回 None。"""
        return None

    def get_positionable_elements(self) -> list[dict]:
        """
        返回模板可调整位置的元素元数据列表。

        每个元素字典包含：
        - id: 元素唯一标识符
        - label: 用户友好的显示名称
        - default_x: 默认 X 坐标百分比 (0-100)
        - default_y: 默认 Y 坐标百分比 (0-100)
        - min_x: X 坐标最小值百分比
        - max_x: X 坐标最大值百分比
        - min_y: Y 坐标最小值百分比
        - max_y: Y 坐标最大值百分比
        - step: 调整步长（可选，默认 1）

        坐标系统：百分比坐标，左上角 (0%, 0%)，右下角 (100%, 100%)

        Returns:
            元素元数据列表，默认返回空列表（向后兼容）
        """
        return []
