"""
配置加载 — 读取 YAML + 补全默认值 + 派生路径
同时负责加载项目根目录的 .env 文件

合并优先级: template.defaults < 用户 config（用户覆盖模板默认值）
"""

import os

import yaml
from dotenv import load_dotenv

from core.utils import sanitize_positions


def _load_env(project_dir: str) -> None:
    """加载项目根目录的 .env 文件（如果存在）"""
    env_path = os.path.join(project_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)


def _deep_merge(base: dict, override: dict) -> dict:
    """
    递归合并：override 中的值覆盖 base，返回新 dict

    特殊处理：
    - None 值会覆盖 base 中的值（用于清空模板默认值）
    - 嵌套 dict 递归合并
    """
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            # 允许 None 覆盖，实现清空语义
            result[key] = val
    return result


def _apply_template(cfg: dict, project_dir: str) -> dict:
    """加载模板默认配置并与用户配置合并"""
    import sys
    # 确保项目根目录在 sys.path，使 templates 包可导入
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

    from templates import get_template
    template_name = cfg["template"]
    tmpl = get_template(template_name)
    defaults = dict(tmpl.get_default_config())  # 深拷贝，避免修改模板原始对象

    # brand_defaults → brand（模板默认品牌）
    brand_defaults = defaults.pop("brand_defaults", {})

    # 合并: template defaults < user config
    merged = _deep_merge(defaults, cfg)

    # brand: 用模板 brand_defaults 填充用户未设置的字段
    user_brand = merged.get("brand")
    if not isinstance(user_brand, dict):
        merged["brand"] = dict(brand_defaults)
    else:
        merged["brand"] = _deep_merge(brand_defaults, user_brand)

    # 自动设置 manim_script 指向模板 scene.py
    if "manim_script" not in cfg:
        merged["manim_script"] = tmpl.get_manim_script()

    # pixel_height 由模板固定（真相源唯一）：忽略用户 config 中的覆盖，
    # 但若 canvas 指定了尺寸（预览编辑器），以 canvas 为准以保持渲染目录一致
    template_pixel_height = defaults.get("layout", {}).get("pixel_height")
    if template_pixel_height is not None:
        if not isinstance(merged.get("layout"), dict):
            merged["layout"] = {}
        merged["layout"]["pixel_height"] = template_pixel_height

    canvas = merged.get("canvas", {})
    if isinstance(canvas, dict):
        if "pixel_height" in canvas:
            if not isinstance(merged.get("layout"), dict):
                merged["layout"] = {}
            merged["layout"]["pixel_height"] = canvas["pixel_height"]
        if "pixel_width" in canvas:
            if not isinstance(merged.get("layout"), dict):
                merged["layout"] = {}
            merged["layout"]["pixel_width"] = canvas["pixel_width"]

    return merged


def _find_project_dir(config_path: str) -> str:
    """
    推断项目根目录：
    1. 优先使用环境变量 CARD_CAROUSEL_PROJECT_DIR
    2. 否则从 config 文件向上查找包含 pipeline.py 的目录（最多 3 层）
    3. 回退到 config 文件所在目录
    """
    env_dir = os.environ.get("CARD_CAROUSEL_PROJECT_DIR")
    if env_dir:
        return os.path.abspath(env_dir)

    candidate = os.path.dirname(config_path)
    for _ in range(3):
        if os.path.exists(os.path.join(candidate, "pipeline.py")):
            return candidate
        parent = os.path.dirname(candidate)
        if parent == candidate:
            break
        candidate = parent
    return os.path.dirname(config_path)


def load_config(path: str) -> dict:
    """加载 YAML 配置，返回 dict 并补全默认值"""
    config_path = os.path.abspath(path)
    project_dir = _find_project_dir(config_path)

    # 加载 .env（在读配置前确保环境变量已就位）
    _load_env(project_dir)

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    cfg["_project_dir"] = project_dir
    cfg["_config_path"] = config_path

    # ── 模板模式：有 template 字段则加载模板默认值并合并 ──
    if "template" in cfg:
        cfg = _apply_template(cfg, project_dir)
        cfg["_project_dir"] = project_dir
        cfg["_config_path"] = config_path

    # 归一化 layout：确保为 dict（null/缺失都归为 {}）
    if not isinstance(cfg.get("layout"), dict):
        cfg["layout"] = {}

    # 清洗 layout.positions：过滤掉 x/y 缺失或非数值的非法条目
    raw_positions = cfg["layout"].get("positions")
    if raw_positions is not None:
        cfg["layout"]["positions"] = sanitize_positions(raw_positions)

    cfg.setdefault("render_quality", "l")
    cfg.setdefault("output", {})
    cfg["output"].setdefault("speed", 1.0)
    cfg["output"].setdefault("format", "mp4")
    # 输出目录默认为调用者的工作目录（而非项目目录），
    # 这样作为 skill 使用时视频保存在用户当前目录
    cfg["output"].setdefault("dir", os.getcwd())

    cfg.setdefault("voice", {})
    cfg["voice"].setdefault("provider", "volcengine")
    cfg["voice"].setdefault("voice_type", "zh-CN-YunxiNeural")
    cfg["voice"].setdefault("speed", 1.0)

    cfg.setdefault("illustrations", {})
    layout_cfg = cfg.get("layout")
    if layout_cfg:
        # 向后兼容：旧配置可能只有 layout 但缺少 pixel_height
        layout_cfg.setdefault("pixel_height", 1440)
        pixel_height = layout_cfg.get("pixel_height")
        if not (
            isinstance(pixel_height, int)
            and not isinstance(pixel_height, bool)
            and pixel_height > 0
        ):
            raise ValueError(
                f"layout.pixel_height 必须为正整数，当前值: {pixel_height!r}"
            )

        wrap_chars = layout_cfg.get("wrap_chars")
        if not (
            isinstance(wrap_chars, int)
            and not isinstance(wrap_chars, bool)
            and wrap_chars > 0
        ):
            raise ValueError(f"layout.wrap_chars 必须为正整数，当前值: {wrap_chars!r}")
        expected_max_chars = wrap_chars * 2
        max_chars_per_card = layout_cfg.get("max_chars_per_card")
        if max_chars_per_card is None:
            layout_cfg["max_chars_per_card"] = expected_max_chars
            max_chars_per_card = expected_max_chars
        elif not (
            isinstance(max_chars_per_card, int)
            and not isinstance(max_chars_per_card, bool)
            and max_chars_per_card > 0
        ):
            raise ValueError(
                "layout.max_chars_per_card 必须为正整数，"
                f"当前值: {max_chars_per_card!r}"
            )

        if max_chars_per_card != expected_max_chars:
            print(
                "警告: layout.max_chars_per_card="
                f"{max_chars_per_card} 与 layout.wrap_chars*2={expected_max_chars} 不一致，已强制修正"
            )
            layout_cfg["max_chars_per_card"] = expected_max_chars

    # ── 路径安全校验 ──
    # manim_script 必须在项目目录内
    script_path = os.path.normpath(os.path.join(project_dir, cfg["manim_script"]))
    if not script_path.startswith(os.path.normpath(project_dir)):
        raise ValueError(f"manim_script 路径越界: {cfg['manim_script']!r}")

    # 派生路径
    # Manim 固定用脚本文件名（不含 .py）作 media 子目录名，
    # 这里必须与 Manim 的行为保持一致，否则 voice 步骤找不到渲染产物
    script_base = cfg["manim_script"].replace(".py", "").replace("/", os.sep)
    media_key = os.path.basename(script_base)
    media_base = os.path.join(project_dir, "media", "videos", media_key)
    cfg["_media_base"] = media_base
    cfg["_audio_dir"] = os.path.join(media_base, "audio")
    cfg["_timing_file"] = os.path.join(media_base, "_timing.json")

    # Manim 按 {像素高度}p{fps} 命名渲染目录（如 1440p15、1920p15）
    # 不同模板分辨率不同，自动检测实际目录而非硬编码
    layout_val = cfg.get("layout")
    if not isinstance(layout_val, dict):
        layout_val = {}
    pixel_height = layout_val.get("pixel_height", 1440)
    fps_map = {"l": 15, "m": 30, "h": 60}
    fps = fps_map.get(cfg["render_quality"], 15)
    quality_dir = f"{pixel_height}p{fps}"
    cfg["_render_dir"] = os.path.join(media_base, quality_dir)
    cfg["_voiced_dir"] = os.path.join(media_base, "voiced")

    return cfg
