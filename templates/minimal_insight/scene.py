"""
图文卡片口播视频 — Manim 渲染脚本（minimal-insight 模板）
极简洞见：竖屏白底大字卡片 + 水墨插画 + 底栏标签

布局 (从上到下):
  ┌─────────────────────────────┐
  │ (赋)logo  @黄赋              │  ← 固定: 左上角圆圈logo + 作者名
  │                             │
  │ 红色主题句(居中)              │  ← 固定: brand.topic
  │                             │
  │  面对专业，他们毫无           │  ← 切换: 大号黑色粗体(当前句子)
  │      敬畏                   │
  │                             │
  │   HUANG FU                  │  ← 固定: 拼音，brand.pinyin
  │                             │
  │       [插画]                │  ← 切换: 居中插画(左右滑动)
  │                             │
  │                  个人观点    │  ← 固定: 右下角免责
  │                  仅供参考    │
  ├─────────────────────────────┤
  │ 底栏标签                     │  ← 固定: brand.footer_tags
  └─────────────────────────────┘
"""

from manim import *
import json
import os
import sys

import numpy as np
import yaml
from PIL import Image as PILImage

# 竖屏配置 1080x1440 (3:4)
config.pixel_width = 1080
config.pixel_height = 1440
config.frame_width = 8
config.frame_height = 10.667
config.background_color = "#FFFFFF"  # 默认白色，Scene.construct 中会从 cfg 覆盖

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
    # 复用 core.config.load_config 确保模板合并逻辑一致
    # （模板模式下 brand 等字段需要从 defaults.yaml 合并）
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
        "bg": colors.get("bg", "#FFFFFF"),
        "text": colors.get("text", "#000000"),
        "accent": colors.get("accent", "#C0392B"),
        "pinyin": colors.get("pinyin", "#000000"),
        "muted": colors.get("muted", "#999999"),
        "bar_bg": colors.get("bar_bg", "#DBDADB"),
        "bar_text": colors.get("bar_text", "#1A1A1A"),
    }


def _get_font(cfg):
    return cfg.get("layout", {}).get("font", "PingFang SC")


def _get_wrap_chars(cfg):
    return cfg.get("layout", {}).get("wrap_chars", 9)


def _get_illustration_size(cfg):
    return cfg.get("layout", {}).get("illustration_size", 4.0)


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


def _wrap_chinese(text, max_chars=9):
    """将中文文本按固定字数换行（还原原视频每行≤9字的排版）"""
    from core.utils import wrap_chinese
    return wrap_chinese(text, max_chars)


_BG_CACHE = {}


def _remove_bg(path, threshold=220):
    """将近白色背景转为透明，让插画融入白色卡片"""
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


def _build_logo_header(cfg, colors, font):
    """构建头部: 左上角圆圈logo + 居中作者名（还原原视频布局）"""
    brand_cfg = cfg.get("brand", {})
    logo_char = brand_cfg.get("logo_char", "深")
    author = brand_cfg.get("author", "@黄赋")

    C_TEXT = colors["text"]

    # 圆圈 logo（左上角）
    circle = Circle(radius=0.30, color=C_TEXT, stroke_width=2.5)
    logo_text = Text(logo_char, font=font, font_size=22, color=C_TEXT, weight=BOLD)
    logo = VGroup(circle, logo_text)
    logo.to_edge(LEFT, buff=0.5)
    logo.to_edge(UP, buff=0.45)

    # 作者名（居中，与 logo 同一行）
    author_text = Text(author, font=font, font_size=20, color=C_TEXT)
    author_text.move_to(UP * logo.get_center()[1])  # 同一 Y 高度
    author_text.set_x(0)

    return VGroup(logo, author_text)


def _build_topic_line(cfg, colors, font):
    """构建红色主题句（固定不动，居中）"""
    brand_cfg = cfg.get("brand", {})
    topic = brand_cfg.get("topic", "")
    if not topic:
        return VGroup()
    topic_text = Text(
        topic,
        font=font, font_size=24, color=colors["accent"],
    )
    topic_text.move_to(UP * 3.7)
    return topic_text


def _build_pinyin(cfg, colors, font):
    """构建拼音行（位置由 Scene 动态控制）"""
    brand_cfg = cfg.get("brand", {})
    pinyin = brand_cfg.get("pinyin", "")
    pinyin_text = Text(
        pinyin,
        font=font, font_size=16, color=colors["pinyin"],
    )
    pinyin_text.move_to(UP * 1.8)
    return pinyin_text


def _build_disclaimer(cfg, colors, font):
    """构建右下角免责声明"""
    brand_cfg = cfg.get("brand", {})
    disclaimer = brand_cfg.get("disclaimer", "个人观点\n仅供参考")
    text = Text(
        disclaimer,
        font=font, font_size=14, color=colors["muted"],
        line_spacing=1.2,
    )
    text.move_to(RIGHT * 3.3 + DOWN * 4.0)
    return text


def _build_footer_bar(cfg, colors, font):
    """构建黑色底栏 + 白色标签"""
    brand_cfg = cfg.get("brand", {})
    tags_lines = brand_cfg.get("footer_tags", [
        "强者思维 ｜ 认知进化 ｜ 深度思考",
        "内核重构 ｜ 心智跃迁 ｜ 底层逻辑",
    ])

    # 底栏背景（紧贴画面底部）
    BAR_H = 1.0
    bar = Rectangle(
        width=config.frame_width + 1,
        height=BAR_H,
        fill_color=colors["bar_bg"], fill_opacity=1,
        stroke_width=0,
    )
    bar.move_to(DOWN * (config.frame_height / 2 - BAR_H / 2))

    tag_texts = VGroup()
    for line in tags_lines:
        t = Text(line, font=font, font_size=17, color=colors["bar_text"])
        tag_texts.add(t)
    tag_texts.arrange(DOWN, buff=0.2)
    tag_texts.move_to(bar.get_center())

    return VGroup(bar, tag_texts)


# ── 滑动方向常量 ──
SLIDE_DISTANCE = 12  # 屏幕外距离


class Scene01_Cards(Scene):
    def construct(self):
        # ── 加载配置 ──
        cfg = _load_config()
        colors = _get_colors(cfg)
        font = _get_font(cfg)
        wrap_chars = _get_wrap_chars(cfg)
        illus_size = _get_illustration_size(cfg)

        # 应用配置中的背景色
        self.camera.background_color = colors["bg"]

        # ── 固定元素 ──
        logo_header = _build_logo_header(cfg, colors, font)
        topic_line = _build_topic_line(cfg, colors, font)
        pinyin = _build_pinyin(cfg, colors, font)
        disclaimer = _build_disclaimer(cfg, colors, font)
        footer_bar = _build_footer_bar(cfg, colors, font)

        self.add(logo_header, topic_line, pinyin, disclaimer, footer_bar)

        # ── 音频 ──
        audio = _audio("Scene01_Cards")
        if audio:
            self.add_sound(audio)
        tl = _Timeline("Scene01_Cards")

        # ── 场景配置 ──
        scene_cfg = None
        for s in cfg.get("scenes", []):
            if s["name"] == "Scene01_Cards":
                scene_cfg = s
                break

        if not scene_cfg:
            self.wait(5)
            return

        narration = scene_cfg["narration"].strip()
        raw_sentences = [s.strip() for s in narration.split("\n") if s.strip()]
        keywords = scene_cfg.get("illustration_keywords", [])

        # 拆分超长句子（与 TTS 逻辑保持一致）
        max_chars = cfg.get("layout", {}).get("max_chars_per_card", 18)
        from core.utils import split_long_sentences
        sentences, keywords = split_long_sentences(raw_sentences, keywords, max_chars)

        # ── 布局 ──
        prev_title = None
        prev_illus = None
        prev_kw = None

        for i, sentence in enumerate(sentences):
            # 大号黑色粗体文字（每行≤wrap_chars字换行，还原原视频排版）
            title = Text(
                _wrap_chinese(sentence, wrap_chars),
                font=font,
                font_size=44,
                color=colors["text"],
                weight=BOLD,
                line_spacing=1.0,
            )
            if title.width > 6.5:
                title.scale_to_fit_width(6.5)
            # 文字顶部固定在主题句下方，不管行数多少都不会重叠
            title.next_to(topic_line, DOWN, buff=0.5)
            title.set_x(0)

            # 拼音动态跟随主文字下方（紧凑间距）
            pinyin.next_to(title, DOWN, buff=0.3)

            # 判断是否需要换图
            kw = keywords[i] if i < len(keywords) else None
            need_new_illus = (kw is not None) and (kw != prev_kw)

            illus = None
            if need_new_illus:
                img_path = _load_illustration(kw)
                if img_path:
                    illus = ImageMobject(img_path)
                    illus.scale_to_fit_width(illus_size)
                    if illus.height > 3.0:
                        illus.scale_to_fit_height(3.0)
                    # 插画紧跟拼音下方，动态定位
                    illus.next_to(pinyin, DOWN, buff=0.4)
                    illus.set_x(0)

            # ── 动画：文字直接切换，插画仅在关键词变化时滑动 ──
            if prev_title is not None:
                self.remove(prev_title)
            self.add(title)

            if need_new_illus and illus is not None:
                animations = []
                # 旧插画滑出到左边
                if prev_illus is not None:
                    animations.append(
                        prev_illus.animate.shift(LEFT * SLIDE_DISTANCE)
                    )
                # 新插画从右边滑入
                illus.shift(RIGHT * SLIDE_DISTANCE)
                animations.append(
                    illus.animate.shift(LEFT * SLIDE_DISTANCE)
                )
                self.play(*animations, run_time=0.5)
                # 清理已滑出的旧插画
                if prev_illus is not None:
                    self.remove(prev_illus)
                tl.sync(self, 0.5)
                prev_illus = illus
                prev_kw = kw
            else:
                tl.sync(self, 0)

            prev_title = title

        self.wait(tl.remaining())
