"""
图片引擎抽象接口 + 工厂方法
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ImageResult:
    success: bool
    path: str = ""
    error: str = ""


class ImageEngine(ABC):
    @abstractmethod
    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "1:1",
                 input_image: str = "") -> ImageResult: ...


def get_image_engine(illus_cfg: dict, gen_tool: str = "") -> ImageEngine:
    """工厂方法，根据 engine 配置返回对应引擎实例"""
    engine = illus_cfg.get("engine", "gemini")
    model = illus_cfg.get("model", None)

    if engine in ("gemini", "doubao"):
        from .tool_adapter import ToolAdapterEngine
        return ToolAdapterEngine(engine=engine, model=model, gen_tool=gen_tool)
    elif gen_tool:
        from .tool_adapter import ToolAdapterEngine
        return ToolAdapterEngine(engine=engine, model=model, gen_tool=gen_tool)
    else:
        raise ValueError(f"未知图片引擎: {engine!r}，可用值: gemini, doubao")
