"""
管线编排 — 所有 step 函数 + run_pipeline 入口
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from .utils import get_duration, sanitize_filename, _output_name, split_long_sentences
from engines.tts import get_tts_engine
from engines.image import get_image_engine


# ── 内部辅助函数 ─────────────────────────────────────────────


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


def _build_tts_voice_signature(voice):
    """构建用于缓存和指纹计算的语音配置签名"""
    fields = ["provider", "voice_type", "speed", "cluster"]
    payload = {field: str(voice.get(field, "")) for field in fields}
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _compute_tts_fingerprint(cfg):
    """计算 TTS 输入指纹，用于判断是否可跳过整步"""
    payload = {
        "narration": [scene.get("narration", "") for scene in cfg.get("scenes", [])],
        "max_chars_per_card": cfg.get("layout", {}).get("max_chars_per_card"),
        "voice": _build_tts_voice_signature(cfg.get("voice", {})),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def _tts_scene(cfg, scene, audio_dir):
    """单个场景的逐句 TTS → 测时长 → 拼接 → 返回 timing dict"""
    voice = cfg["voice"]
    name = scene["name"]
    full_text = scene["narration"].strip()
    raw_sentences = [s.strip() for s in full_text.split("\n") if s.strip()]

    if not raw_sentences:
        print(f"\n  [{name}] 错误: narration 为空")
        sys.exit(1)

    # 拆分超长句子（与渲染逻辑保持一致）
    keywords = scene.get("illustration_keywords", [])
    max_chars = cfg.get("layout", {}).get("max_chars_per_card", 18)
    sentences, _ = split_long_sentences(raw_sentences, keywords, max_chars)

    print(f"\n  [{name}] {len(sentences)} 句")
    t0 = time.time()

    sent_paths = []
    sent_durations = []

    engine = get_tts_engine(voice)
    voice_signature = _build_tts_voice_signature(voice)

    for i, sentence in enumerate(sentences):
        sentence_hash = hashlib.md5(
            f"{sentence}|{voice_signature}".encode("utf-8")
        ).hexdigest()[:8]
        sent_path = os.path.join(audio_dir, f"{name}_{sentence_hash}.mp3")

        if os.path.exists(sent_path):
            dur = get_duration(sent_path)
            sent_paths.append(sent_path)
            sent_durations.append(round(dur, 2))
            print(f"    句{i}: {dur:.2f}s (已存在)")
            continue

        result = engine.synthesize(sentence, sent_path)
        if not result.success:
            print(f"    句{i} 失败: {result.error}")
            sys.exit(1)

        dur = get_duration(sent_path)
        sent_paths.append(sent_path)
        sent_durations.append(round(dur, 2))
        print(f"    句{i}: {dur:.2f}s — {sentence[:25]}...")

    # 拼接成场景完整音频
    scene_audio = os.path.join(audio_dir, f"{name}.mp3")
    scene_manifest = os.path.join(audio_dir, f"{name}.sentences")
    current_manifest = "\n".join(os.path.basename(p) for p in sent_paths)
    previous_manifest = None
    if os.path.exists(scene_manifest):
        with open(scene_manifest, encoding="utf-8") as f:
            previous_manifest = f.read()

    if (not os.path.exists(scene_audio)) or (previous_manifest != current_manifest):
        if len(sent_paths) == 1:
            shutil.copy2(sent_paths[0], scene_audio)
        else:
            _concat_audios(sent_paths, scene_audio)
        with open(scene_manifest, "w", encoding="utf-8") as f:
            f.write(current_manifest)

    total = round(sum(sent_durations), 2)
    elapsed_time = time.time() - t0
    print(f"    合计: {total:.1f}s (耗时 {elapsed_time:.1f}s)")
    return {"total": total, "sentences": sent_durations}


# ── Step 1: TTS ──────────────────────────────────────────────


def step_tts(cfg):
    """逐句 TTS → 测时长 → 拼接 → 写入 timing"""
    audio_dir = cfg["_audio_dir"]
    timing_file = cfg["_timing_file"]
    fingerprint_file = os.path.join(audio_dir, "_tts_fingerprint.md5")
    current_fingerprint = _compute_tts_fingerprint(cfg)

    # 检查是否可以跳过
    all_exist = os.path.exists(timing_file) and os.path.exists(fingerprint_file)
    if all_exist:
        with open(fingerprint_file, encoding="utf-8") as f:
            cached_fingerprint = f.read().strip()
        if cached_fingerprint != current_fingerprint:
            all_exist = False

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
    print(f"Step: TTS 配音 ({voice.get('provider', 'volcengine')})")
    print(f"  Voice: {voice.get('voice_type', 'unknown')}")
    print(f"  语速: {voice.get('speed', 1.0)}")
    print("=" * 50)

    timing = {}
    for scene in cfg["scenes"]:
        timing[scene["name"]] = _tts_scene(cfg, scene, audio_dir)

    os.makedirs(os.path.dirname(timing_file), exist_ok=True)
    with open(timing_file, "w") as f:
        json.dump(timing, f, indent=2)
    with open(fingerprint_file, "w", encoding="utf-8") as f:
        f.write(current_fingerprint)
    print(f"\n  Timing 写入: {timing_file}")
    print(f"\n  音频保存在: {audio_dir}")
    return timing


# ── Step 2: Illustrations ────────────────────────────────────


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

    engine_name = illus_cfg.get("engine", "gemini")
    model = illus_cfg.get("model", None)
    gen_tool = illus_cfg.get("gen_tool", "")
    # 支持相对路径（相对于项目目录）
    if gen_tool and not os.path.isabs(gen_tool):
        gen_tool = os.path.join(project_dir, gen_tool)

    # 安全校验：gen_tool 必须在项目目录内
    if gen_tool:
        norm_tool = os.path.normpath(os.path.abspath(gen_tool))
        norm_project = os.path.normpath(os.path.abspath(project_dir))
        if not norm_tool.startswith(norm_project):
            print(f"  错误: gen_tool 路径越界 ({gen_tool})")
            return

    if not gen_tool or not os.path.exists(gen_tool):
        print(f"  警告: 生图工具不存在 ({gen_tool})，跳过插画生成")
        return

    print("=" * 50)
    print("Step: AI 插画生成")
    print(f"  引擎: {engine_name}" + (f" ({model})" if model else ""))
    print(f"  缓存目录: {cache_dir}")
    print(f"  资源目录: {assets_dir}")
    print("=" * 50)

    # 收集所有唯一关键词
    all_keywords = set()
    for scene in cfg["scenes"]:
        keywords = scene.get("illustration_keywords", [])
        all_keywords.update(k for k in keywords if k)

    # 获取主引擎
    primary_engine = get_image_engine(illus_cfg, gen_tool=gen_tool)

    # 准备 fallback 引擎（若配置了）
    fallback_engine_name = illus_cfg.get("fallback_engine")
    fallback_model = illus_cfg.get("fallback_model")
    fallback_engine = None
    if fallback_engine_name:
        fallback_cfg = dict(illus_cfg)
        fallback_cfg["engine"] = fallback_engine_name
        fallback_cfg["model"] = fallback_model
        fallback_engine = get_image_engine(fallback_cfg, gen_tool=gen_tool)

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

        out_path = os.path.join(cache_dir, f"{safe_name}.png")
        print(f"    引擎: {engine_name}" + (f" ({model})" if model else ""))
        img_result = primary_engine.generate(prompt, out_path)

        if not img_result.success:
            # 主引擎失败，尝试 fallback
            if fallback_engine:
                print(f"    主引擎失败 ({img_result.error})，尝试 fallback ({fallback_engine_name})...")
                fb_result = fallback_engine.generate(prompt, out_path)
                if not fb_result.success:
                    print(f"    fallback 生成失败: {fb_result.error}")
                    failed += 1
                    continue
            else:
                print(f"    生成失败: {img_result.error}")
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
            print("    警告: 生成完成但未找到输出文件")
            failed += 1

    print(f"\n  完成: 生成 {generated} 张, 跳过 {skipped} 张, 失败 {failed} 张")


# ── Step 3: Render ───────────────────────────────────────────


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

    # 注入项目目录 + 配置路径，供模板 scene.py 读取
    env = os.environ.copy()
    env["CARD_CAROUSEL_PROJECT_DIR"] = project_dir
    env["CARD_CAROUSEL_CONFIG_PATH"] = cfg["_config_path"]
    env["CARD_CAROUSEL_AUDIO_DIR"] = cfg["_audio_dir"]
    env["CARD_CAROUSEL_TIMING_FILE"] = cfg["_timing_file"]

    print(f"\n  执行: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=project_dir, env=env)
    if result.returncode != 0:
        print("  渲染失败!")
        sys.exit(1)

    print("\n  渲染完成!")


# ── Step 4: Voice ────────────────────────────────────────────


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


# ── Step 5: Concat ───────────────────────────────────────────


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

        # 安全校验：输出文件必须在 output_dir 内
        if not os.path.normpath(os.path.abspath(final_output)).startswith(
            os.path.normpath(os.path.abspath(output_dir))
        ):
            print(f"\n  错误: 输出路径越界 ({final_output})")
            sys.exit(1)

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


# ── Pipeline 编排 ────────────────────────────────────────────


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
