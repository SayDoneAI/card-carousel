"""
配置加载 — 读取 YAML + 补全默认值 + 派生路径
同时负责加载项目根目录的 .env 文件
"""

import os

import yaml
from dotenv import load_dotenv


def _load_env(project_dir: str) -> None:
    """加载项目根目录的 .env 文件（如果存在）"""
    env_path = os.path.join(project_dir, ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path, override=True)


def load_config(path: str) -> dict:
    """加载 YAML 配置，返回 dict 并补全默认值"""
    config_path = os.path.abspath(path)
    project_dir = os.path.dirname(config_path)

    # 加载 .env（在读配置前确保环境变量已就位）
    _load_env(project_dir)

    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

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
    script_base = cfg["manim_script"].replace(".py", "")
    media_base = os.path.join(project_dir, "media", "videos", script_base)
    cfg["_media_base"] = media_base
    cfg["_audio_dir"] = os.path.join(media_base, "audio")
    cfg["_timing_file"] = os.path.join(media_base, "_timing.json")

    # Manim 按像素高度命名目录: 1440p15 对应 1080x1440 竖屏
    q_map = {"l": "1440p15", "m": "1440p30", "h": "1440p60"}
    quality_dir = q_map.get(cfg["render_quality"], "1440p15")
    cfg["_render_dir"] = os.path.join(media_base, quality_dir)
    cfg["_voiced_dir"] = os.path.join(media_base, "voiced")

    return cfg
