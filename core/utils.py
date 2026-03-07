"""
工具函数 — 供整个项目共用
"""

import os
import re
import subprocess
from datetime import datetime


def get_duration(path):
    """获取音视频文件时长（秒）"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def sanitize_filename(name):
    """将关键词转为安全的文件名"""
    return re.sub(r'[^\w\-]', '_', name.strip().lower())


def _output_name(cfg, speed=1.0):
    """生成输出文件名"""
    date_str = datetime.now().strftime("%Y%m%d")
    base = f"{cfg['title']}_{date_str}"
    if speed != 1.0:
        base += f"_{speed}x"
    return f"{base}.mp4"
