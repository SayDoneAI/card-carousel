"""
图文卡片口播视频 — 生成管线
用法:
  python pipeline.py config.yaml              # 全量执行
  python pipeline.py config.yaml --step tts   # 只跑 TTS
  python pipeline.py config.yaml --step illustrations  # 只生成插画
  python pipeline.py config.yaml --step render # 只渲染 Manim
  python pipeline.py config.yaml --step voice  # 合并音频到视频
  python pipeline.py config.yaml --step concat # 拼接最终视频

流程: tts → illustrations → render → voice → concat
"""

import argparse
import asyncio
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml


# ── 加载项目 .env ──
from dotenv import load_dotenv
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    load_dotenv(dotenv_path=_env_path, override=True)


# ── 工具函数 ────────────────────────────────────────────────


def get_duration(path):
    """获取音视频文件时长（秒）"""
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def sanitize_filename(name):
    """将关键词转为安全的文件名"""
    return re.sub(r'[^\w\-]', '_', name.strip().lower())


def load_config(path):
    """加载 YAML 配置，返回 dict 并补全默认值"""
    config_path = os.path.abspath(path)
    project_dir = os.path.dirname(config_path)

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


def _output_name(cfg, speed=1.0):
    """生成输出文件名"""
    date_str = datetime.now().strftime("%Y%m%d")
    base = f"{cfg['title']}_{date_str}"
    if speed != 1.0:
        base += f"_{speed}x"
    return f"{base}.mp4"


# ── Step 1: TTS (edge-tts) ──────────────────────────────────


def _volcengine_synthesize(text, output_path, api_key, voice_type, cluster="volcano_tts", speed_ratio=1.0):
    """调用火山引擎 TTS API 合成语音"""
    import requests
    payload = {
        "app": {"cluster": cluster},
        "user": {"uid": "card_carousel"},
        "audio": {
            "voice_type": voice_type,
            "encoding": "mp3",
            "speed_ratio": speed_ratio,
        },
        "request": {
            "reqid": uuid.uuid4().hex,
            "text": text,
            "operation": "query",
        },
    }
    headers = {"x-api-key": api_key, "Content-Type": "application/json"}
    try:
        resp = requests.post(
            "https://openspeech.bytedance.com/api/v1/tts",
            headers=headers, json=payload, timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        print(f"    TTS 请求失败: {e}")
        return False
    if "data" in result:
        audio_bytes = base64.b64decode(result["data"])
        with open(output_path, "wb") as f:
            f.write(audio_bytes)
        return True
    print(f"    TTS API 错误: {result}")
    return False


def _edge_tts_synthesize(text, output_path, voice="zh-CN-YunxiNeural", speed=1.0):
    """使用免费的 edge-tts 合成语音"""
    try:
        import edge_tts
    except ImportError:
        print("错误: 缺少 edge-tts，请运行: pip install edge-tts")
        sys.exit(1)

    rate_str = f"{int((speed - 1) * 100):+d}%"

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate_str)
        await communicate.save(output_path)

    asyncio.run(_run())
    return True


def _concat_audios(audio_paths, output_path):
    """用 ffmpeg concat 拼接多个音频文件"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for p in audio_paths:
            escaped = os.path.abspath(p).replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
        list_file = f.name
    try:
        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file, "-c", "copy", output_path,
        ], capture_output=True, check=True)
    finally:
        os.remove(list_file)


def _tts_scene(cfg, scene, audio_dir):
    """单个场景的逐句 TTS → 测时长 → 拼接 → 返回 timing dict"""
    voice = cfg["voice"]
    name = scene["name"]
    full_text = scene["narration"].strip()
    sentences = [s.strip() for s in full_text.split("\n") if s.strip()]

    print(f"\n  [{name}] {len(sentences)} 句")
    t0 = time.time()

    sent_paths = []
    sent_durations = []

    for i, sentence in enumerate(sentences):
        sent_path = os.path.join(audio_dir, f"{name}_s{i:02d}.mp3")

        if os.path.exists(sent_path):
            dur = get_duration(sent_path)
            sent_paths.append(sent_path)
            sent_durations.append(round(dur, 2))
            print(f"    句{i}: {dur:.2f}s (已存在)")
            continue

        provider = voice.get("provider", "edge")
        if provider == "volcengine":
            api_key = os.environ.get("VOLC_API_KEY", "")
            if not api_key:
                print("    错误: 缺少 VOLC_API_KEY 环境变量")
                sys.exit(1)
            ok = _volcengine_synthesize(
                sentence, sent_path,
                api_key=api_key,
                voice_type=voice.get("voice_type", ""),
                cluster=voice.get("cluster", "volcano_tts"),
                speed_ratio=voice.get("speed", 1.0),
            )
        else:
            ok = _edge_tts_synthesize(
                sentence, sent_path,
                voice=voice.get("voice_type", "zh-CN-YunxiNeural"),
                speed=voice.get("speed", 1.0),
            )
        if not ok:
            print(f"    句{i} 失败: {sentence[:20]}...")
            sys.exit(1)

        dur = get_duration(sent_path)
        sent_paths.append(sent_path)
        sent_durations.append(round(dur, 2))
        print(f"    句{i}: {dur:.2f}s — {sentence[:25]}...")

    # 拼接成场景完整音频
    scene_audio = os.path.join(audio_dir, f"{name}.mp3")
    if not os.path.exists(scene_audio):
        if len(sent_paths) == 1:
            shutil.copy2(sent_paths[0], scene_audio)
        else:
            _concat_audios(sent_paths, scene_audio)

    total = round(sum(sent_durations), 2)
    elapsed_time = time.time() - t0
    print(f"    合计: {total:.1f}s (耗时 {elapsed_time:.1f}s)")
    return {"total": total, "sentences": sent_durations}


def step_tts(cfg):
    """逐句 TTS → 测时长 → 拼接 → 写入 timing"""
    audio_dir = cfg["_audio_dir"]
    timing_file = cfg["_timing_file"]

    # 检查是否可以跳过
    all_exist = os.path.exists(timing_file)
    if all_exist:
        for scene in cfg["scenes"]:
            if not os.path.exists(os.path.join(audio_dir, f"{scene['name']}.mp3")):
                all_exist = False
                break

    if all_exist:
        with open(timing_file) as f:
            timing = json.load(f)
        total_dur = sum(v["total"] if isinstance(v, dict) else v for v in timing.values())
        print("=" * 50)
        print("Step: TTS 配音 (跳过 — 音频已存在)")
        print(f"  {len(timing)} 个场景, 总时长 {total_dur:.1f}s")
        print("=" * 50)
        return timing

    os.makedirs(audio_dir, exist_ok=True)

    voice = cfg["voice"]
    print("=" * 50)
    print(f"Step: TTS 配音 ({voice.get('provider', 'edge')})")
    print(f"  Voice: {voice.get('voice_type', 'unknown')}")
    print(f"  语速: {voice.get('speed', 1.0)}")
    print("=" * 50)

    timing = {}
    for scene in cfg["scenes"]:
        timing[scene["name"]] = _tts_scene(cfg, scene, audio_dir)

    os.makedirs(os.path.dirname(timing_file), exist_ok=True)
    with open(timing_file, "w") as f:
        json.dump(timing, f, indent=2)
    print(f"\n  Timing 写入: {timing_file}")
    print(f"\n  音频保存在: {audio_dir}")
    return timing


# ── Step 2: Illustrations (AI 生图 + 缓存) ──────────────────


def _generate_kling(prompt, output_path, model="kling-v1", aspect_ratio="1:1",
                    poll_interval=3, max_wait=120):
    """通过 sucloud 的 kling 异步 API 生成图片"""
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY")
    base_url = os.environ.get("GEMINI_BASE_URL", "https://sucloud.vip").rstrip("/")

    if not api_key:
        raise ValueError("GEMINI_API_KEY 未设置")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # 1. 创建任务
    create_url = f"{base_url}/kling/v1/images/generations"
    body = {
        "model_name": model,
        "prompt": prompt,
        "n": 1,
        "aspect_ratio": aspect_ratio,
    }

    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0)
    resp = httpx.post(create_url, json=body, headers=headers, timeout=timeout, verify=False)
    resp.raise_for_status()
    data = resp.json()

    if data.get("code") != 0:
        raise RuntimeError(f"kling 创建任务失败: {data.get('message', data)}")

    task_id = data["data"]["task_id"]
    print(f"    任务已提交 (task_id={task_id[:16]}...)")

    # 2. 轮询结果
    query_url = f"{base_url}/kling/v1/images/generations/{task_id}"
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(poll_interval)
        r = httpx.get(query_url, headers=headers, timeout=timeout, verify=False)
        r.raise_for_status()
        result = r.json()

        if result.get("code") != 0:
            raise RuntimeError(f"kling 查询失败: {result.get('message', result)}")

        status = result["data"]["task_status"]
        if status == "succeed":
            images = result["data"]["task_result"]["images"]
            if not images:
                raise RuntimeError("kling 返回空图片列表")
            image_url = images[0]["url"]
            # 下载图片
            dl = httpx.get(image_url, timeout=60, verify=False)
            dl.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(dl.content)
            elapsed = time.time() - start
            print(f"    生成完成 ({elapsed:.1f}s)")
            return output_path
        elif status == "failed":
            msg = result["data"].get("task_status_msg", "未知错误")
            raise RuntimeError(f"kling 生成失败: {msg}")
        else:
            elapsed = time.time() - start
            print(f"    等待中... ({elapsed:.0f}s, {status})", end="\r")

    raise RuntimeError(f"kling 超时 ({max_wait}s)")



def _generate_with_tool(prompt, cache_dir, safe_name, gen_tool, engine, model):
    """使用外部 gen_tool (nano_banana_gen.py) 生成图片"""
    cmd = [
        sys.executable, gen_tool,
        prompt,
        "--aspect_ratio", "1:1",
        "-o", cache_dir,
        "--filename", safe_name,
        "--engine", engine,
    ]
    if model:
        cmd.extend(["--model", model])
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def step_illustrations(cfg):
    """为每句话生成 AI 插画，缓存到共享目录"""
    illus_cfg = cfg.get("illustrations", {})
    if not illus_cfg.get("enabled"):
        print("  插画未启用，跳过")
        return

    style_prompt = illus_cfg.get("style_prompt", "")
    project_dir = cfg["_project_dir"]
    cache_dir = os.path.join(project_dir, illus_cfg.get("cache_dir", ".cache/illustrations"))
    os.makedirs(cache_dir, exist_ok=True)

    # assets 目录供 Manim 脚本读取
    assets_dir = os.path.join(project_dir, "assets", "illustrations")
    os.makedirs(assets_dir, exist_ok=True)

    engine = illus_cfg.get("engine", "gemini")
    model = illus_cfg.get("model", None)
    gen_tool = illus_cfg.get("gen_tool", "")
    # 支持相对路径（相对于项目目录）
    if gen_tool and not os.path.isabs(gen_tool):
        gen_tool = os.path.join(project_dir, gen_tool)

    # kling 引擎内置支持，不需要外部工具
    use_builtin_kling = engine == "kling"
    if not use_builtin_kling and (not gen_tool or not os.path.exists(gen_tool)):
        print(f"  警告: 生图工具不存在 ({gen_tool})，跳过插画生成")
        return

    print("=" * 50)
    print("Step: AI 插画生成")
    print(f"  引擎: {engine}" + (f" ({model})" if model else ""))
    print(f"  缓存目录: {cache_dir}")
    print(f"  资源目录: {assets_dir}")
    print("=" * 50)

    # 收集所有唯一关键词
    all_keywords = set()
    for scene in cfg["scenes"]:
        keywords = scene.get("illustration_keywords", [])
        all_keywords.update(k for k in keywords if k)

    generated = 0
    skipped = 0
    failed = 0
    for kw in sorted(all_keywords):
        safe_name = sanitize_filename(kw)

        # 检查缓存（支持多种扩展名）
        cached_path = None
        for ext in (".png", ".jpg", ".jpeg"):
            candidate = os.path.join(cache_dir, f"{safe_name}{ext}")
            if os.path.exists(candidate):
                cached_path = candidate
                break

        if cached_path:
            print(f"  [{kw}] 已缓存，跳过")
            skipped += 1
            asset_dest = os.path.join(assets_dir, os.path.basename(cached_path))
            if not os.path.exists(asset_dest):
                shutil.copy2(cached_path, asset_dest)
            continue

        prompt = f"{style_prompt}, {kw}" if style_prompt else kw
        print(f"  [{kw}] 生成中...")

        try:
            if use_builtin_kling:
                out_path = os.path.join(cache_dir, f"{safe_name}.png")
                print(f"    引擎: kling ({model or 'kling-v1'})")
                _generate_kling(
                    prompt, out_path,
                    model=model or "kling-v1",
                    aspect_ratio="1:1",
                )
            else:
                print(f"    引擎: {engine} ({model})")
                ok = _generate_with_tool(prompt, cache_dir, safe_name, gen_tool, engine, model)
                if not ok:
                    raise RuntimeError("_generate_with_tool 返回 False")
        except Exception as e:
            # 主引擎失败，尝试 fallback
            fallback_engine = illus_cfg.get("fallback_engine")
            fallback_model = illus_cfg.get("fallback_model")
            if fallback_engine:
                print(f"    主引擎失败 ({e})，尝试 fallback ({fallback_engine})...")
                try:
                    if fallback_engine == "kling":
                        out_path = os.path.join(cache_dir, f"{safe_name}.png")
                        _generate_kling(
                            prompt, out_path,
                            model=fallback_model or "kling-v1",
                            aspect_ratio="1:1",
                        )
                    else:
                        ok = _generate_with_tool(prompt, cache_dir, safe_name, gen_tool, fallback_engine, fallback_model)
                        if not ok:
                            print(f"    fallback 生成失败")
                            failed += 1
                            continue
                except Exception as fe:
                    print(f"    fallback 生成失败: {fe}")
                    failed += 1
                    continue
            else:
                print(f"    生成失败: {e}")
                failed += 1
                continue

        # 检查生成结果
        found_path = None
        for ext in (".png", ".jpg", ".jpeg"):
            candidate = os.path.join(cache_dir, f"{safe_name}{ext}")
            if os.path.exists(candidate):
                found_path = candidate
                break

        if found_path:
            asset_dest = os.path.join(assets_dir, os.path.basename(found_path))
            shutil.copy2(found_path, asset_dest)
            generated += 1
            print(f"    -> {found_path}")
        else:
            print(f"    警告: 生成完成但未找到输出文件")
            failed += 1

    print(f"\n  完成: 生成 {generated} 张, 跳过 {skipped} 张, 失败 {failed} 张")


# ── Step 3: Render (Manim) ──────────────────────────────────


def step_render(cfg):
    """渲染 Manim 场景"""
    script = cfg["manim_script"]
    quality = cfg["render_quality"]
    scene_names = [s["name"] for s in cfg["scenes"]]

    print("=" * 50)
    print(f"Step: 渲染 Manim ({script})")
    print(f"  质量: -{quality}")
    print(f"  场景: {len(scene_names)} 个")
    print("=" * 50)

    project_dir = cfg["_project_dir"]
    cmd = [
        "manim", f"-q{quality}",
        os.path.join(project_dir, script),
    ] + scene_names

    print(f"\n  执行: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=project_dir)
    if result.returncode != 0:
        print("  渲染失败!")
        sys.exit(1)

    print("\n  渲染完成!")


# ── Step 4: Voice (合并音频到视频) ───────────────────────────


def step_voice(cfg):
    """将 TTS 音频合并到渲染好的视频"""
    render_dir = cfg["_render_dir"]
    audio_dir = cfg["_audio_dir"]
    voiced_dir = cfg["_voiced_dir"]
    os.makedirs(voiced_dir, exist_ok=True)

    print("=" * 50)
    print("Step: 合并配音到视频")
    print("=" * 50)

    for scene in cfg["scenes"]:
        name = scene["name"]
        video_path = os.path.join(render_dir, f"{name}.mp4")
        audio_path = os.path.join(audio_dir, f"{name}.mp3")
        output_path = os.path.join(voiced_dir, f"{name}.mp4")

        if os.path.exists(output_path):
            print(f"\n  [{name}] 已存在，跳过")
            continue

        if not os.path.exists(video_path):
            print(f"\n  [{name}] 错误: 视频不存在 ({video_path})")
            sys.exit(1)
        if not os.path.exists(audio_path):
            print(f"\n  [{name}] 错误: 音频不存在 ({audio_path})")
            sys.exit(1)

        video_dur = get_duration(video_path)
        audio_dur = get_duration(audio_path)
        print(f"\n  [{name}] 视频={video_dur:.1f}s, 音频={audio_dur:.1f}s")

        if audio_dur > video_dur:
            # 音频更长: 冻结视频最后一帧
            subprocess.run([
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-filter_complex",
                f"[0:v]tpad=stop_mode=clone:stop_duration={audio_dur - video_dur + 0.5}[v]",
                "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-shortest",
                output_path,
            ], capture_output=True, check=True)
        else:
            subprocess.run([
                "ffmpeg", "-y",
                "-i", video_path,
                "-i", audio_path,
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                "-map", "0:v", "-map", "1:a",
                "-shortest",
                output_path,
            ], capture_output=True, check=True)

        print(f"    -> {get_duration(output_path):.1f}s")

    print("\n  合并完成!")


# ── Step 5: Concat (拼接 + 可选加速) ────────────────────────


def step_concat(cfg):
    """拼接所有场景 → 输出最终视频"""
    src_dir = cfg["_voiced_dir"]
    speed = float(cfg["output"].get("speed", 1.0))
    output_dir = cfg["output"].get("dir", cfg["_project_dir"])
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 50)
    print(f"Step: 拼接 → {speed}x")
    print("=" * 50)

    concat_fd = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", prefix="concat_", delete=False,
    )
    concat_file = concat_fd.name
    tmp_video_path = None
    try:
        with concat_fd:
            for scene in cfg["scenes"]:
                path = os.path.join(src_dir, f"{scene['name']}.mp4")
                if not os.path.exists(path):
                    print(f"\n  错误: 场景视频不存在 ({path})")
                    sys.exit(1)
                escaped = os.path.abspath(path).replace("'", "'\\''")
                concat_fd.write(f"file '{escaped}'\n")

        final_name = _output_name(cfg, speed=speed)
        final_output = os.path.join(output_dir, final_name)

        if speed == 1.0:
            print(f"\n  拼接 → {final_name}")
            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                final_output,
            ], capture_output=True, check=True)
        else:
            tmp_fd = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp_video_path = tmp_fd.name
            tmp_fd.close()

            subprocess.run([
                "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                "-i", concat_file,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                tmp_video_path,
            ], capture_output=True, check=True)

            print(f"\n  拼接 + {speed}x → {final_name}")
            subprocess.run([
                "ffmpeg", "-y", "-i", tmp_video_path,
                "-filter_complex",
                f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]",
                "-map", "[v]", "-map", "[a]",
                final_output,
            ], capture_output=True, check=True)

        dur = get_duration(final_output)
        size_mb = os.path.getsize(final_output) / 1024 / 1024
        print(f"    -> {final_output}")
        print(f"    -> {dur:.1f}s ({size_mb:.1f}MB)")
        print("\n  完成!")
    finally:
        if os.path.exists(concat_file):
            os.remove(concat_file)
        if tmp_video_path and os.path.exists(tmp_video_path):
            os.remove(tmp_video_path)


# ── Pipeline ────────────────────────────────────────────────


STEPS = {
    "tts": step_tts,
    "illustrations": step_illustrations,
    "render": step_render,
    "voice": step_voice,
    "concat": step_concat,
}

STEP_ORDER = ["tts", "illustrations", "render", "voice", "concat"]


def run_pipeline(cfg, step=None):
    """编排所有步骤或单独运行某一步"""
    title = cfg["title"]
    print(f"\n{'#' * 50}")
    print(f"  图文卡片视频管线: {title}")
    print(f"{'#' * 50}\n")

    if step:
        if step not in STEPS:
            print(f"未知步骤: {step}")
            print(f"可用步骤: {', '.join(STEP_ORDER)}")
            sys.exit(1)
        STEPS[step](cfg)
    else:
        t0 = time.time()
        for s in STEP_ORDER:
            # 插画未启用则跳过
            if s == "illustrations" and not cfg.get("illustrations", {}).get("enabled"):
                continue
            print()
            STEPS[s](cfg)

        elapsed = time.time() - t0
        print(f"\n{'#' * 50}")
        print(f"  全部完成! 总耗时: {elapsed:.0f}s")
        print(f"{'#' * 50}")


# ── CLI ─────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="图文卡片口播视频生成管线",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="示例:\n"
               "  python pipeline.py config.yaml\n"
               "  python pipeline.py config.yaml --step tts\n"
               "  python pipeline.py config.yaml --step illustrations\n"
               "  python pipeline.py config.yaml --step render\n",
    )
    parser.add_argument("config", help="YAML 配置文件路径")
    parser.add_argument("--step", choices=STEP_ORDER, default=None,
                        help="只执行指定步骤")
    parser.add_argument("--speed", type=float, default=None,
                        help="播放倍率 (默认 1.0)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.speed is not None:
        if args.speed <= 0 or args.speed > 100:
            print(f"错误: --speed 必须在 0.1-100.0 之间，当前值: {args.speed}")
            sys.exit(1)
        cfg["output"]["speed"] = args.speed
    run_pipeline(cfg, step=args.step)


if __name__ == "__main__":
    main()
