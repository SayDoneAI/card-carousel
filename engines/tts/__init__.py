"""
TTS 引擎抽象接口 + 工厂方法
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TTSResult:
    success: bool
    error: str = ""


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str, output_path: str) -> TTSResult: ...


def get_tts_engine(voice_cfg: dict) -> TTSEngine:
    """工厂方法，根据 provider 返回对应引擎实例"""
    provider = voice_cfg.get("provider", "volcengine")

    if provider == "volcengine":
        from .volcengine import VolcengineTTSEngine
        return VolcengineTTSEngine(
            voice_type=voice_cfg.get("voice_type", ""),
            cluster=voice_cfg.get("cluster", "volcano_tts"),
            speed_ratio=voice_cfg.get("speed", 1.0),
        )
    else:
        raise ValueError(f"未知 TTS provider: {provider!r}，可用值: volcengine")
