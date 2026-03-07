"""
模板注册表 — 统一入口
"""

from templates.base import BaseTemplate

REGISTRY: dict[str, type[BaseTemplate]] = {}


def register(name: str):
    """类装饰器：将模板类注册到 REGISTRY"""
    def decorator(cls: type[BaseTemplate]):
        REGISTRY[name] = cls
        return cls
    return decorator


def get_template(name: str) -> BaseTemplate:
    """按名称获取模板实例"""
    if name not in REGISTRY:
        available = ", ".join(REGISTRY) or "(无)"
        raise ValueError(f"未知模板: {name}，可用: {available}")
    return REGISTRY[name]()


# ── 自动注册所有内置模板 ──
from templates.minimal_insight import MinimalInsightTemplate  # noqa: E402

REGISTRY["minimal-insight"] = MinimalInsightTemplate
