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


def _load_user_override(template_name: str, project_dir: str) -> dict:
    """加载用户自定义模板覆盖（.user/templates/<name>.yaml），不存在则返回空 dict"""
    override_path = os.path.join(project_dir, ".user", "templates", f"{template_name}.yaml")
    if not os.path.exists(override_path):
        return {}
    try:
        with open(override_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _apply_template(cfg: dict, project_dir: str) -> dict:
    """加载模板默认配置并与用户配置合并

    合并优先级: template.defaults < .user/templates/<name>.yaml < 用户 config
    """
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

    # 加载用户自定义覆盖（预览编辑器保存的）
    user_override = _load_user_override(template_name, project_dir)

    # 合并: template defaults < user override < user config
    merged = _deep_merge(defaults, user_override)
    merged = _deep_merge(merged, cfg)

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

    # ── 应用 element_visibility / element_font_sizes 到 positionable_elements ──
    pe_list = merged.get("positionable_elements")
    if isinstance(pe_list, list) and pe_list:
        # 深拷贝元素列表，避免修改模板原始对象
        pe_list = [dict(e) for e in pe_list]
        merged["positionable_elements"] = pe_list

        # element_visibility 覆盖
        elem_vis = merged.pop("element_visibility", None)
        if isinstance(elem_vis, dict) and elem_vis:
            for elem in pe_list:
                eid = elem.get("id", "")
                if eid in elem_vis:
                    elem["visible"] = elem_vis[eid]

        # element_font_sizes 覆盖
        elem_fs = merged.pop("element_font_sizes", None)
        if isinstance(elem_fs, dict) and elem_fs:
            for elem in pe_list:
                eid = elem.get("id", "")
                if eid in elem_fs:
                    elem["font_size"] = elem_fs[eid]

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


def _load_brand(project_dir: str) -> dict:
    """加载项目根目录的 brand.yaml（作者资产层），不存在则返回空 dict"""
    brand_path = os.path.join(project_dir, "brand.yaml")
    if not os.path.exists(brand_path):
        return {}
    try:
        with open(brand_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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

    # 加载 brand.yaml（作者资产层，最低优先级）
    brand = _load_brand(project_dir)
    cfg["_brand"] = brand

    # ── 模板模式：有 template 字段则加载模板默认值并合并 ──
    if "template" in cfg:
        cfg = _apply_template(cfg, project_dir)
        cfg["_project_dir"] = project_dir
        cfg["_config_path"] = config_path
        cfg.setdefault("_brand", brand)

    # 归一化 layout：确保为 dict（null/缺失都归为 {}）
    if not isinstance(cfg.get("layout"), dict):
        cfg["layout"] = {}

    # 清洗 layout.positions：过滤掉 x/y 缺失或非数值的非法条目
    raw_positions = cfg["layout"].get("positions")
    if raw_positions is not None:
        cfg["layout"]["positions"] = sanitize_positions(raw_positions)

    cfg.setdefault("render_quality", "h")
    cfg.setdefault("output", {})
    cfg["output"].setdefault("speed", 1.0)
    cfg["output"].setdefault("format", "mp4")
    # 输出目录默认为调用者的工作目录（而非项目目录），
    # 这样作为 skill 使用时视频保存在用户当前目录
    cfg["output"].setdefault("dir", os.getcwd())

    # voice 合并优先级: content yaml > brand.yaml > 硬编码默认值
    cfg.setdefault("voice", {})
    brand_voice = brand.get("voice", {})
    for k, v in brand_voice.items():
        cfg["voice"].setdefault(k, v)
    cfg["voice"].setdefault("provider", "volcengine")
    cfg["voice"].setdefault("voice_type", "zh_male_ruyayichen_uranus_bigtts")
    cfg["voice"].setdefault("cluster", "volcano_tts")
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

    # Manim 按 quality preset 的 pixel_height 命名渲染目录
    # 注意：shared.py 的 construct() 会在运行时覆盖 config.pixel_height，
    # 但 Manim 的输出目录在此之前就已根据 -ql/-qm/-qh 的 preset 值确定。
    # 因此这里必须用 Manim quality preset 的高度，不是模板的 pixel_height。
    manim_quality_heights = {"l": 480, "m": 720, "h": 1080}
    fps_map = {"l": 15, "m": 30, "h": 60}
    manim_ph = manim_quality_heights.get(cfg["render_quality"], 480)
    fps = fps_map.get(cfg["render_quality"], 15)
    quality_dir = f"{manim_ph}p{fps}"
    cfg["_render_dir"] = os.path.join(media_base, quality_dir)
    cfg["_voiced_dir"] = os.path.join(media_base, "voiced")

    return cfg
