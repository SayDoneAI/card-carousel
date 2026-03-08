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
    """生成输出文件名（title 经过 sanitize 防止路径穿越）"""
    date_str = datetime.now().strftime("%Y%m%d")
    safe_title = sanitize_filename(cfg["title"])
    base = f"{safe_title}_{date_str}"
    if speed != 1.0:
        base += f"_{speed}x"
    return f"{base}.mp4"


def split_long_sentences(sentences, keywords, max_chars=18):
    """
    拆分超长句子，保证 TTS 和渲染同步

    Args:
        sentences: 原始句子列表
        keywords: 对应的关键词列表
        max_chars: 每张卡片最多字数（默认 18 = 2行 × 9字/行）

    Returns:
        (拆分后的句子列表, 扩展后的关键词列表)
    """
    if max_chars <= 0:
        raise ValueError(f"max_chars 必须大于 0，当前值: {max_chars}")

    split_sentences = []
    expanded_keywords = []

    for i, sent in enumerate(sentences):
        kw = keywords[i] if i < len(keywords) else None
        if len(sent) <= max_chars:
            split_sentences.append(sent)
            expanded_keywords.append(kw)
        else:
            # 按 max_chars 切分
            while len(sent) > max_chars:
                split_sentences.append(sent[:max_chars])
                expanded_keywords.append(kw)  # 复用同一关键词
                sent = sent[max_chars:]
            if sent:
                split_sentences.append(sent)
                expanded_keywords.append(kw)

    return split_sentences, expanded_keywords


def wrap_chinese(text, max_chars=9):
    """将中文文本按固定字数换行"""
    lines = []
    while len(text) > max_chars:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        lines.append(text)
    return '\n'.join(lines)
