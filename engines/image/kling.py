"""
Kling 图片生成引擎 — 通过 sucloud 异步 API 轮询生成
"""

import os
import time

from . import ImageEngine, ImageResult


class KlingEngine(ImageEngine):
    def __init__(
        self,
        model: str = "kling-v1",
        aspect_ratio: str = "1:1",
        poll_interval: int = 3,
        max_wait: int = 120,
    ):
        self.model = model
        self.aspect_ratio = aspect_ratio
        self.poll_interval = poll_interval
        self.max_wait = max_wait

    def generate(self, prompt: str, output_path: str) -> ImageResult:
        try:
            result_path = self._generate_kling(prompt, output_path)
            return ImageResult(success=True, path=result_path)
        except Exception as e:
            return ImageResult(success=False, error=str(e))

    def _generate_kling(self, prompt: str, output_path: str) -> str:
        import httpx

        api_key = os.environ.get("GEMINI_API_KEY")
        base_url = os.environ.get("GEMINI_BASE_URL", "https://sucloud.vip").rstrip("/")

        if not api_key:
            raise ValueError("GEMINI_API_KEY 未设置")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # 1. 创建任务
        create_url = f"{base_url}/kling/v1/images/generations"
        body = {
            "model_name": self.model,
            "prompt": prompt,
            "n": 1,
            "aspect_ratio": self.aspect_ratio,
        }

        timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
        resp = httpx.post(create_url, json=body, headers=headers, timeout=timeout, verify=False)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"kling 创建任务失败: {data.get('message', data)}")

        task_id = data["data"]["task_id"]
        print(f"    任务已提交 (task_id={task_id[:16]}...)")

        # 2. 轮询结果
        query_url = f"{base_url}/kling/v1/images/generations/{task_id}"
        start = time.time()
        while time.time() - start < self.max_wait:
            time.sleep(self.poll_interval)
            r = httpx.get(query_url, headers=headers, timeout=timeout, verify=False)
            r.raise_for_status()
            result = r.json()

            if result.get("code") != 0:
                raise RuntimeError(f"kling 查询失败: {result.get('message', result)}")

            status = result["data"]["task_status"]
            if status == "succeed":
                images = result["data"]["task_result"]["images"]
                if not images:
                    raise RuntimeError("kling 返回空图片列表")
                image_url = images[0]["url"]
                dl = httpx.get(image_url, timeout=60, verify=False)
                dl.raise_for_status()
                with open(output_path, "wb") as f:
                    f.write(dl.content)
                elapsed = time.time() - start
                print(f"    生成完成 ({elapsed:.1f}s)")
                return output_path
            elif status == "failed":
                msg = result["data"].get("task_status_msg", "未知错误")
                raise RuntimeError(f"kling 生成失败: {msg}")
            else:
                elapsed = time.time() - start
                print(f"    等待中... ({elapsed:.0f}s, {status})", end="\r")

        raise RuntimeError(f"kling 超时 ({self.max_wait}s)")
