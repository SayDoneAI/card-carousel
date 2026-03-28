"""封面场景 — 插画上半屏全宽 + 金线分隔 + 大字标题"""

# ruff: noqa: F403, F405, E402
from manim import *
import os
import sys
import textwrap
from pathlib import Path as _Path

_DIR = os.environ.get(
    "CARD_CAROUSEL_PROJECT_DIR", str(_Path(__file__).resolve().parents[2])
)
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from templates.shared import _load_config, _build_gradient_image, FRAME_BASE


def _wrap_title(title: str, per_line: int = 10) -> str:
    """按字数拆行（优先在标点处断开）"""
    if len(title) <= per_line:
        return title
    mid = len(title) // 2
    # 在中点附近寻找合适的标点断行
    for punct in "？！。，、；,. ":
        idx = title.find(punct, mid - 3)
        if 0 < idx <= mid + 5:
            return title[:idx + 1] + "\n" + title[idx + 1:]
    # 没有标点则直接从中点切
    return title[:mid] + "\n" + title[mid:]


class DarkCardCover(Scene):
    def construct(self):
        cfg = _load_config()

        canvas = cfg.get("canvas", {})
        pw = canvas.get("pixel_width", 1080)
        ph = canvas.get("pixel_height", 1920)
        config.pixel_width = pw
        config.pixel_height = ph
        config.frame_width = FRAME_BASE
        config.frame_height = FRAME_BASE * ph / pw
        self.camera.frame_width = config.frame_width
        self.camera.frame_height = config.frame_height

        fw = config.frame_width   # 8.0
        fh = config.frame_height  # ≈14.22 for 1080×1920

        colors = cfg.get("layout", {}).get("colors", {})
        font = cfg.get("layout", {}).get("font", "Heiti SC")
        brand = cfg.get("brand", {})
        brand_defaults = cfg.get("brand_defaults", {})

        def brand_val(key, default=""):
            return brand.get(key) or brand_defaults.get(key) or default

        # ── 背景 ──
        bg_cfg = cfg.get("layout", {}).get("background", {})
        if bg_cfg.get("type") == "gradient":
            grad_path = _build_gradient_image(bg_cfg, pw, ph)
            if grad_path:
                bg = ImageMobject(grad_path)
                bg.scale_to_fit_width(fw)
                bg.move_to(ORIGIN)
                self.add(bg)
        else:
            self.camera.background_color = colors.get("bg", "#0A0A0A")

        # ── 插画：全宽 4:3 裁切，顶部对齐，占上方 42% ──
        cover_img_path = None
        # 优先从 per-config 目录读取（由 CARD_CAROUSEL_COVER_DIR 指定）
        _cover_dir_env = os.environ.get("CARD_CAROUSEL_COVER_DIR")
        _search_dirs = ([_cover_dir_env] if _cover_dir_env else []) + [os.path.join(_DIR, "assets")]
        for _search_dir in _search_dirs:
            for _cand in ["cover_illustration.jpg", "cover_illustration.png", "cover_ai_identity.png"]:
                _p = os.path.join(_search_dir, _cand)
                if os.path.exists(_p):
                    cover_img_path = _p
                    break
            if cover_img_path:
                break

        illus_height = fh * 0.42          # 插画高度 ≈ 5.97 units
        illus_center_y = fh / 2 - illus_height / 2   # 顶部贴边

        if cover_img_path:
            from PIL import Image as PILImage
            import tempfile
            src = PILImage.open(cover_img_path).convert("RGBA")
            sw, sh = src.size
            # 裁成 4:3 横版，全宽展示
            target_ratio = 4 / 3
            if sw / sh > target_ratio:
                nw = int(sh * target_ratio)
                left = (sw - nw) // 2
                src = src.crop((left, 0, left + nw, sh))
            else:
                nh = int(sw / target_ratio)
                top = (sh - nh) // 2
                src = src.crop((0, top, sw, top + nh))
            tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
            src.save(tmp.name)
            tmp.close()
            illus = ImageMobject(tmp.name)
            illus.scale_to_fit_width(fw)
            illus.move_to([0, illus_center_y, 0])
            self.add(illus)

        # 插画底部 y 坐标
        divider_y = fh / 2 - illus_height - 0.06

        # ── 金色分隔线 ──
        accent = colors.get("accent", "#FFD700")
        line = Line(
            start=[-fw * 0.46, divider_y, 0],
            end=[fw * 0.46, divider_y, 0],
            color=accent,
            stroke_width=3,
        )
        self.add(line)

        # ── 大字标题（白色，两行）──
        title = cfg.get("title", "")
        if not title:
            title = brand_val("topic", "")
        title_str = _wrap_title(title, per_line=10)

        title_mob = Text(
            title_str,
            font="阿里巴巴普惠体 2.0",
            font_size=72,
            color="#FFFFFF",
            weight=HEAVY,
            line_spacing=1.25,
        )
        max_w = fw * 0.88
        if title_mob.width > max_w:
            title_mob.scale_to_fit_width(max_w)

        # 标题顶部距分隔线 0.4 units
        title_top_y = divider_y - 0.4
        title_mob.move_to([0, title_top_y - title_mob.height / 2, 0])
        self.add(title_mob)

        title_bottom_y = title_top_y - title_mob.height

        # ── 话题金句（金色，标题下方）──
        topic = brand_val("topic", "")
        if topic and topic != title:
            topic_mob = Text(
                topic,
                font=font,
                font_size=28,
                color=accent,
            )
            if topic_mob.width > fw * 0.84:
                topic_mob.scale_to_fit_width(fw * 0.84)
            topic_mob.move_to([0, title_bottom_y - 0.3 - topic_mob.height / 2, 0])
            self.add(topic_mob)

        # ── 作者 + slogan 底部 ──
        muted = colors.get("subtitle", "#888888")
        author = brand_val("author", "@黄赋")
        slogan = brand_val("slogan", "关注我，陪你打怪升级")

        slogan_mob = Text(slogan, font=font, font_size=20, color=muted)
        author_mob = Text(author, font=font, font_size=22, color=muted)

        bottom_y = -fh / 2 + fh * 0.05
        slogan_mob.move_to([0, bottom_y + slogan_mob.height / 2, 0])
        author_mob.move_to([0, bottom_y + slogan_mob.height + 0.15 + author_mob.height / 2, 0])
        self.add(author_mob, slogan_mob)

        self.wait(1.0)
