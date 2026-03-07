"""
Edge TTS 引擎实现
"""

import asyncio
from . import TTSEngine, TTSResult


class EdgeTTSEngine(TTSEngine):
    def __init__(self, voice: str = "zh-CN-YunxiNeural", speed: float = 1.0):
        self.voice = voice
        self.speed = speed

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        try:
            import edge_tts
        except ImportError:
            return TTSResult(success=False, error="缺少 edge-tts，请运行: pip install edge-tts")

        rate_str = f"{int((self.speed - 1) * 100):+d}%"

        async def _run():
            communicate = edge_tts.Communicate(text, self.voice, rate=rate_str)
            await communicate.save(output_path)

        asyncio.run(_run())
        return TTSResult(success=True)
