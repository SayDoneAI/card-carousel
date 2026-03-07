"""
火山引擎 TTS 实现
"""

import base64
import os
import uuid

from . import TTSEngine, TTSResult


class VolcengineTTSEngine(TTSEngine):
    def __init__(
        self,
        voice_type: str,
        cluster: str = "volcano_tts",
        speed_ratio: float = 1.0,
    ):
        self.voice_type = voice_type
        self.cluster = cluster
        self.speed_ratio = speed_ratio

    def synthesize(self, text: str, output_path: str) -> TTSResult:
        import requests

        api_key = os.environ.get("VOLC_API_KEY", "")
        if not api_key:
            return TTSResult(success=False, error="缺少 VOLC_API_KEY 环境变量")

        payload = {
            "app": {"cluster": self.cluster},
            "user": {"uid": "card_carousel"},
            "audio": {
                "voice_type": self.voice_type,
                "encoding": "mp3",
                "speed_ratio": self.speed_ratio,
            },
            "request": {
                "reqid": uuid.uuid4().hex,
                "text": text,
                "operation": "query",
            },
        }
        headers = {"x-api-key": api_key, "Content-Type": "application/json"}
        try:
            resp = requests.post(
                "https://openspeech.bytedance.com/api/v1/tts",
                headers=headers, json=payload, timeout=120,
            )
            resp.raise_for_status()
            result = resp.json()
        except Exception as e:
            print(f"    TTS 请求失败: {e}")
            return TTSResult(success=False, error=str(e))

        if "data" in result:
            audio_bytes = base64.b64decode(result["data"])
            with open(output_path, "wb") as f:
                f.write(audio_bytes)
            return TTSResult(success=True)

        err_msg = str(result)
        print(f"    TTS API 错误: {result}")
        return TTSResult(success=False, error=err_msg)
