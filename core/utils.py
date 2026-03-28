"""
工具函数 — 供整个项目共用
"""

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
        (拆分后的句子列表, 扩展后的关键词列表, 是否为续接卡片列表)
        is_continuation[i] == True 表示该卡片是某句话拆分的后半部分，
        渲染时不应推进 TTS 时间线索引。
    """
    if max_chars <= 0:
        raise ValueError(f"max_chars 必须大于 0，当前值: {max_chars}")

    split_sentences = []
    expanded_keywords = []
    is_continuation = []

    for i, sent in enumerate(sentences):
        kw = keywords[i] if i < len(keywords) else None
        if len(sent) <= max_chars:
            split_sentences.append(sent)
            expanded_keywords.append(kw)
            is_continuation.append(False)
        else:
            # 按 max_chars 切分
            first = True
            while len(sent) > max_chars:
                split_sentences.append(sent[:max_chars])
                expanded_keywords.append(kw)  # 复用同一关键词
                is_continuation.append(not first)
                first = False
                sent = sent[max_chars:]
            if sent:
                split_sentences.append(sent)
                expanded_keywords.append(kw)
                is_continuation.append(True)  # 续接片段

    return split_sentences, expanded_keywords, is_continuation


def wrap_chinese(text, max_chars=9):
    """将中文文本按固定字数换行"""
    lines = []
    while len(text) > max_chars:
        lines.append(text[:max_chars])
        text = text[max_chars:]
    if text:
        lines.append(text)
    return '\n'.join(lines)


def percent_to_manim(px, py, width, height):
    """
    百分比坐标 → Manim 坐标

    Args:
        px: X 坐标百分比 (0-100)，0% = 左边缘，100% = 右边缘
        py: Y 坐标百分比 (0-100)，0% = 顶部，100% = 底部
        width: Manim 场景宽度（frame_width）
        height: Manim 场景高度（frame_height）

    Returns:
        (manim_x, manim_y) 元组

    坐标系转换：
        - 百分比：左上角 (0%, 0%)，中心 (50%, 50%)，右下角 (100%, 100%)
        - Manim：左上角 (-w/2, h/2)，中心 (0, 0)，右下角 (w/2, -h/2)
    """
    manim_x = (px / 100 - 0.5) * width
    manim_y = (0.5 - py / 100) * height
    return manim_x, manim_y


def sanitize_positions(positions: dict) -> dict:
    """
    清洗 layout.positions 字典：过滤掉 x/y 非数值或缺失的条目。

    Args:
        positions: 原始 positions 字典，格式 { element_id: { x: float, y: float }, ... }

    Returns:
        只含合法完整 x/y 条目的新字典（x/y 均为数值且非 bool）
    """
    if not isinstance(positions, dict):
        return {}
    result = {}
    for elem_id, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        x = pos.get("x")
        y = pos.get("y")
        if (
            isinstance(x, (int, float)) and not isinstance(x, bool)
            and isinstance(y, (int, float)) and not isinstance(y, bool)
        ):
            result[elem_id] = {"x": x, "y": y}
    return result


def is_explicitly_positioned(config: dict, element_id: str) -> bool:
    """只有 layout.positions 中存在该元素且同时包含数值类型 x 和 y 才算显式定位"""
    positions = config.get("layout", {}).get("positions", {})
    if element_id not in positions:
        return False
    pos = positions[element_id]
    if not isinstance(pos, dict):
        return False
    x, y = pos.get("x"), pos.get("y")
    return (
        isinstance(x, (int, float)) and not isinstance(x, bool)
        and isinstance(y, (int, float)) and not isinstance(y, bool)
    )


def get_element_position(
    config: dict,
    element_id: str,
    frame_width: float,
    frame_height: float,
    fallback_fn=None,
):
    """三层优先级解析元素位置（百分比 → Manim 坐标）：

    Level 3（最高）: layout.positions[element_id] 存在 → 用覆盖坐标
    Level 2: positionable_elements[id].default_x/y → 用模板默认坐标
    Level 1（最低）: 无 default_x/y → 调用 fallback_fn() 或返回 None
                    （None 表示调用方应使用 next_to 等相对布局）

    向后兼容：positionable_elements 为空时调用 fallback_fn() 或返回 None。
    """
    # Level 3: layout.positions 覆盖（最高优先级）
    positions = config.get("layout", {}).get("positions", {})
    if element_id in positions and isinstance(positions[element_id], dict):
        pos = positions[element_id]
        x, y = pos.get("x"), pos.get("y")
        if x is not None and y is not None:
            return percent_to_manim(x, y, frame_width, frame_height)

    # Level 2 / Level 1: positionable_elements
    for elem in config.get("positionable_elements", []):
        if elem.get("id") != element_id:
            continue
        dx = elem.get("default_x")
        dy = elem.get("default_y")
        if dx is not None and dy is not None:
            return percent_to_manim(dx, dy, frame_width, frame_height)
        return fallback_fn() if fallback_fn is not None else None

    # 向后兼容：无 positionable_elements 时使用 fallback
    return fallback_fn() if fallback_fn is not None else None


def manim_to_percent(mx, my, width, height):
    """
    Manim 坐标 → 百分比坐标

    Args:
        mx: Manim X 坐标
        my: Manim Y 坐标
        width: Manim 场景宽度（frame_width）
        height: Manim 场景高度（frame_height）

    Returns:
        (px, py) 元组，百分比坐标 (0-100)
    """
    px = (mx / width + 0.5) * 100
    py = (0.5 - my / height) * 100
    return px, py
