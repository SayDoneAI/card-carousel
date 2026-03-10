"""
外部工具适配器图片引擎 — 封装 _generate_with_tool 调用
支持 gemini、doubao 等通过外部脚本生成的引擎
"""

import subprocess
import sys

from . import ImageEngine, ImageResult


class ToolAdapterEngine(ImageEngine):
    def __init__(self, engine: str, model: str | None, gen_tool: str):
        self.engine = engine
        self.model = model
        self.gen_tool = gen_tool

    def generate(self, prompt: str, output_path: str,
                 aspect_ratio: str = "1:1") -> ImageResult:
        # output_path 在此引擎里不直接使用（工具自行决定文件名）
        # 调用约定与原 _generate_with_tool 完全一致
        import os
        cache_dir = str(os.path.dirname(output_path))
        safe_name = str(os.path.basename(output_path).rsplit(".", 1)[0])

        cmd = [
            sys.executable, self.gen_tool,
            prompt,
            "--aspect_ratio", aspect_ratio,
            "-o", cache_dir,
            "--filename", safe_name,
            "--engine", self.engine,
        ]
        if self.model:
            cmd.extend(["--model", self.model])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return ImageResult(success=True, path=output_path)
        return ImageResult(
            success=False,
            error=result.stderr.strip() or "工具返回非零退出码",
        )
