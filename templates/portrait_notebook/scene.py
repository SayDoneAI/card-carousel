"""
人像笔记本口播视频 — Manim 渲染脚本（portrait-notebook 模板）
竖屏 1080x1920（9:16）：真人照片背景 + 速写本插画 + 字幕

布局 (从上到下, 坐标系原点在画面中心, frame_height=16.0):
  ┌─────────────────────────────────┐  y=+8.0 (顶部)
  │     人像照片（顶部约35%）          │  图片底边约 y=+2.8
  │     固定不动                      │
  ├─────────────────────────────────┤
  │  🟠 橙红色大标题（brand.topic）    │  y ≈ +2.2，大字，粗体
  ├─────────────────────────────────┤
  │  ┌──────────────────────────┐   │
  │  │  笔记本容器                 │  y ≈ 0.0，占画面中部
  │  │  米白圆角矩形               │  宽约 7.5，高约 5.5
  │  │  左侧螺旋装订线（小圆圈竖排）  │
  │  │  插画在纸张内部              │
  │  └──────────────────────────┘   │
  │                                 │
  │  白色字幕（当前句）               │  y ≈ -4.2，TTS同步切换
  │  橙色副标题（brand.subtitle）    │  y ≈ -4.9，固定不动
  │                                 │
  └─────────────────────────────────┘  y=-8.0 (底部)
"""

from manim import *
import json
import os
import sys

import numpy as np
import yaml
from PIL import Image as PILImage

# 竖屏配置 1080x1920 (9:16)
config.pixel_width = 1080
config.pixel_height = 1920
config.frame_width = 9.0
config.frame_height = 16.0
config.background_color = "#000000"  # 默认黑色，construct 中会从 cfg 覆盖

# ── 路径 ──
# CARD_CAROUSEL_PROJECT_DIR 由 step_render() 注入，指向项目根目录
# 回退到项目根目录（__file__ 的上两级），兼容直接 manim 调用
from pathlib import Path as _Path
_DIR = os.environ.get("CARD_CAROUSEL_PROJECT_DIR", str(_Path(__file__).resolve().parents[2]))

# 支持通过环境变量直接注入音频/timing路径（新模板模式），回退到 Manim 默认目录
# Manim 用脚本文件名 "scene" 作子目录名
_DEFAULT_MEDIA = os.path.join(_DIR, "media", "videos", "scene")
AUDIO_DIR = os.environ.get("CARD_CAROUSEL_AUDIO_DIR", os.path.join(_DEFAULT_MEDIA, "audio"))
TIMING_FILE = os.environ.get("CARD_CAROUSEL_TIMING_FILE", os.path.join(_DEFAULT_MEDIA, "_timing.json"))
ASSETS_DIR = os.path.join(_DIR, "assets", "illustrations")


def _audio(name):
    p = os.path.join(AUDIO_DIR, f"{name}.mp3")
    return p if os.path.exists(p) else None


def _load_timing(scene_name):
    try:
        with open(TIMING_FILE) as f:
            data = json.load(f)
        entry = data.get(scene_name, 30)
        if isinstance(entry, dict):
            return entry.get("total", 30), entry.get("sentences", [])
        return entry, []
    except FileNotFoundError:
        return 30, []


def _load_config():
    """复用 core.config.load_config 确保模板合并逻辑一致"""
    project_root = str(_Path(__file__).resolve().parents[2])
    default_config = os.path.join(project_root, "config.yaml")
    config_path = os.environ.get("CARD_CAROUSEL_CONFIG_PATH", default_config)

    # 确保项目根在 sys.path，使 core 包可导入
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from core.config import load_config
    return load_config(config_path)


def _get_colors(cfg):
    """从 config 读取颜色配置，回退到默认值"""
    colors = cfg.get("layout", {}).get("colors", {})
    return {
        "bg": colors.get("bg", "#000000"),
        "text": colors.get("text", "#FFFFFF"),
        "accent": colors.get("accent", "#FF6B35"),
        "subtitle": colors.get("subtitle", "#FF6B35"),
        "notebook_bg": colors.get("notebook_bg", "#F5F0E8"),
        "notebook_spiral": colors.get("notebook_spiral", "#888888"),
    }


def _get_font(cfg):
    return cfg.get("layout", {}).get("font", "PingFang SC")


def _get_wrap_chars(cfg):
    return cfg.get("layout", {}).get("wrap_chars", 12)


def _get_illustration_size(cfg):
    return cfg.get("layout", {}).get("illustration_size", 5.0)


def _get_portrait_image(cfg):
    """获取人像照片路径（相对于项目根目录）"""
    rel_path = cfg.get("layout", {}).get("portrait_image", "assets/huangfu.png")
    return os.path.join(_DIR, rel_path)


class _Timeline:
    """音频时间线管理器"""

    def __init__(self, scene_name):
        self.total, self.durs = _load_timing(scene_name)
        self.idx = 0
        self.elapsed = 0

    def sync(self, scene, animation_time=0):
        self.elapsed += animation_time
        if self.idx < len(self.durs):
            wait = self.durs[self.idx] - animation_time
            if wait > 0.1:
                scene.wait(wait)
                self.elapsed += wait
            self.idx += 1
        else:
            scene.wait(1.0)
            self.elapsed += 1.0

    def remaining(self, buffer=1.0):
        remaining_dur = sum(self.durs[self.idx:])
        return max(remaining_dur + buffer, 1.0)


def _wrap_chinese(text, max_chars=12):
    """将中文文本按固定字数换行"""
    from core.utils import wrap_chinese
    return wrap_chinese(text, max_chars)


_BG_CACHE = {}


def _remove_bg(path, threshold=220):
    """将近白色背景转为透明，让插画融入米白笔记本"""
    if path in _BG_CACHE:
        return _BG_CACHE[path]

    out_path = path.rsplit('.', 1)[0] + '_nobg.png'
    if os.path.exists(out_path):
        _BG_CACHE[path] = out_path
        return out_path

    img = PILImage.open(path).convert("RGBA")
    data = np.array(img)

    # 检测角落亮度，深色背景跳过
    corners = [data[0, 0], data[0, -1], data[-1, 0], data[-1, -1]]
    avg_brightness = np.mean([np.mean(c[:3]) for c in corners])
    if avg_brightness < 128:
        _BG_CACHE[path] = path
        return path

    # 近白色像素设为透明
    mask = (
        (data[:, :, 0] > threshold)
        & (data[:, :, 1] > threshold)
        & (data[:, :, 2] > threshold)
    )
    data[mask] = [255, 255, 255, 0]

    PILImage.fromarray(data).save(out_path, 'PNG')
    _BG_CACHE[path] = out_path
    return out_path


def _load_illustration(keyword):
    from core.utils import sanitize_filename
    safe_name = sanitize_filename(keyword)
    for ext in (".png", ".jpg", ".jpeg"):
        path = os.path.join(ASSETS_DIR, f"{safe_name}{ext}")
        if os.path.exists(path):
            return _remove_bg(path)
    return None


def _build_portrait(cfg):
    """加载人像照片，宽度充满屏幕，固定在顶部约35%区域"""
    portrait_path = _get_portrait_image(cfg)
    if not os.path.exists(portrait_path):
        # 无图时用占位矩形
        placeholder = Rectangle(
            width=9.0, height=5.6,
            fill_color="#1A1A1A", fill_opacity=1,
            stroke_width=0,
        )
        placeholder.move_to(UP * (8.0 - 5.6 / 2))
        return placeholder

    portrait = ImageMobject(portrait_path)
    # 宽度充满屏幕（frame_width = 9.0）
    portrait.scale_to_fit_width(9.0)
    # 顶边对齐画面顶部
    portrait.move_to(UP * (8.0 - portrait.height / 2))
    return portrait


def _build_topic(cfg, colors, font):
    """构建橙红色大标题（brand.topic），固定在人像下方"""
    brand_cfg = cfg.get("brand", {})
    topic = brand_cfg.get("topic", "")
    if not topic:
        return VGroup()
    topic_text = Text(
        topic,
        font=font,
        font_size=44,
        color=colors["accent"],
        weight=BOLD,
    )
    # 水平居中，Y 坐标由 construct 根据人像实际高度动态设置
    topic_text.set_x(0)
    return topic_text


def _build_subtitle(cfg, colors, font):
    """构建橙色副标题（brand.subtitle），固定在字幕下方"""
    brand_cfg = cfg.get("brand", {})
    subtitle_text = brand_cfg.get("subtitle", "")
    if not subtitle_text:
        return VGroup()
    subtitle = Text(
        subtitle_text,
        font=font,
        font_size=28,
        color=colors["subtitle"],
    )
    subtitle.set_x(0)
    return subtitle


def _build_notebook(colors):
    """构建笔记本容器：米白圆角矩形 + 左侧螺旋装订线（返回 VGroup）"""
    notebook_width = 7.5
    notebook_height = 5.5
    spiral_color = colors["notebook_spiral"]
    notebook_bg = colors["notebook_bg"]

    # 圆角矩形（米白色笔记本纸）
    notebook_rect = RoundedRectangle(
        width=notebook_width,
        height=notebook_height,
        corner_radius=0.25,
        fill_color=notebook_bg,
        fill_opacity=1,
        stroke_color=notebook_bg,
        stroke_width=1,
    )

    # 左侧螺旋装订线：8个小圆圈竖排
    spiral_circles = VGroup()
    spiral_x = notebook_rect.get_left()[0] + 0.15  # 笔记本左边缘内侧
    num_spirals = 8
    spiral_top_y = notebook_rect.get_top()[1] - 0.55
    spiral_spacing = (notebook_height - 1.1) / (num_spirals - 1)
    for i in range(num_spirals):
        y_pos = spiral_top_y - i * spiral_spacing
        circle = Circle(radius=0.15, stroke_color=spiral_color, stroke_width=2.5)
        circle.set_fill(opacity=0)
        circle.move_to([spiral_x, y_pos, 0])
        spiral_circles.add(circle)

    return VGroup(notebook_rect, spiral_circles), notebook_rect


# ── 滑动方向常量（基于 9:16 宽帧） ──
SLIDE_DISTANCE = 12


class PortraitNotebookScene(Scene):
    def construct(self):
        # ── 加载配置 ──
        cfg = _load_config()
        colors = _get_colors(cfg)
        font = _get_font(cfg)
        wrap_chars = _get_wrap_chars(cfg)
        illus_size = _get_illustration_size(cfg)

        # 应用配置中的背景色
        self.camera.background_color = colors["bg"]

        # ── 固定元素：人像照片（顶部）──
        portrait = _build_portrait(cfg)
        self.add(portrait)

        # 人像底边 Y 坐标（用于定位 topic）
        # portrait_bottom_y = portrait.get_bottom()[1]  # 已由 next_to 隐式使用

        # ── 固定元素：橙红色大标题 ──
        topic = _build_topic(cfg, colors, font)
        if len(topic) > 0:
            topic.next_to(portrait, DOWN, buff=0.2)
            topic.set_x(0)
            # 如果宽度超出屏幕，缩放适配
            if topic.width > 8.5:
                topic.scale_to_fit_width(8.5)
        self.add(topic)

        # ── 笔记本容器（初始放置在画面中部）──
        notebook_y = 0.0  # 笔记本中心 Y（画面中部，topic 下方）
        # 动态计算笔记本 Y，使其刚好在 topic 下方留有 buff
        if len(topic) > 0:
            topic_bottom = topic.get_bottom()[1]
            notebook_y = topic_bottom - 5.5 / 2 - 0.3
        else:
            notebook_y = 0.0

        # ── 固定元素：副标题（笔记本下方固定）──
        subtitle = _build_subtitle(cfg, colors, font)
        subtitle_y = notebook_y - 5.5 / 2 - 1.5
        # 确保副标题不超出底部
        if subtitle_y < -7.2:
            subtitle_y = -7.2
        if len(subtitle) > 0:
            subtitle.move_to([0, subtitle_y, 0])
        self.add(subtitle)

        # 字幕 Y 坐标（副标题上方）
        caption_y = subtitle_y + 0.9 if len(subtitle) > 0 else subtitle_y

        # ── 音频 ──
        audio = _audio("PortraitNotebookScene")
        if audio:
            self.add_sound(audio)
        tl = _Timeline("PortraitNotebookScene")

        # ── 场景配置 ──
        scene_cfg = None
        for s in cfg.get("scenes", []):
            if s["name"] == "PortraitNotebookScene":
                scene_cfg = s
                break

        if not scene_cfg:
            self.wait(5)
            return

        narration = scene_cfg["narration"].strip()
        raw_sentences = [s.strip() for s in narration.split("\n") if s.strip()]

        # 支持 illustration_keywords 和 illustrations 两种配置方式
        keywords = scene_cfg.get("illustration_keywords", [])
        if not keywords:
            illustrations = scene_cfg.get("illustrations", [])
            keywords = [ill.get("keyword") if isinstance(ill, dict) else ill for ill in illustrations]

        # 拆分超长句子（与 TTS 逻辑保持一致）
        max_chars = cfg.get("layout", {}).get("max_chars_per_card", 24)
        from core.utils import split_long_sentences
        sentences, keywords = split_long_sentences(raw_sentences, keywords, max_chars)

        # ── 循环渲染每个句子 ──
        prev_caption = None
        prev_notebook_group = None  # 始终指向已 add() 到场景中的 notebook_group
        prev_kw = None

        for i, sentence in enumerate(sentences):
            kw = keywords[i] if i < len(keywords) else None
            need_new_illus = (kw is not None) and (kw != prev_kw)

            # ── 构建新笔记本：仅首次或关键词变化时才重建 ──
            if prev_notebook_group is None or need_new_illus:
                notebook_group, notebook_rect = _build_notebook(colors)
                notebook_group.move_to([0, notebook_y, 0])

                # ── 插画（放在笔记本内部）──
                if need_new_illus:
                    img_path = _load_illustration(kw)
                    if img_path:
                        illus = ImageMobject(img_path)
                        # 插画尺寸不超过笔记本内部可用区域（留出螺旋线和边距）
                        max_illus_w = 6.5
                        max_illus_h = 4.8
                        illus.scale_to_fit_width(min(illus_size, max_illus_w))
                        if illus.height > max_illus_h:
                            illus.scale_to_fit_height(max_illus_h)
                        # 插画居中放在笔记本矩形内（偏右以避开螺旋线）
                        illus.move_to([notebook_group.get_center()[0] + 0.2,
                                       notebook_y, 0])
                        notebook_group.add(illus)
            else:
                # 关键词未变：不重建 notebook，继续使用已在场景中的 prev_notebook_group
                notebook_group = prev_notebook_group

            # ── 字幕（当前句，直接替换）──
            caption = Text(
                _wrap_chinese(sentence, wrap_chars),
                font=font,
                font_size=32,
                color=colors["text"],
                line_spacing=1.2,
            )
            if caption.width > 8.5:
                caption.scale_to_fit_width(8.5)
            caption.move_to([0, caption_y, 0])

            # ── 动画 ──
            if prev_notebook_group is not None and need_new_illus:
                # 笔记本（含插画）整体滑动：旧的滑出到左边，新的从右边滑入
                notebook_group.shift(RIGHT * SLIDE_DISTANCE)
                animations = [
                    prev_notebook_group.animate.shift(LEFT * SLIDE_DISTANCE),
                    notebook_group.animate.shift(LEFT * SLIDE_DISTANCE),
                ]
                # 替换字幕
                if prev_caption is not None:
                    self.remove(prev_caption)
                self.add(caption)

                self.play(*animations, run_time=0.5)
                self.remove(prev_notebook_group)
                # add 新 notebook 到场景（滑入后已在正确位置）
                # play 期间已通过 animate 将其纳入渲染，remove 旧的后新的仍可见
                tl.sync(self, 0.5)
                prev_kw = kw
                prev_notebook_group = notebook_group  # 新建的已加入场景
            else:
                # 无需换图：首次显示笔记本，或关键词未变只换字幕
                if prev_notebook_group is None:
                    # 首次：将新建的 notebook 加入场景
                    self.add(notebook_group)
                    prev_notebook_group = notebook_group
                # 关键词未变时 notebook_group is prev_notebook_group，无需重新 add
                if prev_caption is not None:
                    self.remove(prev_caption)
                self.add(caption)
                tl.sync(self, 0)

            prev_caption = caption
            # 注意：prev_notebook_group 已在上面各分支中正确维护，不在此处统一赋值

        self.wait(tl.remaining())
