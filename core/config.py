"""
配置加载 — 读取 YAML + 补全默认值 + 派生路径
同时负责加载项目根目录的 .env 文件

合并优先级: template.defaults < 用户 config（用户覆盖模板默认值）
"""

import os

import yaml
from dotenv import load_dotenv


def _load_env(project_dir: str) -> None:
    """加载项目根目录的 .env 文件（如果存在）"""
    env_path = os.path.join(project_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 中的值覆盖 base，返回新 dict"""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
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
    defaults = tmpl.get_default_config()

    # brand_defaults → brand（模板默认品牌）
    brand_defaults = defaults.pop("brand_defaults", {})

    # 合并: template defaults < user config
    merged = _deep_merge(defaults, cfg)

    # brand: 用模板 brand_defaults 填充用户未设置的字段
    if "brand" not in merged:
        merged["brand"] = brand_defaults
    else:
        merged["brand"] = _deep_merge(brand_defaults, merged["brand"])

    # 自动设置 manim_script 指向模板 scene.py
    if "manim_script" not in cfg:
        merged["manim_script"] = tmpl.get_manim_script()

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

    cfg.setdefault("render_quality", "l")
    cfg.setdefault("output", {})
    cfg["output"].setdefault("speed", 1.0)
    cfg["output"].setdefault("format", "mp4")
    cfg["output"].setdefault("dir", project_dir)

    cfg.setdefault("voice", {})
    cfg["voice"].setdefault("provider", "edge")
    cfg["voice"].setdefault("voice_type", "zh-CN-YunxiNeural")
    cfg["voice"].setdefault("speed", 1.0)

    cfg.setdefault("illustrations", {})

    # 派生路径
    # 模板模式用模板名作 media 目录名（避免多模板共用 scene.py 时目录冲突）
    # 旧模式用脚本文件名（保持兼容）
    if "template" in cfg:
        media_key = cfg["template"].replace("-", "_")
    else:
        script_base = cfg["manim_script"].replace(".py", "").replace("/", os.sep)
        media_key = os.path.basename(script_base)
    media_base = os.path.join(project_dir, "media", "videos", media_key)
    cfg["_media_base"] = media_base
    cfg["_audio_dir"] = os.path.join(media_base, "audio")
    cfg["_timing_file"] = os.path.join(media_base, "_timing.json")

    # Manim 按像素高度命名目录: 1440p15 对应 1080x1440 竖屏
    q_map = {"l": "1440p15", "m": "1440p30", "h": "1440p60"}
    quality_dir = q_map.get(cfg["render_quality"], "1440p15")
    cfg["_render_dir"] = os.path.join(media_base, quality_dir)
    cfg["_voiced_dir"] = os.path.join(media_base, "voiced")

    return cfg
