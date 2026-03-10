"""
通用卡片渲染引擎 — 声明式模板基类

所有模板 scene.py 只需继承 GenericCardScene 并设置 SCENE_NAME，
元素布局、动画、时间线等逻辑全部由此引擎从 defaults.yaml 驱动。
"""

# ruff: noqa: F403, F405, E402
from manim import *
import json
import os
import sys

import numpy as np
from PIL import Image as PILImage

from pathlib import Path as _Path

# ── 路径初始化 ────────────────────────────────────────────────────────
_DIR = os.environ.get(
    "CARD_CAROUSEL_PROJECT_DIR",
    str(_Path(__file__).resolve().parents[1]),
)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from core.utils import (  # noqa: E402
    percent_to_manim,
    get_element_position,
    is_explicitly_positioned,
    wrap_chinese,
    split_long_sentences,
    sanitize_filename,
)

# ── 音频 / 时间线 / 插画路径 ──────────────────────────────────────────
_DEFAULT_MEDIA = os.path.join(_DIR, "media", "videos", "scene")
AUDIO_DIR = os.environ.get(
    "CARD_CAROUSEL_AUDIO_DIR", os.path.join(_DEFAULT_MEDIA, "audio")
)
TIMING_FILE = os.environ.get(
    "CARD_CAROUSEL_TIMING_FILE", os.path.join(_DEFAULT_MEDIA, "_timing.json")
)
_PREVIEW_ASSETS_DIR = os.environ.get("CARD_CAROUSEL_PREVIEW_ASSETS_DIR")
if _PREVIEW_ASSETS_DIR and os.path.isdir(_PREVIEW_ASSETS_DIR):
    ASSETS_DIR = _PREVIEW_ASSETS_DIR
else:
    ASSETS_DIR = os.path.join(_DIR, "assets", "illustrations")

# ── 画布基准宽度 ──────────────────────────────────────────────────────
FRAME_BASE = 9.0

# ── 滑动动画距离 ─────────────────────────────────────────────────────
SLIDE_DISTANCE = 12


# ═══════════════════════════════════════════════════════════════════════
#  共享工具函数（从两个 scene.py 提取，完全一致）
# ═══════════════════════════════════════════════════════════════════════

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
    project_root = _DIR
    default_config = os.path.join(project_root, "config.yaml")
    config_path = os.environ.get("CARD_CAROUSEL_CONFIG_PATH", default_config)
    from core.config import load_config
    return load_config(config_path)


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


# ── 颜色工具 ─────────────────────────────────────────────────────────

def _hex_to_rgb(color, fallback=(255, 255, 255)):
    if not isinstance(color, str):
        return fallback
    value = color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return fallback
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def _rgb_to_hex(rgb):
    r, g, b = (max(0, min(255, int(v))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _shift_tone(rgb, ratio):
    if ratio >= 0:
        return tuple(channel + (255 - channel) * ratio for channel in rgb)
    return tuple(channel * (1 + ratio) for channel in rgb)


def _is_light_color(rgb):
    r, g, b = rgb
    brightness = (0.299 * r + 0.587 * g + 0.114 * b) / 255
    return brightness >= 0.5


# ── 插画加载 ─────────────────────────────────────────────────────────

_BG_CACHE = {}


def _remove_bg(path, threshold=220):
    """将近白色背景转为透明"""
    if path in _BG_CACHE:
        return _BG_CACHE[path]

    out_path = path.rsplit('.', 1)[0] + '_nobg.png'
    if os.path.exists(out_path):
        _BG_CACHE[path] = out_path
        return out_path

    img = PILImage.open(path).convert("RGBA")
    data = np.array(img)

    corners = [data[0, 0], data[0, -1], data[-1, 0], data[-1, -1]]
    avg_brightness = np.mean([np.mean(c[:3]) for c in corners])
    if avg_brightness < 128:
        _BG_CACHE[path] = path
        return path

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
    safe_name = sanitize_filename(keyword)
    for ext in (".png", ".jpg", ".jpeg"):
        path = os.path.join(ASSETS_DIR, f"{safe_name}{ext}")
        if os.path.exists(path):
            return _remove_bg(path)
    return None


def _should_use_placeholder_mode(cfg):
    preview_cfg = cfg.get("preview", {})
    if not isinstance(preview_cfg, dict):
        return False
    return bool(preview_cfg.get("use_illustration_placeholder", False))


def _build_illustration_placeholder(width, height, bg_color, font):
    bg_rgb = _hex_to_rgb(bg_color)
    bg_is_light = _is_light_color(bg_rgb)
    fill_rgb = _shift_tone(bg_rgb, -0.22 if bg_is_light else 0.24)
    stroke_rgb = _shift_tone(bg_rgb, -0.35 if bg_is_light else 0.38)
    fill_color = _rgb_to_hex(fill_rgb)
    stroke_color = _rgb_to_hex(stroke_rgb)

    placeholder_box = Rectangle(
        width=width,
        height=height,
        fill_color=fill_color,
        fill_opacity=1,
        stroke_color=stroke_color,
        stroke_width=2,
    )
    placeholder_text = Text(
        "插画占位",
        font=font,
        font_size=28,
        color=stroke_color,
        weight=MEDIUM,
    )
    if placeholder_text.width > width * 0.75:
        placeholder_text.scale_to_fit_width(width * 0.75)
    if placeholder_text.height > height * 0.45:
        placeholder_text.scale_to_fit_height(height * 0.45)

    return VGroup(placeholder_box, placeholder_text)


def _build_illustration(keyword, cfg, colors, font, illus_size, max_height=None):
    """构建插画 Mobject（图片或占位图）"""
    use_placeholder_only = _should_use_placeholder_mode(cfg)
    img_path = None if use_placeholder_only else _load_illustration(keyword)
    max_h = max_height or min(illus_size * 0.75, 3.0)

    if not img_path:
        if not use_placeholder_only:
            return None
        placeholder_height = max_h
        return _build_illustration_placeholder(
            width=illus_size,
            height=placeholder_height,
            bg_color=colors["bg"],
            font=font,
        )

    illus = ImageMobject(img_path)
    illus.scale_to_fit_width(illus_size)
    if illus.height > max_h:
        illus.scale_to_fit_height(max_h)
    return illus


# ── 配置解析辅助 ─────────────────────────────────────────────────────

def _get_colors(cfg):
    """从 config 读取颜色，支持任意 key"""
    return dict(cfg.get("layout", {}).get("colors", {}))


def _get_font(cfg):
    return cfg.get("layout", {}).get("font", "PingFang SC")


def _get_font_size(cfg):
    return cfg.get("layout", {}).get("font_size", 44)


def _get_wrap_chars(cfg):
    return cfg.get("layout", {}).get("wrap_chars", 9)


def _get_illustration_size(cfg):
    return cfg.get("layout", {}).get("illustration_size", 4.0)


def _resolve_cfg_path(cfg, dotted_path):
    """按点分路径从 cfg 取值，如 'layout.portrait_image'"""
    keys = dotted_path.split(".")
    obj = cfg
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
    return obj


# ═══════════════════════════════════════════════════════════════════════
#  GenericCardScene — 声明式通用渲染引擎
# ═══════════════════════════════════════════════════════════════════════

class GenericCardScene(Scene):
    """
    声明式卡片渲染引擎 — 所有模板的基类。

    子类只需设置 SCENE_NAME，所有渲染逻辑由 defaults.yaml 中的
    positionable_elements 声明驱动。
    """

    SCENE_NAME = "GenericScene"

    def construct(self):
        # ── 加载配置 ──
        cfg = _load_config()

        # ── 画布设置（从 canvas 或 layout 回退）──
        canvas = cfg.get("canvas", {})
        pw = canvas.get("pixel_width", 1080)
        ph = canvas.get("pixel_height", None)
        if ph is None:
            ph = cfg.get("layout", {}).get("pixel_height", 1440)
        config.pixel_width = pw
        config.pixel_height = ph
        ratio = ph / pw
        config.frame_width = FRAME_BASE
        config.frame_height = FRAME_BASE * ratio

        # ── 基础参数 ──
        colors = _get_colors(cfg)
        font = _get_font(cfg)
        font_size = _get_font_size(cfg)
        wrap_chars = _get_wrap_chars(cfg)
        illus_size = _get_illustration_size(cfg)

        self.camera.background_color = colors.get("bg", "#FFFFFF")

        # ── 声明式元素 ──
        elements = cfg.get("positionable_elements", [])

        # 用于追踪 flow_layout 元素的 Mobject 引用
        flow_mobjects = {}  # id -> Mobject

        # 第一遍：渲染固定元素和非动画元素
        for elem in elements:
            elem_type = elem.get("type", "text")
            elem_id = elem.get("id", "")

            if elem_type == "image":
                mob = self._add_image_element(elem, cfg)
                if mob is not None:
                    self.add(mob)

            elif elem_type == "mask":
                mob = self._add_mask_element(elem, colors)
                if mob is not None:
                    self.add(mob)

            elif elem_type == "logo":
                mob = self._add_logo_element(elem, cfg, colors, font)
                if mob is not None:
                    self.add(mob)

            elif elem_type == "text":
                mob = self._add_text_element(elem, cfg, colors, font)
                if mob is not None:
                    self.add(mob)
                    flow_mobjects[elem_id] = mob

            elif elem_type == "bar":
                mob = self._add_bar_element(elem, cfg, colors, font)
                if mob is not None:
                    self.add(mob)

            # illustration / caption 在动画循环中处理

        # ── 音频 ──
        audio = _audio(self.SCENE_NAME)
        if audio:
            self.add_sound(audio)
        tl = _Timeline(self.SCENE_NAME)

        # ── 场景配置 ──
        scene_cfg = None
        for s in cfg.get("scenes", []):
            if s["name"] == self.SCENE_NAME:
                scene_cfg = s
                break

        if not scene_cfg:
            self.wait(5)
            return

        # ── 动画循环 ──
        self._run_animation_loop(
            cfg, scene_cfg, elements, colors, font, font_size,
            wrap_chars, illus_size, tl, flow_mobjects,
        )

    # ── 元素构建方法 ─────────────────────────────────────────────────

    def _add_image_element(self, elem, cfg):
        """type: image — 加载图片，按 anchor/width 定位"""
        source = elem.get("source", "")
        rel_path = _resolve_cfg_path(cfg, source) if source else None
        if not rel_path:
            return None

        full_path = os.path.join(_DIR, rel_path)
        if not os.path.exists(full_path):
            # 无图时用占位矩形
            fw = config.frame_width
            fh = config.frame_height
            placeholder = Rectangle(
                width=fw,
                height=fh * 0.35,
                fill_color="#1A1A1A",
                fill_opacity=1,
                stroke_width=0,
            )
            anchor = elem.get("anchor", "center")
            if anchor == "top":
                placeholder.move_to(
                    UP * (fh / 2 - placeholder.height / 2)
                )
            return placeholder

        img = ImageMobject(full_path)
        width_mode = elem.get("width", "full")
        if width_mode == "full":
            img.scale_to_fit_width(config.frame_width)

        anchor = elem.get("anchor", "center")
        if anchor == "top":
            img.move_to(UP * (config.frame_height / 2 - img.height / 2))
        elif anchor == "bottom":
            img.move_to(DOWN * (config.frame_height / 2 - img.height / 2))

        return img

    def _add_logo_element(self, elem, cfg, colors, font):
        """type: logo — 圆圈 + 单字 Logo"""
        logo_char = None
        brand_defaults = cfg.get("brand_defaults", {})
        if isinstance(brand_defaults, dict):
            logo_char = brand_defaults.get("logo_char")
        if not logo_char:
            brand_cfg = cfg.get("brand", {})
            if isinstance(brand_cfg, dict):
                logo_char = brand_cfg.get("logo_char")
        if not logo_char:
            brand_field = elem.get("brand_field")
            if isinstance(brand_field, dict):
                logo_char = cfg.get("brand", {}).get(brand_field.get("key", ""), "")
        if not logo_char:
            return None

        text_color = colors.get("text", "#000000")
        color_fields = elem.get("color_fields", [])
        if color_fields:
            text_color = colors.get(color_fields[0]["key"], text_color)

        circle = Circle(radius=0.35, color=text_color, stroke_width=2.5)
        logo_text = Text(
            logo_char,
            font=font,
            font_size=22,
            color=text_color,
            weight=BOLD,
        )
        logo = VGroup(circle, logo_text)

        elem_id = elem.get("id", "")
        pos = get_element_position(
            cfg, elem_id, config.frame_width, config.frame_height,
        )
        if pos is not None:
            logo.move_to([pos[0], pos[1], 0])

        return logo

    def _add_text_element(self, elem, cfg, colors, font):
        """type: text — 读 brand 字段，设字号/颜色/位置/weight"""
        brand_field = elem.get("brand_field")
        text_content = ""
        if brand_field:
            text_content = cfg.get("brand", {}).get(brand_field["key"], "")
        if not text_content:
            return None

        # 颜色：取第一个 color_field 对应的颜色
        color_fields = elem.get("color_fields", [])
        text_color = colors.get("text", "#000000")
        if color_fields:
            text_color = colors.get(color_fields[0]["key"], text_color)

        fs = elem.get("font_size_override", _get_font_size(cfg))
        weight_str = elem.get("weight", "").upper()
        weight = BOLD if weight_str == "BOLD" else NORMAL

        line_spacing = elem.get("line_spacing", 1.2)

        mob = Text(
            text_content,
            font=font,
            font_size=fs,
            color=text_color,
            weight=weight,
            line_spacing=line_spacing,
        )

        # 宽度限制
        max_w = config.frame_width * 0.95
        if mob.width > max_w:
            mob.scale_to_fit_width(max_w)

        # 定位
        elem_id = elem.get("id", "")
        flow = elem.get("flow_layout", False)

        if flow:
            # flow_layout 元素：仅在有显式覆盖时绝对定位
            if is_explicitly_positioned(cfg, elem_id):
                pos = get_element_position(
                    cfg, elem_id, config.frame_width, config.frame_height,
                )
                if pos is not None:
                    mob.move_to([pos[0], pos[1], 0])
                    mob._has_explicit_position = True
                else:
                    mob._has_explicit_position = False
            else:
                mob._has_explicit_position = False
        else:
            pos = get_element_position(
                cfg, elem_id, config.frame_width, config.frame_height,
                fallback_fn=lambda: (0, 0),
            )
            if pos is not None:
                mob.move_to([pos[0], pos[1], 0])

        return mob

    def _add_bar_element(self, elem, cfg, colors, font):
        """type: bar — 底栏矩形 + 标签"""
        bar_bg = colors.get("bar_bg", "#DBDADB")
        bar_text_color = colors.get("bar_text", "#1A1A1A")

        # 颜色字段覆盖
        color_fields = elem.get("color_fields", [])
        for cf in color_fields:
            key = cf["key"]
            if key == "bar_bg":
                bar_bg = colors.get(key, bar_bg)
            elif key == "bar_text":
                bar_text_color = colors.get(key, bar_text_color)

        bar_h = elem.get("bar_height", 1.0)
        bar = Rectangle(
            width=config.frame_width + 1,
            height=bar_h,
            fill_color=bar_bg,
            fill_opacity=1,
            stroke_width=0,
        )

        elem_id = elem.get("id", "")
        pos = get_element_position(
            cfg, elem_id, config.frame_width, config.frame_height,
            fallback_fn=lambda: (0, -config.frame_height / 2 + bar_h / 2),
        )
        if pos is not None:
            bar.move_to([pos[0], pos[1], 0])

        # 底栏标签文字
        tags_lines = cfg.get("brand", {}).get("footer_tags", [])
        if not tags_lines:
            return bar

        tag_texts = VGroup()
        for line in tags_lines:
            t = Text(line, font=font, font_size=17, color=bar_text_color)
            tag_texts.add(t)
        tag_texts.arrange(DOWN, buff=0.2)
        tag_texts.move_to(bar.get_center())

        return VGroup(bar, tag_texts)

    def _add_mask_element(self, elem, colors):
        """type: mask — 渐变遮罩矩形"""
        mask_color = elem.get("color", "#000000")
        opacity = elem.get("opacity", 0.5)
        position = elem.get("position", "top")
        height_pct = elem.get("height_percent", 15) / 100.0

        fw = config.frame_width
        fh = config.frame_height
        mask_h = fh * height_pct

        mask_rect = Rectangle(
            width=fw + 0.5,
            height=mask_h,
            fill_color=mask_color,
            fill_opacity=opacity,
            stroke_width=0,
        )

        if position == "top":
            mask_rect.move_to(UP * (fh / 2 - mask_h / 2))
        elif position == "bottom":
            mask_rect.move_to(DOWN * (fh / 2 - mask_h / 2))

        return mask_rect

    # ── 动画循环 ─────────────────────────────────────────────────────

    def _run_animation_loop(
        self, cfg, scene_cfg, elements, colors, font,
        font_size, wrap_chars, illus_size, tl, flow_mobjects,
    ):
        """插画切换 + 字幕/大字同步（统一两个模板的动画逻辑）"""
        narration = scene_cfg["narration"].strip()
        raw_sentences = [s.strip() for s in narration.split("\n") if s.strip()]

        keywords = scene_cfg.get("illustration_keywords", [])
        if not keywords:
            illustrations = scene_cfg.get("illustrations", [])
            keywords = [
                ill.get("keyword") if isinstance(ill, dict) else ill
                for ill in illustrations
            ]

        max_chars = cfg.get("layout", {}).get("max_chars_per_card", 18)
        sentences, keywords = split_long_sentences(raw_sentences, keywords, max_chars)

        # 查找 illustration / caption 元素声明
        illus_elem = None
        caption_elem = None
        for elem in elements:
            etype = elem.get("type", "text")
            if etype == "illustration":
                illus_elem = elem
            elif etype == "caption":
                caption_elem = elem

        # 查找 flow_layout text 元素（如 pinyin）用于动态跟随
        flow_text_elems = [
            e for e in elements
            if e.get("type", "text") == "text" and e.get("flow_layout", False)
        ]

        prev_caption = None
        prev_illus = None
        prev_kw = None

        # 确定字幕 Y（如果有 caption 元素声明）
        caption_x = 0
        caption_y = None
        if caption_elem:
            def _caption_fallback():
                dx = caption_elem.get("default_x")
                dy = caption_elem.get("default_y")
                if dx is None or dy is None:
                    return None
                return percent_to_manim(
                    dx, dy, config.frame_width, config.frame_height,
                )

            cap_pos = get_element_position(
                cfg,
                caption_elem.get("id", "caption"),
                config.frame_width,
                config.frame_height,
                fallback_fn=_caption_fallback,
            )
            if cap_pos is not None:
                caption_x = cap_pos[0]
                caption_y = cap_pos[1]

        # 找引用锚点（用于 flow_layout 元素的 next_to 定位）
        # 寻找非 flow 的 text 元素作为标题锚点
        title_anchor = None
        for eid, mob in flow_mobjects.items():
            elem_def = next(
                (e for e in elements if e.get("id") == eid), None
            )
            if elem_def and not elem_def.get("flow_layout", False):
                title_anchor = mob
                break

        for i, sentence in enumerate(sentences):
            kw = keywords[i] if i < len(keywords) else None
            need_new_illus = (kw is not None) and (kw != prev_kw)

            # ── 大号文字（字幕/主内容） ──
            caption_text = Text(
                wrap_chinese(sentence, wrap_chars),
                font=font,
                font_size=font_size,
                color=colors.get("text", "#FFFFFF"),
                weight=BOLD,
                line_spacing=1.0,
            )
            max_w = config.frame_width * 0.95
            if caption_text.width > max_w:
                caption_text.scale_to_fit_width(max_w)

            if caption_y is not None:
                caption_text.move_to([caption_x, caption_y, 0])
            elif title_anchor is not None:
                caption_text.next_to(title_anchor, DOWN, buff=0.5)
                caption_text.set_x(caption_x)
            else:
                caption_text.set_x(caption_x)

            # 更新 flow 元素位置（如拼音跟随主文字）
            for ftelem in flow_text_elems:
                fid = ftelem.get("id", "")
                fmob = flow_mobjects.get(fid)
                if fmob is not None and not getattr(fmob, '_has_explicit_position', False):
                    fmob.next_to(caption_text, DOWN, buff=0.3)

            # ── 插画 ──
            illus = None
            if need_new_illus and illus_elem is not None:
                illus = _build_illustration(kw, cfg, colors, font, illus_size)
                if illus is not None:
                    illus_id = illus_elem.get("id", "illustration")
                    illus_pos = get_element_position(
                        cfg, illus_id, config.frame_width, config.frame_height,
                    )
                    if illus_pos is not None:
                        illus.move_to([illus_pos[0], illus_pos[1], 0])
                    else:
                        # 动态定位：紧跟最后一个 flow 文字下方
                        anchor_mob = caption_text
                        for ftelem in flow_text_elems:
                            fmob = flow_mobjects.get(ftelem.get("id", ""))
                            if fmob is not None:
                                anchor_mob = fmob
                        illus.next_to(anchor_mob, DOWN, buff=0.4)
                        illus.set_x(0)

            # ── 动画 ──
            if prev_caption is not None:
                self.remove(prev_caption)
            self.add(caption_text)

            if need_new_illus and illus is not None:
                animations = []
                if prev_illus is not None:
                    animations.append(
                        prev_illus.animate.shift(LEFT * SLIDE_DISTANCE)
                    )
                illus.shift(RIGHT * SLIDE_DISTANCE)
                animations.append(
                    illus.animate.shift(LEFT * SLIDE_DISTANCE)
                )
                self.play(*animations, run_time=0.5)
                if prev_illus is not None:
                    self.remove(prev_illus)
                tl.sync(self, 0.5)
                prev_illus = illus
                prev_kw = kw
            else:
                tl.sync(self, 0)

            prev_caption = caption_text

        self.wait(tl.remaining())
