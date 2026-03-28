#!/usr/bin/env python3
"""
精确预览服务器 — 轻量 HTTP 后端，驱动模板预览编辑器的「精确预览」功能

端口: 8766
提供:
  POST /api/render_frame   — 调用 Manim 渲染单帧，返回 PNG
  GET  /api/video_frame    — 从已有渲染视频抽取帧，返回 PNG
  GET  /*                  — serve tools/ 目录下的静态文件

用法:
  cd /path/to/card-carousel
  python tools/preview_server.py
"""

import http.server
import json
import logging
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

# ── 项目根目录 ──────────────────────────────────────────────────────────────
# 脚本位于 tools/，项目根在上一级
_SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = _SCRIPT_DIR.parent
TOOLS_DIR = _SCRIPT_DIR

# 确保 core / templates 等包可导入
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

PORT = 8766
PREVIEW_HOST = os.getenv("PREVIEW_HOST", "127.0.0.1").strip() or "127.0.0.1"
ALLOWED_CORS_ORIGINS = (
    f"http://localhost:{PORT}",
    f"http://127.0.0.1:{PORT}",
)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("preview_server")
DEBUG_MODE = os.getenv("DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}

# 预览服务在启动时已知项目根，提前固定，避免 load_config 在 /tmp YAML 下误判根目录
os.environ["CARD_CAROUSEL_PROJECT_DIR"] = str(PROJECT_DIR)

# 渲染并发锁：Manim 渲染是阻塞操作，用锁保证同一时刻只有一个渲染任务
_render_lock = threading.Lock()
_POSITIVE_INT_LAYOUT_FIELDS = ("wrap_chars", "max_chars_per_card")
_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg")
_CACHE_DIR = PROJECT_DIR / ".cache"
_CACHE_ILLUSTRATIONS_DIR = _CACHE_DIR / "illustrations"
_PREVIEW_ASSETS_DIR = _CACHE_DIR / "preview_assets"
_ASSETS_ILLUSTRATIONS_DIR = PROJECT_DIR / "assets" / "illustrations"
_UPLOADS_DIR = PROJECT_DIR / "assets" / "uploads"
_USER_TEMPLATES_DIR = PROJECT_DIR / ".user" / "templates"


def _client_error_message(default_msg: str, exc: Exception | None = None) -> str:
    if DEBUG_MODE and exc is not None:
        return f"{default_msg}: {exc}"
    return default_msg


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def _find_scene_class(scene_py: str) -> str | None:
    """从 scene.py 文件中提取第一个 Scene 子类名"""
    try:
        with open(scene_py, encoding="utf-8") as f:
            content = f.read()
        # 匹配 class Xxx(Scene) 或 class Xxx(MovingCameraScene) 等
        m = re.search(r"^class\s+(\w+)\s*\([^)]*Scene[^)]*\)\s*:", content, re.MULTILINE)
        if m:
            return m.group(1)
    except OSError:
        pass
    return None


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 中的值覆盖 base，返回新 dict"""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def _get_template_defaults(template: str) -> dict:
    """读取模板 defaults（含 brand_defaults 合并结果）"""
    from templates import get_template

    tmpl = get_template(template)
    defaults = dict(tmpl.get_default_config() or {})

    brand_defaults = defaults.pop("brand_defaults", {})
    top_level_footer_tags = defaults.pop("footer_tags", None)
    brand_cfg = defaults.get("brand")
    if not isinstance(brand_cfg, dict):
        defaults["brand"] = dict(brand_defaults) if isinstance(brand_defaults, dict) else {}
    elif isinstance(brand_defaults, dict):
        defaults["brand"] = _deep_merge(brand_defaults, brand_cfg)

    # footer_tags 统一真相源：仅保留 brand.footer_tags
    if top_level_footer_tags is not None:
        defaults.setdefault("brand", {})
        if isinstance(defaults["brand"], dict) and "footer_tags" not in defaults["brand"]:
            defaults["brand"]["footer_tags"] = top_level_footer_tags

    return defaults


def _resolve_scene_classes(template: str, manim_script: str | None = None) -> list[str]:
    """优先从模板注册信息获取场景类名列表，失败时回退到 scene.py 解析"""
    from templates import get_template

    tmpl = get_template(template)
    scene_classes = tmpl.get_scene_classes()
    if scene_classes:
        return list(scene_classes)

    scene_py = manim_script or os.path.join(str(PROJECT_DIR), tmpl.get_manim_script())
    parsed = _find_scene_class(scene_py)
    if parsed:
        return [parsed]
    raise RuntimeError(f"无法确定模板 {template!r} 的 Scene 类名")


def _resolve_scene_class(template: str, manim_script: str | None = None) -> str:
    scene_classes = _resolve_scene_classes(template, manim_script)
    if scene_classes:
        return scene_classes[0]
    raise RuntimeError(f"无法确定模板 {template!r} 的 Scene 类名")


def _validate_preview_params(params: dict) -> None:
    """在调用 load_config 前做前置校验，避免把非法参数送入 Manim 流程"""
    if not isinstance(params, dict):
        raise ValueError("params 必须是对象")

    layout = params.get("layout")
    if layout is None:
        params["layout"] = {}
        layout = params["layout"]
    if not isinstance(layout, dict):
        raise ValueError("params.layout 必须是对象")

    for field in _POSITIVE_INT_LAYOUT_FIELDS:
        if field not in layout:
            continue
        value = layout[field]
        if not (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        ):
            raise ValueError(
                f"params.layout.{field} 必须为正整数，当前值: {value!r}"
            )

    if "font_size" in layout:
        font_size = layout["font_size"]
        if not (
            (isinstance(font_size, int) or isinstance(font_size, float))
            and not isinstance(font_size, bool)
        ):
            raise ValueError(
                f"params.layout.font_size 必须为数字，当前值: {font_size!r}"
            )
        if not (8 <= font_size <= 200):
            raise ValueError(
                f"params.layout.font_size 必须在 8-200 范围内，当前值: {font_size!r}"
            )


def _validate_positions(positions: dict, template_id: str) -> None:
    """
    校验前端传入的 positions 参数。

    positions 格式: { element_id: { x: float, y: float }, ... }

    校验规则：
    1. 元素 id 必须在模板的 positionable_elements 中存在
    2. x 和 y 必须是数值
    3. x 和 y 必须在元素定义的 min/max 范围内

    非法数据抛出 ValueError。
    """
    if not isinstance(positions, dict):
        raise ValueError("positions 必须是对象")

    # 获取模板的 positionable_elements
    template_defaults = _get_template_defaults(template_id)
    positionable_elements = template_defaults.get("positionable_elements", [])

    if not positionable_elements:
        # 模板不支持位置调整，但有 positions 参数
        if positions:
            raise ValueError(f"模板 {template_id!r} 不支持位置调整")
        return

    # 构建合法元素 id 映射
    valid_elements = {}
    for elem in positionable_elements:
        if not isinstance(elem, dict):
            continue
        elem_id = elem.get("id")
        if not elem_id:
            continue
        valid_elements[elem_id] = {
            "min_x": elem.get("min_x", 0),
            "max_x": elem.get("max_x", 100),
            "min_y": elem.get("min_y", 0),
            "max_y": elem.get("max_y", 100),
        }

    # 校验每个位置
    for elem_id, pos in positions.items():
        if not isinstance(elem_id, str):
            raise ValueError(f"positions 的键必须是字符串，当前值: {elem_id!r}")

        if elem_id not in valid_elements:
            raise ValueError(f"元素 id {elem_id!r} 不在模板 {template_id!r} 的可定位元素列表中")

        if not isinstance(pos, dict):
            raise ValueError(f"positions[{elem_id!r}] 必须是对象")

        constraints = valid_elements[elem_id]

        # x 和 y 必须同时存在
        if "x" not in pos or "y" not in pos:
            raise ValueError(
                f"positions[{elem_id!r}] 必须同时包含 x 和 y，当前键: {sorted(pos.keys())!r}"
            )

        x = pos["x"]
        y = pos["y"]

        # 校验 x
        if not isinstance(x, (int, float)) or isinstance(x, bool):
            raise ValueError(f"positions[{elem_id!r}].x 必须是数值，当前值: {x!r}")
        if not (constraints["min_x"] <= x <= constraints["max_x"]):
            raise ValueError(
                f"positions[{elem_id!r}].x 必须在 [{constraints['min_x']}, {constraints['max_x']}] 范围内，当前值: {x}"
            )

        # 校验 y
        if not isinstance(y, (int, float)) or isinstance(y, bool):
            raise ValueError(f"positions[{elem_id!r}].y 必须是数值，当前值: {y!r}")
        if not (constraints["min_y"] <= y <= constraints["max_y"]):
            raise ValueError(
                f"positions[{elem_id!r}].y 必须在 [{constraints['min_y']}, {constraints['max_y']}] 范围内，当前值: {y}"
            )


def _validate_scenes(scenes: list) -> list:
    """
    校验并清理前端传入的 scenes 列表。

    每个 scene 期望格式:
      { name: str, narration: str, illustration_keywords: [str|null, ...] }

    返回清理后的列表；非法数据抛出 ValueError。
    """
    if not isinstance(scenes, list):
        raise ValueError("scenes 必须是数组")
    result = []
    for i, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"scenes[{i}] 必须是对象")
        name = scene.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"scenes[{i}].name 必须是非空字符串")
        narration = scene.get("narration", "")
        if not isinstance(narration, str):
            raise ValueError(f"scenes[{i}].narration 必须是字符串")
        keywords_raw = scene.get("illustration_keywords", [])
        if not isinstance(keywords_raw, list):
            raise ValueError(f"scenes[{i}].illustration_keywords 必须是数组")
        # 每个关键词只允许字符串或 null
        keywords: list = []
        for j, kw in enumerate(keywords_raw):
            if kw is None or isinstance(kw, str):
                keywords.append(kw)
            else:
                raise ValueError(
                    f"scenes[{i}].illustration_keywords[{j}] 必须是字符串或 null"
                )
        result.append({
            "name": name.strip(),
            "narration": narration,
            "illustration_keywords": keywords,
        })
    return result


def _collect_illustration_keywords(scenes: list[dict]) -> list[str]:
    """收集 scenes 里的关键词（去重、去空白），保持出现顺序。"""
    seen: set[str] = set()
    keywords: list[str] = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        raw_list = scene.get("illustration_keywords", [])
        if not isinstance(raw_list, list):
            continue
        for kw in raw_list:
            if not isinstance(kw, str):
                continue
            text = kw.strip()
            if not text or text in seen:
                continue
            seen.add(text)
            keywords.append(text)
    return keywords


def _find_cached_illustration(keyword: str) -> Path | None:
    """按关键词在 .cache 下查找缓存图片（优先 .cache/illustrations）。"""
    from core.utils import sanitize_filename

    safe_name = sanitize_filename(keyword)
    if not safe_name:
        return None

    # 与 step_illustrations 保持一致：优先 .cache/illustrations/{safe_name}.*
    for ext in _IMAGE_EXTENSIONS:
        candidate = _CACHE_ILLUSTRATIONS_DIR / f"{safe_name}{ext}"
        if candidate.is_file():
            return candidate

    # 兜底：扫描 .cache 下同名文件
    if _CACHE_DIR.is_dir():
        for ext in _IMAGE_EXTENSIONS:
            for found in _CACHE_DIR.rglob(f"{safe_name}{ext}"):
                if found.is_file():
                    return found
    return None


def _list_preview_asset_images() -> list[Path]:
    """列出 .cache/preview_assets 下的可用图片，优先原图而非 *_nobg。"""
    if not _PREVIEW_ASSETS_DIR.is_dir():
        return []
    files = [
        p for p in _PREVIEW_ASSETS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
    ]
    files.sort(key=lambda p: (p.stem.endswith("_nobg"), p.name.lower()))
    return files


def _has_preview_asset_for_keyword(safe_name: str) -> bool:
    return any(
        (_PREVIEW_ASSETS_DIR / f"{safe_name}{ext}").is_file()
        for ext in _IMAGE_EXTENSIONS
    )


def _generate_illustration(keyword: str) -> Path | None:
    """
    使用 tools/image_gen.py 生成插画。

    返回生成的图片路径，失败时返回 None。
    """
    from core.utils import sanitize_filename

    safe_name = sanitize_filename(keyword)
    if not safe_name:
        return None

    _CACHE_ILLUSTRATIONS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        import sys
        sys.path.insert(0, str(TOOLS_DIR))
        from image_gen import generate

        output_path = generate(
            prompt=keyword,
            aspect_ratio="3:4",
            image_size="2K",
            output_dir=str(_CACHE_ILLUSTRATIONS_DIR),
            filename=safe_name,
            engine="gemini",
        )

        if output_path and Path(output_path).exists():
            log.info(f"成功生成插画: {keyword} -> {output_path}")
            return Path(output_path)
    except Exception as e:
        log.warning(f"生成插画失败 ({keyword}): {e}")

    return None


def _prepare_preview_illustrations(scenes: list[dict]) -> bool:
    """
    为预览准备插画文件，返回是否必须启用占位图模式。

    规则：
      1) 按 keyword 在 .cache 查找命中并复制到 .cache/preview_assets
      2) 未命中时，尝试生成插画
      3) 生成失败时，若 .cache/preview_assets 存在任意图，则复制第一张作为该 keyword 的预览图
      4) 所有关键词都无法映射到文件时，启用占位图模式
    """
    from core.utils import sanitize_filename

    keywords = _collect_illustration_keywords(scenes)
    if not keywords:
        return False

    _PREVIEW_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    copied_from_cache = 0
    aliased_from_preview = 0
    resolved_keywords = 0

    for keyword in keywords:
        safe_name = sanitize_filename(keyword)
        if not safe_name:
            continue
        if _has_preview_asset_for_keyword(safe_name):
            resolved_keywords += 1
            continue

        cached_image = _find_cached_illustration(keyword)
        if cached_image is not None:
            cache_dest = _PREVIEW_ASSETS_DIR / cached_image.name
            if not cache_dest.exists():
                shutil.copy2(cached_image, cache_dest)
                copied_from_cache += 1

            alias_dest = _PREVIEW_ASSETS_DIR / f"{safe_name}{cache_dest.suffix.lower()}"
            if not alias_dest.exists():
                shutil.copy2(cache_dest, alias_dest)
            resolved_keywords += 1
            continue

        # 预览模式不生成新插画（避免触发 API 调用 / 限流）
        # 直接尝试从已有预览资产借用
        existing_preview_assets = _list_preview_asset_images()
        if existing_preview_assets:
            fallback = existing_preview_assets[0]
            alias_dest = _PREVIEW_ASSETS_DIR / f"{safe_name}{fallback.suffix.lower()}"
            if not alias_dest.exists():
                shutil.copy2(fallback, alias_dest)
                aliased_from_preview += 1
            resolved_keywords += 1

    # 二次兜底：对未解析的关键词，再次尝试从 preview_assets 借用
    # （主循环中其他关键词可能已向 preview_assets 添加了图片）
    if resolved_keywords > 0 and resolved_keywords < len(keywords):
        existing_preview_assets = _list_preview_asset_images()
        if existing_preview_assets:
            for keyword in keywords:
                safe_name = sanitize_filename(keyword)
                if not safe_name or _has_preview_asset_for_keyword(safe_name):
                    continue
                fallback = existing_preview_assets[0]
                alias_dest = _PREVIEW_ASSETS_DIR / f"{safe_name}{fallback.suffix.lower()}"
                if not alias_dest.exists():
                    shutil.copy2(fallback, alias_dest)
                    aliased_from_preview += 1
                resolved_keywords += 1

    use_placeholder = resolved_keywords == 0
    unresolved_count = len(keywords) - resolved_keywords
    log.info(
        "预览插画准备: keywords=%d, resolved=%d, unresolved=%d, cache_copied=%d, preview_aliased=%d, placeholder=%s",
        len(keywords),
        resolved_keywords,
        unresolved_count,
        copied_from_cache,
        aliased_from_preview,
        use_placeholder,
    )
    return use_placeholder


def _write_temp_yaml(template: str, params: dict) -> str:
    """
    将前端参数写入临时 YAML 文件。

    params 格式（与前端 getCurrentParams() 一致）:
      { colors: {...}, brand: {...}, layout: {...}, footer_tags: [...],
        scenes: [{name, narration, illustration_keywords}, ...] }
    """
    import yaml  # manim 环境应有 pyyaml

    template_defaults = _get_template_defaults(template)
    default_layout = template_defaults.get("layout", {})
    default_wrap_chars = default_layout.get("wrap_chars", 9)
    default_pixel_height = default_layout.get("pixel_height", 1440)
    if not (
        isinstance(default_pixel_height, int)
        and not isinstance(default_pixel_height, bool)
        and default_pixel_height > 0
    ):
        default_pixel_height = 1440
    scene_name = _resolve_scene_class(template)
    layout_params = params.get("layout")
    if not isinstance(layout_params, dict):
        layout_params = {}

    cfg: dict = {
        "template": template,
        "render_quality": "l",
        "preview": {},
    }

    # 颜色来源优先级：顶层 params.colors > params.layout.colors
    # 前端通常将颜色放在 params.layout.colors，兼容两种写法
    colors_value = params.get("colors") or layout_params.get("colors")
    if colors_value:
        cfg.setdefault("layout", {})["colors"] = colors_value

    if layout_params:
        # 合并 layout（排除嵌套的 colors，已单独处理）
        layout_extra = {k: v for k, v in layout_params.items() if k != "colors"}
        cfg.setdefault("layout", {}).update(layout_extra)

    if "brand" in params:
        cfg["brand"] = params["brand"]

    if "footer_tags" in params:
        cfg.setdefault("brand", {})["footer_tags"] = params["footer_tags"]

    # 画布尺寸：优先 canvas（新模式），回退 layout.pixel_height（旧模式）
    layout = cfg.setdefault("layout", {})
    canvas_params = params.get("canvas")
    if isinstance(canvas_params, dict) and canvas_params.get("pixel_height"):
        cfg["canvas"] = canvas_params
        layout["pixel_height"] = canvas_params.get("pixel_height", default_pixel_height)
    else:
        # 从模板 defaults 的 canvas 中读取
        default_canvas = template_defaults.get("canvas", {})
        if default_canvas:
            cfg["canvas"] = default_canvas
            layout["pixel_height"] = default_canvas.get("pixel_height", default_pixel_height)
        else:
            layout["pixel_height"] = default_pixel_height

    # 需要给 config.py 的校验提供合法的 layout 字段
    if "wrap_chars" not in layout:
        layout["wrap_chars"] = layout_params.get("wrap_chars", default_wrap_chars)

    # scenes: 优先使用前端传入的内容，否则生成单帧预览占位
    scenes_from_params = params.get("scenes")
    if scenes_from_params:
        validated = _validate_scenes(scenes_from_params)
        cfg["scenes"] = [
            {
                "name": s["name"],
                "narration": s["narration"],
                "illustration_keywords": s["illustration_keywords"],
            }
            for s in validated
        ]
    else:
        # 最小占位 scenes，确保 scene_cfg 不为 None
        cfg["scenes"] = [
            {
                "name": scene_name,
                "narration": "精确预览帧",
                "illustration_keywords": [],
            }
        ]

    # 预览优先使用真实插画：先查 .cache，再回退 assets 现有图片，最终才用占位图
    cfg.setdefault("preview", {})["use_illustration_placeholder"] = _prepare_preview_illustrations(
        cfg["scenes"]
    )

    # 支持位置调整：如果 params 中有 positions，写入 layout.positions（覆盖层）
    # positionable_elements 不修改，保持模板默认值
    # 同时对 layout.positions（可能由 params.layout.positions 旁路写入）统一做 sanitize，
    # 过滤掉 x/y 缺失或非数值的非法条目，保证写入临时 YAML 的数据始终合法。
    if "positions" in params and isinstance(params["positions"], dict):
        cfg.setdefault("layout", {})["positions"] = params["positions"]

    from core.utils import sanitize_positions
    raw_pos = cfg.get("layout", {}).get("positions")
    if isinstance(raw_pos, dict):
        sanitized = sanitize_positions(raw_pos)
        # 完整校验：白名单 + min/max 范围；静默移除非法条目（来自配置合并，非直接用户输入）
        try:
            template_defaults = _get_template_defaults(template)
            positionable_elements = template_defaults.get("positionable_elements", [])
            valid_elements = {
                e["id"]: e
                for e in positionable_elements
                if isinstance(e, dict) and e.get("id")
            }
            cleaned: dict = {}
            for elem_id, pos in sanitized.items():
                if elem_id not in valid_elements:
                    log.debug("positions: 移除未知元素 %r", elem_id)
                    continue
                constraints = valid_elements[elem_id]
                x, y = pos["x"], pos["y"]
                min_x = constraints.get("min_x", 0)
                max_x = constraints.get("max_x", 100)
                min_y = constraints.get("min_y", 0)
                max_y = constraints.get("max_y", 100)
                if not (min_x <= x <= max_x):
                    log.debug("positions: 移除越界 %r.x=%s (范围 [%s, %s])", elem_id, x, min_x, max_x)
                    continue
                if not (min_y <= y <= max_y):
                    log.debug("positions: 移除越界 %r.y=%s (范围 [%s, %s])", elem_id, y, min_y, max_y)
                    continue
                cleaned[elem_id] = pos
            cfg["layout"]["positions"] = cleaned
        except Exception:
            # 若获取模板信息失败，使用 sanitize_positions 的结果（类型安全即可）
            cfg["layout"]["positions"] = sanitized

    # 确保 positionable_elements 可写（后续 visibility 和 font_size 覆盖共用）
    pe_list = cfg.get("positionable_elements")
    if not pe_list:
        pe_list = template_defaults.get("positionable_elements", [])
        if pe_list:
            cfg["positionable_elements"] = [dict(e) for e in pe_list]
            pe_list = cfg["positionable_elements"]

    # 应用 element_visibility 覆盖到 positionable_elements
    elem_vis = params.get("element_visibility")
    if isinstance(elem_vis, dict) and elem_vis and pe_list:
        for elem in pe_list:
            eid = elem.get("id", "")
            if eid in elem_vis:
                elem["visible"] = elem_vis[eid]

    # 应用 element_font_sizes 覆盖到 positionable_elements
    elem_fs = params.get("element_font_sizes")
    if isinstance(elem_fs, dict) and elem_fs and pe_list:
        for elem in pe_list:
            eid = elem.get("id", "")
            if eid in elem_fs:
                elem["font_size_override"] = int(elem_fs[eid])

    # 应用 element_colors 覆盖到 positionable_elements（每元素独立颜色）
    elem_colors = params.get("element_colors")
    if isinstance(elem_colors, dict) and elem_colors and pe_list:
        for elem in pe_list:
            eid = elem.get("id", "")
            if eid in elem_colors and elem_colors[eid]:
                elem["color_override"] = str(elem_colors[eid])

    # 应用 element_fonts 覆盖到 positionable_elements（每元素独立字体）
    elem_fonts = params.get("element_fonts")
    if isinstance(elem_fonts, dict) and elem_fonts and pe_list:
        for elem in pe_list:
            eid = elem.get("id", "")
            if eid in elem_fonts and elem_fonts[eid]:
                elem["font_override"] = str(elem_fonts[eid])

    # 应用 animation 参数覆盖
    anim_params = params.get("animation")
    if isinstance(anim_params, dict):
        cfg["animation"] = anim_params

    # 应用 image 参数覆盖（如 image.author_avatar.width_percent）
    image_params = params.get("image")
    if isinstance(image_params, dict):
        cfg["image"] = image_params

    # 应用 illustration 参数覆盖（如 aspect_ratio）
    illus_params = params.get("illustration")
    if isinstance(illus_params, dict) and pe_list:
        for elem in pe_list:
            if elem.get("type") == "illustration":
                if "aspect_ratio" in illus_params:
                    elem["aspect_ratio"] = str(illus_params["aspect_ratio"])

    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="cc_preview_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True)
    return path


def _find_rendered_png(media_dir: str) -> str | None:
    """在 Manim 输出目录中查找生成的 PNG 截图文件"""
    # Manim -s 模式下，截图保存到 images/ 子目录
    search_roots = [
        os.path.join(media_dir, "images"),
        media_dir,
    ]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for fname in sorted(os.listdir(root), reverse=True):
            if fname.lower().endswith(".png"):
                return os.path.join(root, fname)
    return None


def _render_frame(template: str, params: dict) -> bytes:
    """
    核心渲染函数：写 YAML → 调用 Manim -s → 读 PNG → 清理

    返回 PNG bytes，失败时抛出 RuntimeError
    """
    tmp_yaml = None
    tmp_media = None
    try:
        # 1. 获取真实画布尺寸（用于 -r 参数确保 Manim camera 初始化正确）
        template_defaults = _get_template_defaults(template)
        canvas = params.get("canvas") or template_defaults.get("canvas", {})
        pw = canvas.get("pixel_width", 1080)
        ph = canvas.get("pixel_height",
                        template_defaults.get("layout", {}).get("pixel_height", 1440))

        # 2. 写临时 YAML（保持原始分辨率）
        tmp_yaml = _write_temp_yaml(template, params)
        log.info("临时配置: %s (画布 %dx%d)", tmp_yaml, pw, ph)

        # 3. 用 load_config 获取 manim_script 路径
        from core.config import load_config
        os.environ["CARD_CAROUSEL_PROJECT_DIR"] = str(PROJECT_DIR)
        cfg = load_config(tmp_yaml)
        manim_script = os.path.join(str(PROJECT_DIR), cfg["manim_script"])
        if not os.path.isfile(manim_script):
            raise RuntimeError(f"找不到 Manim 脚本: {manim_script}")

        # 4. 找到 Scene 类名
        scene_class = _resolve_scene_class(template, manim_script)
        log.info("Scene 类名: %s", scene_class)

        # 5. 临时 media 输出目录
        tmp_media = tempfile.mkdtemp(prefix="cc_media_")

        # 6. 组装 manim 命令（-r 传原始画布尺寸，确保 camera 初始化正确）
        cmd = [
            sys.executable, "-m", "manim",
            "-s",                     # screenshot / last-frame 模式
            "-r", f"{pw},{ph}",       # Manim -r 格式: W,H（原始分辨率）
            "--format", "png",
            "--media_dir", tmp_media,
            "-o", "preview_frame",
            manim_script,
            scene_class,
        ]

        env = os.environ.copy()
        env["CARD_CAROUSEL_PROJECT_DIR"] = str(PROJECT_DIR)
        env["CARD_CAROUSEL_CONFIG_PATH"] = tmp_yaml
        # 禁用音频（截图不需要），但 timing 文件需要是有效 JSON
        env["CARD_CAROUSEL_AUDIO_DIR"] = tmp_media
        # 创建空的 timing 文件
        timing_file = os.path.join(tmp_media, "_timing.json")
        with open(timing_file, "w") as f:
            f.write("{}")
        env["CARD_CAROUSEL_TIMING_FILE"] = timing_file
        # 预览模式：让 Manim 优先从 .cache/preview_assets 读取插画
        env["CARD_CAROUSEL_PREVIEW_ASSETS_DIR"] = str(_PREVIEW_ASSETS_DIR)

        log.info("执行: %s", " ".join(cmd))
        t0 = time.time()

        proc = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_DIR),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = proc.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise RuntimeError("Manim 渲染超时（>120s）")

        elapsed = time.time() - t0
        log.info("Manim 完成，耗时 %.1fs，returncode=%d", elapsed, proc.returncode)

        if proc.returncode != 0:
            stderr_tail = stderr_bytes[-2000:].decode("utf-8", errors="replace") if stderr_bytes else "(无错误输出)"
            raise RuntimeError(f"Manim 渲染失败 (exit {proc.returncode}):\n{stderr_tail}")

        # 6. 查找输出 PNG
        png_path = _find_rendered_png(tmp_media)
        if not png_path:
            # 递归搜索整个 tmp_media
            for root, _dirs, files in os.walk(tmp_media):
                for fname in files:
                    if fname.lower().endswith(".png"):
                        png_path = os.path.join(root, fname)
                        break
                if png_path:
                    break

        if not png_path:
            raise RuntimeError("Manim 完成但找不到输出 PNG 文件")

        log.info("找到 PNG: %s", png_path)

        # PIL 缩小到预览尺寸（保持比例，减小传输体积）
        from PIL import Image as PILImage
        import io
        preview_w = 540
        preview_h = int(preview_w * ph / pw)
        img = PILImage.open(png_path)
        if img.width > preview_w:
            img = img.resize((preview_w, preview_h), PILImage.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    finally:
        # 清理临时文件
        if tmp_yaml and os.path.exists(tmp_yaml):
            os.unlink(tmp_yaml)
        if tmp_media and os.path.isdir(tmp_media):
            shutil.rmtree(tmp_media, ignore_errors=True)


def _extract_video_frame(template: str, scene_index: int) -> bytes:
    """
    从已有渲染视频中抽取指定帧（ffmpeg）

    查找路径: 复用 core.config.load_config 推导的 _render_dir/{SceneClass}.mp4
    """
    from core.config import load_config
    import yaml

    cfg_fd, cfg_path = tempfile.mkstemp(suffix=".yaml", prefix="cc_preview_video_")
    try:
        with os.fdopen(cfg_fd, "w", encoding="utf-8") as f:
            yaml.dump({"template": template, "render_quality": "l"}, f, allow_unicode=True)
        loaded_cfg = load_config(cfg_path)
    finally:
        if os.path.exists(cfg_path):
            os.unlink(cfg_path)

    render_dir = Path(loaded_cfg["_render_dir"])
    scene_classes = _resolve_scene_classes(template)
    if not scene_classes:
        raise RuntimeError(f"模板 {template!r} 未声明 Scene 类")

    if scene_index < len(scene_classes):
        scene_class = scene_classes[scene_index]
    else:
        scene_class = scene_classes[-1]

    video_path: Path | None = None
    if render_dir.is_dir():
        exact = render_dir / f"{scene_class}.mp4"
        if exact.is_file():
            video_path = exact
        else:
            matched = sorted(render_dir.glob(f"{scene_class}*.mp4"))
            if matched:
                video_path = matched[0]

    if not video_path:
        raise RuntimeError(
            "找不到已渲染视频 "
            f"(template={template}, scene={scene_class}, render_dir={render_dir})"
        )

    log.info("抽帧来源: %s", video_path)
    fd, out_path = tempfile.mkstemp(suffix=".png", prefix="cc_frame_")
    os.close(fd)
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            out_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 失败: {result.stderr[-1000:]}")
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(out_path):
            os.unlink(out_path)


# ── HTTP 请求处理器 ────────────────────────────────────────────────────────────

class PreviewHandler(http.server.BaseHTTPRequestHandler):
    """处理 /api/* 请求 + 静态文件服务"""

    # 静默 access log（渲染期间日志太多会干扰）
    def log_message(self, fmt, *args):  # noqa: D401
        log.debug(fmt, *args)

    # ── CORS ─────────────────────────────────────────────────────────────────
    def _set_cors(self):
        origin = self.headers.get("Origin")
        if origin in ALLOWED_CORS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_CORS_ORIGINS:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    # ── 响应工具 ─────────────────────────────────────────────────────────────
    def _send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_png(self, data: bytes):
        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def _send_error_json(self, status: int, message: str):
        self._send_json(status, {"error": message})

    # ── GET 路由 ──────────────────────────────────────────────────────────────
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/video_frame":
            self._handle_video_frame(parsed.query)
        elif path == "/api/template_defaults":
            self._handle_template_defaults(parsed.query)
        elif path == "/api/templates":
            self._handle_list_templates()
        elif path == "/api/template_manifest":
            self._handle_template_manifest(parsed.query)
        elif path == "/api/health":
            self._send_json(200, {"status": "ok", "port": PORT})
        elif path == "/api/list-images":
            self._handle_list_images()
        elif path == "/api/user_template":
            self._handle_get_user_template(parsed.query)
        else:
            self._serve_static(path)

    def _handle_video_frame(self, query_string: str):
        qs = urllib.parse.parse_qs(query_string)
        template = qs.get("template", ["minimal-insight"])[0]
        scene_index_raw = qs.get("scene_index", ["0"])[0]
        try:
            scene_index = int(scene_index_raw)
        except ValueError:
            self._send_error_json(400, f"scene_index 必须是整数，当前值: {scene_index_raw!r}")
            return
        if scene_index < 0:
            self._send_error_json(400, f"scene_index 必须是非负整数，当前值: {scene_index_raw!r}")
            return
        try:
            png_bytes = _extract_video_frame(template, scene_index)
            self._send_png(png_bytes)
        except ValueError as exc:
            log.warning("video_frame 参数错误: %s", exc)
            self._send_error_json(400, _client_error_message("参数错误", exc))
        except Exception:
            log.exception("video_frame 失败")
            self._send_error_json(500, _client_error_message("获取视频帧失败"))

    def _handle_template_defaults(self, query_string: str):
        qs = urllib.parse.parse_qs(query_string)
        template = qs.get("template", ["minimal-insight"])[0]
        try:
            defaults = _get_template_defaults(template)
            # 合并用户自定义覆盖（如果存在）
            override_path = _USER_TEMPLATES_DIR / f"{template}.yaml"
            has_user_override = override_path.exists()
            if has_user_override:
                import yaml as _yaml
                with open(override_path, encoding="utf-8") as f:
                    user_data = _yaml.safe_load(f)
                if isinstance(user_data, dict):
                    defaults = _deep_merge(defaults, user_data)
            # positionable_elements 只通过 /api/template_manifest 暴露
            defaults_response = {k: v for k, v in defaults.items() if k != "positionable_elements"}
            self._send_json(200, {
                "template": template,
                "defaults": defaults_response,
                "has_user_override": has_user_override,
            })
        except ValueError as exc:
            log.warning("template_defaults 参数错误: %s", exc)
            self._send_error_json(400, _client_error_message("参数错误", exc))
        except Exception:
            log.exception("template_defaults 失败")
            self._send_error_json(500, _client_error_message("加载模板默认参数失败"))

    def _handle_list_templates(self):
        """GET /api/templates — 返回已注册模板列表"""
        try:
            from templates import get_all_templates
            templates = get_all_templates()
            result = []
            for template_id, template_obj in templates.items():
                result.append({
                    "id": template_id,
                    "name": template_obj.name,
                    "description": getattr(template_obj, "description", ""),
                })
            self._send_json(200, {"templates": result})
        except Exception:
            log.exception("list_templates 失败")
            self._send_error_json(500, _client_error_message("获取模板列表失败"))

    def _handle_list_images(self):
        """GET /api/list-images — 扫描 assets/ 目录返回可用图片列表"""
        try:
            assets_dir = os.path.join(PROJECT_DIR, "assets")
            images = []
            if os.path.isdir(assets_dir):
                img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
                for root, _dirs, files in os.walk(assets_dir):
                    for fname in sorted(files):
                        if os.path.splitext(fname)[1].lower() in img_exts:
                            rel = os.path.relpath(os.path.join(root, fname), PROJECT_DIR)
                            images.append(rel)
            self._send_json(200, {"images": sorted(images)})
        except Exception:
            log.exception("list-images 失败")
            self._send_error_json(500, _client_error_message("获取图片列表失败"))

    def _handle_template_manifest(self, query_string: str):
        """GET /api/template_manifest?template=xxx — 返回模板的 positionable_elements 元数据"""
        qs = urllib.parse.parse_qs(query_string)
        template_id = qs.get("template", ["minimal-insight"])[0]
        try:
            from templates import get_template
            template_obj = get_template(template_id)
            if template_obj is None:
                self._send_error_json(404, f"模板不存在: {template_id}")
                return

            # 获取可定位元素元数据 + 配色方案 + 画布
            defaults = template_obj.get_default_config()
            elements = defaults.get("positionable_elements", [])
            response = {
                "template": template_id,
                "positionable_elements": elements,
            }
            if "color_palettes" in defaults:
                response["color_palettes"] = defaults["color_palettes"]
            if "canvas" in defaults:
                response["canvas"] = defaults["canvas"]
            self._send_json(200, response)
        except ValueError as exc:
            log.warning("template_manifest 参数错误: %s", exc)
            self._send_error_json(400, _client_error_message("参数错误", exc))
        except Exception:
            log.exception("template_manifest 失败")
            self._send_error_json(500, _client_error_message("获取模板元数据失败"))

    def _serve_static(self, path: str):
        # 根目录 → template_preview.html
        if path in ("/", ""):
            path = "/template_preview.html"

        # 安全校验：限制在 tools/ 目录
        rel = path.lstrip("/")
        file_path = (TOOLS_DIR / rel).resolve()
        try:
            file_path.relative_to(TOOLS_DIR.resolve())
        except ValueError:
            self._send_error_json(403, "禁止访问")
            return

        if not file_path.is_file():
            self._send_error_json(404, f"文件不存在: {rel}")
            return

        mime, _ = mimetypes.guess_type(str(file_path))
        mime = mime or "application/octet-stream"
        data = file_path.read_bytes()

        self.send_response(200)
        self._set_cors()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ── POST 路由 ─────────────────────────────────────────────────────────────
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/api/render_frame":
            self._handle_render_frame()
        elif path == "/api/upload-image":
            self._handle_upload_image()
        elif path == "/api/save_template":
            self._handle_save_template()
        else:
            self._send_error_json(404, f"未知 API: {path}")

    def _handle_render_frame(self):
        # 读取请求体
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_error_json(400, "Content-Length 必须是整数")
            return

        if length == 0:
            self._send_error_json(400, "缺少请求体")
            return
        try:
            body = self.rfile.read(length)
            payload = json.loads(body)
        except Exception as exc:
            log.warning("JSON 解析失败: %s", exc)
            self._send_error_json(400, _client_error_message("参数错误", exc))
            return

        if not isinstance(payload, dict):
            self._send_error_json(400, "请求体必须是 JSON 对象")
            return

        template = payload.get("template", "minimal-insight")
        params = payload.get("params", {})
        try:
            _validate_preview_params(params)
            # 校验 positions 参数
            if "positions" in params:
                _validate_positions(params["positions"], template)
        except ValueError as exc:
            log.warning("render_frame 参数错误: %s", exc)
            self._send_error_json(400, _client_error_message("参数错误", exc))
            return

        log.info("收到渲染请求: template=%s", template)

        # 渲染锁：同一时刻只有一个渲染任务，新请求立即返回 503（配合前端 last-write-wins）
        acquired = _render_lock.acquire(blocking=False)
        if not acquired:
            self._send_error_json(503, "渲染队列繁忙，请稍后重试")
            return

        try:
            png_bytes = _render_frame(template, params)
            self._send_png(png_bytes)
        except ValueError as exc:
            log.warning("render_frame 参数错误: %s", exc)
            self._send_error_json(400, _client_error_message("参数错误", exc))
        except Exception:
            log.exception("render_frame 失败")
            self._send_error_json(500, _client_error_message("渲染失败"))
        finally:
            _render_lock.release()

    def _handle_upload_image(self):
        """POST /api/upload-image — 接收图片文件，保存到 assets/uploads/，返回相对路径"""
        import cgi

        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_error_json(400, "需要 multipart/form-data 格式")
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_error_json(400, "Content-Length 必须是整数")
            return

        if length == 0 or length > 20 * 1024 * 1024:  # 最大 20MB
            self._send_error_json(400, "文件大小必须在 1 字节到 20MB 之间")
            return

        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": content_type,
                },
            )
            file_item = form["file"]
            if not file_item.filename:
                self._send_error_json(400, "未找到上传文件")
                return

            # 安全文件名
            original_name = os.path.basename(file_item.filename)
            name, ext = os.path.splitext(original_name)
            ext = ext.lower()
            if ext not in (".png", ".jpg", ".jpeg", ".webp"):
                self._send_error_json(400, f"不支持的图片格式: {ext}")
                return

            safe_name = re.sub(r"[^\w\-.]", "_", name)
            # 避免重名：加时间戳
            ts = int(time.time())
            filename = f"{safe_name}_{ts}{ext}"

            _UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
            dest = _UPLOADS_DIR / filename
            with open(dest, "wb") as f:
                f.write(file_item.file.read())

            rel_path = f"assets/uploads/{filename}"
            log.info("图片上传成功: %s", rel_path)
            self._send_json(200, {"path": rel_path})

        except KeyError:
            self._send_error_json(400, "请求中缺少 'file' 字段")
        except Exception:
            log.exception("upload-image 失败")
            self._send_error_json(500, _client_error_message("上传失败"))

    def _handle_save_template(self):
        """POST /api/save_template — 将编辑器参数保存为用户自定义模板覆盖

        保存到 .user/templates/<template>.yaml，pipeline 运行时会读取并合并。
        合并优先级：git defaults < .user/templates/<name>.yaml < content config
        """
        import yaml as _yaml

        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            self._send_error_json(400, "Content-Length 必须是整数")
            return

        if length == 0:
            self._send_error_json(400, "缺少请求体")
            return

        try:
            body = self.rfile.read(length)
            payload = json.loads(body)
        except Exception as exc:
            self._send_error_json(400, _client_error_message("参数错误", exc))
            return

        template = payload.get("template", "").strip()
        params = payload.get("params")
        if not template or not isinstance(params, dict):
            self._send_error_json(400, "需要 template (字符串) 和 params (对象)")
            return

        # 安全校验：模板名只允许字母数字和连字符
        if not re.match(r"^[a-zA-Z0-9_-]+$", template):
            self._send_error_json(400, f"模板名不合法: {template!r}")
            return

        # 构建要保存的覆盖配置
        override = {}
        if "layout" in params and isinstance(params["layout"], dict):
            override["layout"] = params["layout"]
        if "brand" in params and isinstance(params["brand"], dict):
            override["brand"] = params["brand"]
        if "footer_tags" in params:
            override.setdefault("brand", {})["footer_tags"] = params["footer_tags"]
        # 元素可见性、字号、位置覆盖
        if "element_visibility" in params and isinstance(params["element_visibility"], dict):
            override["element_visibility"] = params["element_visibility"]
        if "element_font_sizes" in params and isinstance(params["element_font_sizes"], dict):
            override["element_font_sizes"] = params["element_font_sizes"]
        if "element_colors" in params and isinstance(params["element_colors"], dict):
            override["element_colors"] = params["element_colors"]
        if "element_fonts" in params and isinstance(params["element_fonts"], dict):
            override["element_fonts"] = params["element_fonts"]
        if "cover" in params and isinstance(params["cover"], dict):
            override["cover"] = params["cover"]
        if "positions" in params and isinstance(params["positions"], dict):
            override["positions"] = params["positions"]
        # 动画、图片、插画参数
        if "animation" in params and isinstance(params["animation"], dict):
            override["animation"] = params["animation"]
        if "image" in params and isinstance(params["image"], dict):
            override["image"] = params["image"]
        if "illustration" in params and isinstance(params["illustration"], dict):
            override["illustration_display"] = params["illustration"]

        if not override:
            self._send_error_json(400, "没有可保存的参数")
            return

        try:
            _USER_TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
            dest = _USER_TEMPLATES_DIR / f"{template}.yaml"
            with open(dest, "w", encoding="utf-8") as f:
                _yaml.dump(override, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
            log.info("用户模板覆盖已保存: %s", dest)
            self._send_json(200, {"saved": str(dest.relative_to(PROJECT_DIR))})
        except Exception:
            log.exception("save_template 失败")
            self._send_error_json(500, _client_error_message("保存模板失败"))

    def _handle_get_user_template(self, query_string: str):
        """GET /api/user_template?template=xxx — 返回用户自定义模板覆盖（如有）"""
        qs = urllib.parse.parse_qs(query_string)
        template = qs.get("template", [""])[0].strip()
        if not template:
            self._send_error_json(400, "缺少 template 参数")
            return

        override_path = _USER_TEMPLATES_DIR / f"{template}.yaml"
        if not override_path.exists():
            self._send_json(200, {"template": template, "override": None})
            return

        try:
            import yaml as _yaml
            with open(override_path, encoding="utf-8") as f:
                data = _yaml.safe_load(f)
            self._send_json(200, {"template": template, "override": data or {}})
        except Exception:
            log.exception("读取用户模板失败")
            self._send_error_json(500, _client_error_message("读取用户模板失败"))


# ── 入口 ──────────────────────────────────────────────────────────────────────

class ThreadedHTTPServer(http.server.ThreadingHTTPServer):
    """多线程 HTTP 服务器（允许并发静态文件请求，渲染由锁串行化）"""
    daemon_threads = True
    allow_reuse_address = True


def main():
    server = ThreadedHTTPServer((PREVIEW_HOST, PORT), PreviewHandler)
    log.info("精确预览服务器启动: http://%s:%d", PREVIEW_HOST, PORT)
    log.info("  静态文件:   http://%s:%d/template_preview.html", PREVIEW_HOST, PORT)
    log.info("  渲染 API:   POST http://%s:%d/api/render_frame", PREVIEW_HOST, PORT)
    log.info("  视频帧 API: GET  http://%s:%d/api/video_frame?template=xxx", PREVIEW_HOST, PORT)
    log.info("项目根目录: %s", PROJECT_DIR)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("服务器停止")


if __name__ == "__main__":
    main()
