"""封面场景 — 与常规卡片完全相同的布局:
顶部灰色标题栏 → 插画区（大红标题 + 小棒人叠加）→ 黑色粗分隔线 → 白色字幕区
"""

# ruff: noqa: F403, F405, E402
from manim import *
import os
import sys
from pathlib import Path as _Path

_DIR = os.environ.get(
    "CARD_CAROUSEL_PROJECT_DIR", str(_Path(__file__).resolve().parents[2])
)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from templates.shared import _load_config, FRAME_BASE, _remove_bg


def _wrap_title(title: str, per_line: int = 8) -> str:
    """按字数拆行（优先在标点处断开）"""
    if len(title) <= per_line:
        return title
    mid = len(title) // 2
    for punct in "？！。，、；,. ":
        idx = title.find(punct, mid - 3)
        if 0 < idx <= mid + 5:
            return title[:idx + 1] + "\n" + title[idx + 1:]
    return title[:mid] + "\n" + title[mid:]


class SketchCardCover(Scene):
    def construct(self):
        cfg = _load_config()

        canvas = cfg.get("canvas", {})
        pw = canvas.get("pixel_width", 1080)
        ph = canvas.get("pixel_height", 1440)
        config.pixel_width = pw
        config.pixel_height = ph
        config.frame_width = FRAME_BASE
        config.frame_height = FRAME_BASE * ph / pw
        self.camera.frame_width = config.frame_width
        self.camera.frame_height = config.frame_height

        fw = config.frame_width    # 8.0
        fh = config.frame_height   # 10.667 for 1080×1440

        layout = cfg.get("layout", {})
        colors = layout.get("colors", {})
        font = layout.get("font", "PingFang SC")
        brand = cfg.get("brand", {})
        brand_defaults = cfg.get("brand_defaults", {})

        def brand_val(key, default=""):
            return brand.get(key) or brand_defaults.get(key) or default

        # ── 纯白背景 ──
        self.camera.background_color = "#FFFFFF"

        # ── 顶部灰色标题栏（5%）──
        top_bar_h = fh * 0.05   # 0.533
        top_bar_top = fh / 2
        top_bar_center_y = top_bar_top - top_bar_h / 2

        top_bar = Rectangle(
            width=fw,
            height=top_bar_h,
            fill_color="#F2F2F2",
            fill_opacity=1.0,
            stroke_width=0,
        )
        top_bar.move_to([0, top_bar_center_y, 0])
        self.add(top_bar)

        # 顶部栏文字（话题）
        topic = brand_val("topic", "")
        if topic:
            topic_mob = Text(
                topic,
                font=font,
                font_size=22,
                color="#888888",
            )
            if topic_mob.width > fw * 0.86:
                topic_mob.scale_to_fit_width(fw * 0.86)
            topic_mob.move_to([0, top_bar_center_y, 0])
            self.add(topic_mob)

        # ── 顶部栏下方分隔线（1px 灰线）──
        sep_top_y = top_bar_top - top_bar_h
        sep_top = Line(
            start=[-fw / 2, sep_top_y, 0],
            end=[fw / 2, sep_top_y, 0],
            color="#CCCCCC",
            stroke_width=1,
        )
        self.add(sep_top)

        # ── 内容区边界 ──
        # 内容区从标题栏底部到字幕分隔线顶部
        caption_zone_h = fh * 0.285           # 3.04 units（与 defaults.yaml 对齐）
        content_top_y = sep_top_y             # 4.8
        content_bottom_y = -fh / 2 + caption_zone_h  # -2.293
        content_h = content_top_y - content_bottom_y  # 7.093
        content_center_y = (content_top_y + content_bottom_y) / 2  # 1.254

        # ── 封面插画（小棒人，垂直居中偏下，约 40% 内容区高度）──
        cover_img_path = None
        # 优先从 per-config 目录读取（由 CARD_CAROUSEL_COVER_DIR 指定）
        _cover_dir_env = os.environ.get("CARD_CAROUSEL_COVER_DIR")
        _search_dirs = ([_cover_dir_env] if _cover_dir_env else []) + [os.path.join(_DIR, "assets")]
        for _search_dir in _search_dirs:
            for _cand in ["cover_illustration.jpg", "cover_illustration.png"]:
                _p = os.path.join(_search_dir, _cand)
                if os.path.exists(_p):
                    cover_img_path = _p
                    break
            if cover_img_path:
                break

        # cover_fullscreen: 插画占满内容区，不叠红色标题
        cover_fullscreen = cfg.get("cover", {}).get("cover_fullscreen", False)

        if cover_img_path:
            if cover_fullscreen:
                # 全屏模式：插画占满内容区，不去背景，不叠标题
                illus = ImageMobject(cover_img_path)
                # 按宽度适配，高度按比例
                illus.scale_to_fit_width(fw * 0.92)
                if illus.height > content_h * 0.92:
                    illus.scale_to_fit_height(content_h * 0.92)
                illus.move_to([0, content_center_y, 0])
                self.add(illus)
            else:
                # 默认模式：去背景，小插画 + 叠加红色标题
                nobg_path = _remove_bg(cover_img_path, threshold=230)
                illus = ImageMobject(nobg_path)
                target_h = content_h * 0.45
                illus.scale_to_fit_height(target_h)
                illus_center_y = content_top_y - content_h * 0.6
                illus.move_to([0, illus_center_y, 0])
                self.add(illus)

        if not cover_fullscreen:
            # ── 大红色标题（上层叠加）──
            title = cfg.get("title", "") or brand_val("topic", "")
            title_str = _wrap_title(title, per_line=8)
            red = colors.get("accent", "#E53935")

            title_mob = Text(
                title_str,
                font=font,
                font_size=96,
                color=red,
                weight=HEAVY,
                line_spacing=1.1,
            )
            max_w = fw * 0.90
            if title_mob.width > max_w:
                title_mob.scale_to_fit_width(max_w)

            title_center_y = content_top_y - content_h * 0.28
            title_mob.move_to([0, title_center_y, 0])
            self.add(title_mob)

        title = cfg.get("title", "") or brand_val("topic", "")

        # ── 粗黑分隔线（内容区与字幕区之间）──
        sep_bot_y = content_bottom_y
        sep_bot = Line(
            start=[-fw / 2, sep_bot_y, 0],
            end=[fw / 2, sep_bot_y, 0],
            color="#1A1A1A",
            stroke_width=8,
        )
        self.add(sep_bot)

        # ── 白色字幕区背景 ──
        caption_bar = Rectangle(
            width=fw,
            height=caption_zone_h,
            fill_color="#FFFFFF",
            fill_opacity=1.0,
            stroke_width=0,
        )
        caption_bar_center_y = content_bottom_y - caption_zone_h / 2
        caption_bar.move_to([0, caption_bar_center_y, 0])
        self.add(caption_bar)

        # 字幕区: 粗体黑色标题
        caption_mob = Text(
            title if len(title) <= 18 else title[:18],
            font=font,
            font_size=52,
            color="#1A1A1A",
            weight=BOLD,
        )
        if caption_mob.width > fw * 0.88:
            caption_mob.scale_to_fit_width(fw * 0.88)

        # 口号（第一行）
        author = brand_val("author", "创业向导，少走弯路，多做正事")
        author_mob = Text(
            author,
            font=font,
            font_size=20,
            color="#888888",
        )
        if author_mob.width > fw * 0.88:
            author_mob.scale_to_fit_width(fw * 0.88)

        # 免责声明（第二行）
        tagline = brand_val("tagline", "个人观点，无不良引导")
        tagline_mob = Text(
            tagline,
            font=font,
            font_size=18,
            color="#888888",
        )
        if tagline_mob.width > fw * 0.88:
            tagline_mob.scale_to_fit_width(fw * 0.88)

        # 标题居中偏上（字幕区上 1/3）
        caption_center_y = caption_bar_center_y + caption_zone_h * 0.18
        caption_mob.move_to([0, caption_center_y, 0])

        # 口号 + 免责声明贴近字幕区底部
        sig_gap = 0.12
        sig_total_h = author_mob.height + sig_gap + tagline_mob.height
        sig_top_y = caption_bar_center_y - caption_zone_h * 0.22 + sig_total_h / 2
        author_mob.move_to([0, sig_top_y - author_mob.height / 2, 0])
        tagline_mob.move_to([0, sig_top_y - author_mob.height - sig_gap - tagline_mob.height / 2, 0])

        self.add(caption_mob, author_mob, tagline_mob)

        self.wait(1.0)
