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


def _split_by_silences(audio_path: str, sentences: list, total: float) -> list:
    """用 ffmpeg silencedetect 拆分每句时长，失败时按字数比例回退。

    策略: 按字数比例计算每个句子边界的期望时间点，然后为每个边界找
    最近的静音区间（避免因 TTS 戏剧性停顿导致的错位）。
    """
    n = len(sentences)
    if n == 1:
        return [round(total, 2)]

    chars = [max(len(s), 1) for s in sentences]
    tc = sum(chars)

    def _proportional():
        return [round(total * c / tc, 2) for c in chars]

    try:
        import re
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path,
             "-af", "silencedetect=n=-35dB:d=0.08",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=30,
        )
        starts = [float(m) for m in re.findall(r"silence_start: ([\d.]+)", result.stderr)]
        ends   = [float(m) for m in re.findall(r"silence_end: ([\d.]+)",   result.stderr)]
        silences = list(zip(starts, ends))
        if len(silences) < n - 1:
            return _proportional()

        # 计算 n-1 个边界的期望时间点（按字数比例）
        expected_boundaries = []
        cumulative = 0
        for c in chars[:-1]:
            cumulative += c
            expected_boundaries.append(total * cumulative / tc)

        # 为每个期望边界找最近的静音 end（不重复使用）
        avg_dur = total / n
        search_window = avg_dur * 0.7   # 搜索窗口: 平均句长的 ±70%
        used = set()
        selected_ends = []
        for expected in expected_boundaries:
            best_idx, best_dist = None, float("inf")
            for i, (s, e) in enumerate(silences):
                if i in used:
                    continue
                dist = abs(e - expected)
                if dist < best_dist and dist <= search_window:
                    best_dist, best_idx = dist, i
            if best_idx is not None:
                used.add(best_idx)
                selected_ends.append(silences[best_idx][1])
            else:
                selected_ends.append(expected)   # 窗口内无静音，退回比例值

        selected_ends.sort()

        # 计算各句时长
        durations = []
        prev = 0.0
        for b in selected_ends:
            durations.append(max(0.1, round(b - prev, 2)))
            prev = b
        durations.append(max(0.1, round(total - prev, 2)))
        return durations
    except Exception:
        return _proportional()


def _tts_scene(cfg, scene, audio_dir):
    """场景整体 TTS（一次合成保证语气连贯）→ 静音检测拆分时长"""
    voice = cfg["voice"]
    name = scene["name"]
    full_text = scene["narration"].strip()
    raw_sentences = [s.strip() for s in full_text.split("\n") if s.strip()]

    if not raw_sentences:
        print(f"\n  [{name}] 错误: narration 为空")
        sys.exit(1)

    keywords = scene.get("illustration_keywords", [])
    max_chars = cfg.get("layout", {}).get("max_chars_per_card", 18)
    sentences, _, _cont = split_long_sentences(raw_sentences, keywords, max_chars)

    n = len(sentences)
    print(f"\n  [{name}] {n} 句")
    t0 = time.time()

    engine = get_tts_engine(voice)
    voice_signature = _build_tts_voice_signature(voice)

    # 整句合成：加句号确保自然停顿
    def _ensure_punct(s):
        return s if s and s[-1] in "。！？，、；：…—" else s + "。"

    combined_text = "\n".join(_ensure_punct(s) for s in sentences)
    combined_hash = hashlib.md5(
        f"full|{combined_text}|{voice_signature}".encode("utf-8")
    ).hexdigest()[:8]

    scene_audio = os.path.join(audio_dir, f"{name}.mp3")
    combined_cache = os.path.join(audio_dir, f"{name}_full_{combined_hash}.mp3")

    if not os.path.exists(combined_cache):
        print("    整场合成中...")
        result = engine.synthesize(combined_text, combined_cache)
        if not result.success:
            print(f"    合成失败: {result.error}")
            sys.exit(1)
    else:
        print("    已缓存，直接使用")

    shutil.copy2(combined_cache, scene_audio)
    total = round(get_duration(scene_audio), 2)

    sent_durations = _split_by_silences(scene_audio, sentences, total)

    elapsed = time.time() - t0
    for i, (s, d) in enumerate(zip(sentences, sent_durations)):
        print(f"    句{i}: {d:.2f}s — {s[:25]}")
    print(f"    合计: {total:.1f}s (耗时 {elapsed:.1f}s)")
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

    # 品牌资产层：use_character / use_reference_image
    brand = cfg.get("_brand", {})
    brand_author = brand.get("author", {})
    character_desc = illus_cfg.get("character_desc") or brand_author.get("character_desc", "")
    if illus_cfg.get("use_character") and character_desc:
        # 支持 {character} 占位符，让模板控制人物描述的插入位置
        if "{character}" in style_prompt:
            style_prompt = style_prompt.replace("{character}", character_desc)
        else:
            style_prompt = f"{character_desc}, {style_prompt}" if style_prompt else character_desc
    else:
        # 无人物描述时清理残留的 {character} 占位符，避免脏 prompt
        style_prompt = style_prompt.replace("{character}", "").strip().rstrip(",.，。")
    # 参考图控制：仅 use_reference_image=true 时允许 input_image
    use_ref = illus_cfg.get("use_reference_image")
    if use_ref is True:
        # 自动注入 brand 参考图（content yaml 未显式指定时）
        if not illus_cfg.get("input_image") and brand_author.get("reference_image"):
            illus_cfg = dict(illus_cfg)
            illus_cfg["input_image"] = brand_author["reference_image"]
            if "strength" not in illus_cfg and brand_author.get("reference_strength") is not None:
                illus_cfg["strength"] = brand_author["reference_strength"]
    else:
        # use_reference_image 未设置或为 false → 清除 input_image，纯文生图
        if illus_cfg.get("input_image"):
            print("  ⚠️  use_reference_image 未启用，已忽略 input_image（推荐使用纯文字 character_desc 替代参考图）")
            illus_cfg = dict(illus_cfg) if not isinstance(illus_cfg, dict) else illus_cfg
            illus_cfg.pop("input_image", None)
            illus_cfg.pop("strength", None)
        # 迁移提示：brand.yaml 有旧字段但未启用
        if brand_author.get("reference_image") and use_ref is not True:
            print("  💡 检测到 brand.yaml 中有 reference_image，但 use_reference_image 未启用。")
            print("     如需使用参考图，请设置 illustrations.use_reference_image: true")
            print("     推荐方案：使用 character_desc 纯文字描述替代参考图")
    project_dir = cfg["_project_dir"]
    cache_dir = os.path.join(project_dir, illus_cfg.get("cache_dir", ".cache/illustrations"))
    os.makedirs(cache_dir, exist_ok=True)

    # 每个视频独立的插画目录，供 Manim 脚本读取（通过 CARD_CAROUSEL_ILLUSTRATIONS_DIR 传入）
    assets_dir = cfg["_illustrations_dir"]
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

    # 从模板 positionable_elements 获取插画宽高比
    # 优先使用 illustration.aspect_ratio（预览编辑器覆盖），回退到元素默认值
    illus_aspect_ratio = cfg.get("illustration", {}).get("aspect_ratio")
    if not illus_aspect_ratio:
        illus_aspect_ratio = "1:1"
        for pe in cfg.get("positionable_elements", []):
            if pe.get("type") == "illustration":
                illus_aspect_ratio = pe.get("aspect_ratio", "1:1")
                break

    # 收集所有唯一关键词
    all_keywords = set()
    for scene in cfg["scenes"]:
        keywords = scene.get("illustration_keywords", [])
        all_keywords.update(k for k in keywords if k)

    # 解析 input_image 路径（img2img 参考图）
    input_image = illus_cfg.get("input_image", "")
    if input_image and not os.path.isabs(input_image):
        input_image = os.path.join(project_dir, input_image)

    # 获取主引擎
    primary_engine = get_image_engine(illus_cfg, gen_tool=gen_tool)

    # 准备 fallback 引擎（若配置了，支持链式 fallback）
    fallback_spec = illus_cfg.get("fallback_engines")
    if fallback_spec is None:
        fallback_spec = illus_cfg.get("fallback_engine")
    if isinstance(fallback_spec, (list, tuple)):
        fallback_engine_names = [name for name in fallback_spec if name]
    elif fallback_spec:
        fallback_engine_names = [fallback_spec]
    else:
        fallback_engine_names = []

    fallback_models_spec = illus_cfg.get("fallback_models")
    if fallback_models_spec is None:
        fallback_models_spec = illus_cfg.get("fallback_model")
    if isinstance(fallback_models_spec, (list, tuple)):
        fallback_models = list(fallback_models_spec)
    elif fallback_models_spec:
        fallback_models = [fallback_models_spec]
    else:
        fallback_models = []

    if len(fallback_models) < len(fallback_engine_names):
        fallback_models.extend([None] * (len(fallback_engine_names) - len(fallback_models)))

    fallback_chain = []
    for idx, fb_name in enumerate(fallback_engine_names):
        if fb_name == engine_name:
            continue
        fb_cfg = dict(illus_cfg)
        fb_cfg["engine"] = fb_name
        fb_cfg["model"] = fallback_models[idx] if idx < len(fallback_models) else None
        fallback_chain.append((fb_name, fb_cfg["model"], get_image_engine(fb_cfg, gen_tool=gen_tool)))

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

        if style_prompt:
            # 支持占位符 {keyword} — 用户可精确控制关键词插入位置
            if "{keyword}" in style_prompt:
                prompt = style_prompt.replace("{keyword}", kw)
            else:
                # 默认：内容主题在前，风格约束在后（提升内容匹配度）
                prompt = f"主题内容：「{kw}」。\n\n风格要求：{style_prompt}"
        else:
            prompt = kw
        print(f"  [{kw}] 生成中...")

        out_path = os.path.join(cache_dir, f"{safe_name}.png")
        print(f"    引擎: {engine_name}" + (f" ({model})" if model else ""))
        if input_image:
            print(f"    参考图: {os.path.basename(input_image)}")
        illus_strength = illus_cfg.get("strength")
        img_result = primary_engine.generate(prompt, out_path, aspect_ratio=illus_aspect_ratio, input_image=input_image, strength=illus_strength)

        if not img_result.success:
            if fallback_chain:
                last_error = img_result.error
                recovered = False
                for fb_name, fb_model, fb_engine in fallback_chain:
                    fb_label = f"{fb_name} ({fb_model})" if fb_model else fb_name
                    print(f"    主引擎失败 ({last_error})，尝试 fallback ({fb_label})...")
                    fb_result = fb_engine.generate(prompt, out_path, aspect_ratio=illus_aspect_ratio, input_image=input_image, strength=illus_strength)
                    if fb_result.success:
                        recovered = True
                        break
                    last_error = fb_result.error
                    print(f"    fallback {fb_name} 失败: {fb_result.error}")
                if not recovered:
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
        "--media_dir", cfg["_manim_media_dir"],
        os.path.join(project_dir, script),
    ] + scene_names

    # 注入项目目录 + 配置路径，供模板 scene.py 读取
    env = os.environ.copy()
    env["CARD_CAROUSEL_PROJECT_DIR"] = project_dir
    env["CARD_CAROUSEL_CONFIG_PATH"] = cfg["_config_path"]
    env["CARD_CAROUSEL_AUDIO_DIR"] = cfg["_audio_dir"]
    env["CARD_CAROUSEL_TIMING_FILE"] = cfg["_timing_file"]
    env["CARD_CAROUSEL_ILLUSTRATIONS_DIR"] = cfg["_illustrations_dir"]
    env["CARD_CAROUSEL_COVER_DIR"] = cfg["_cover_dir"]

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
            # 如果渲染视频比 voiced 视频更新，说明内容已变化，需要重新合并
            render_mtime = os.path.getmtime(video_path) if os.path.exists(video_path) else 0
            voiced_mtime = os.path.getmtime(output_path)
            if render_mtime <= voiced_mtime:
                print(f"\n  [{name}] 已存在，跳过")
                continue
            print(f"\n  [{name}] 渲染视频已更新，重新合并配音")

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


# ── Step 5: Cover ─────────────────────────────────────────────


def step_cover(cfg):
    """生成封面：插画 → TTS → Manim 渲染 → 合并配音（含开场音效）"""
    cover_cfg = cfg.get("cover", {})
    if not cover_cfg:
        return

    project_dir = cfg["_project_dir"]
    audio_dir = cfg["_audio_dir"]
    voiced_dir = cfg["_voiced_dir"]
    os.makedirs(voiced_dir, exist_ok=True)

    print("=" * 50)
    print("Step: 封面制作")
    print("=" * 50)

    # 1. 生成封面插画
    illus_prompt = cover_cfg.get("illustration_prompt", "")
    if illus_prompt:
        illus_cfg = cfg.get("illustrations", {})
        gen_tool = illus_cfg.get("gen_tool", "")
        if gen_tool and not os.path.isabs(gen_tool):
            gen_tool = os.path.join(project_dir, gen_tool)
        prompt_hash = hashlib.md5(illus_prompt.encode()).hexdigest()
        # 每个封面 prompt 独立缓存，避免多视频并发时互相覆盖
        cover_cache_path = os.path.join(project_dir, "assets", f"cover_{prompt_hash[:12]}.jpg")
        # 封面插画放在 per-config 目录，供 Manim 通过 CARD_CAROUSEL_COVER_DIR 读取
        os.makedirs(cfg["_cover_dir"], exist_ok=True)
        cover_illus_path = os.path.join(cfg["_cover_dir"], "cover_illustration.jpg")
        illus_stale = not os.path.exists(cover_cache_path)
        if illus_stale:
            print("  封面插画: 生成中...")
            img_engine = get_image_engine(illus_cfg, gen_tool=gen_tool)
            img_result = img_engine.generate(illus_prompt, cover_cache_path, aspect_ratio="4:3")
            # 尝试 fallback
            if not img_result.success:
                fallback_names = illus_cfg.get("fallback_engines", [])
                fallback_models = illus_cfg.get("fallback_models", [])
                for i, fb_name in enumerate(fallback_names):
                    fb_cfg = dict(illus_cfg)
                    fb_cfg["engine"] = fb_name
                    fb_cfg["model"] = fallback_models[i] if i < len(fallback_models) else None
                    fb_engine = get_image_engine(fb_cfg, gen_tool=gen_tool)
                    img_result = fb_engine.generate(illus_prompt, cover_cache_path, aspect_ratio="4:3")
                    if img_result.success:
                        break
            if img_result.success:
                # 查找实际生成的文件（生成器可能写为 jpg 或 png）
                actual_cache = cover_cache_path
                for ext in (".jpg", ".jpeg", ".png"):
                    p = os.path.join(project_dir, "assets", f"cover_{prompt_hash[:12]}{ext}")
                    if os.path.exists(p):
                        actual_cache = p
                        break
                print(f"    -> {actual_cache}")
            else:
                print(f"    生成失败: {img_result.error}，将使用默认封面")
        else:
            print("  封面插画: 已缓存，跳过")
        # 将本次封面复制到 cover_illustration.jpg 供模板读取
        actual_cache = cover_cache_path
        for ext in (".jpg", ".jpeg", ".png"):
            p = os.path.join(project_dir, "assets", f"cover_{prompt_hash[:12]}{ext}")
            if os.path.exists(p):
                actual_cache = p
                break
        if os.path.exists(actual_cache):
            shutil.copy2(actual_cache, cover_illus_path)

    # 2. 封面 TTS
    narration = cover_cfg.get("narration") or cfg.get("title", "")
    cover_audio = os.path.join(audio_dir, "cover.mp3")
    if narration:
        voice_signature = _build_tts_voice_signature(cfg["voice"])
        cover_hash = hashlib.md5(
            f"cover|{narration}|{voice_signature}".encode("utf-8")
        ).hexdigest()[:8]
        cover_cache = os.path.join(audio_dir, f"cover_tts_{cover_hash}.mp3")
        if not os.path.exists(cover_cache):
            print(f"  封面 TTS: 合成中...")
            tts_engine = get_tts_engine(cfg["voice"])
            tts_result = tts_engine.synthesize(narration, cover_cache)
            if not tts_result.success:
                print(f"    TTS 失败: {tts_result.error}")
                cover_cache = None
        else:
            print("  封面 TTS: 已缓存，跳过")
        if cover_cache and os.path.exists(cover_cache):
            shutil.copy2(cover_cache, cover_audio)

    # 处理开场音效：拼接在 TTS 前面
    sfx_path = cover_cfg.get("opening_sfx", "")
    if not sfx_path:
        sfx_path = cfg.get("output", {}).get("opening_sfx", "")
    if sfx_path and not os.path.isabs(sfx_path):
        sfx_path = os.path.join(project_dir, sfx_path)

    if sfx_path and os.path.exists(sfx_path) and os.path.exists(cover_audio):
        print(f"  开场音效: 拼接 SFX + TTS...")
        combined_audio = os.path.join(audio_dir, "cover_with_sfx.mp3")
        subprocess.run([
            "ffmpeg", "-y",
            "-i", sfx_path, "-i", cover_audio,
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]",
            "-map", "[a]",
            combined_audio,
        ], capture_output=True, check=True)
        shutil.copy2(combined_audio, cover_audio)
    elif sfx_path and os.path.exists(sfx_path) and not os.path.exists(cover_audio):
        shutil.copy2(sfx_path, cover_audio)

    # 3. 渲染封面 Manim 场景（按模板选择 cover.py）
    template_name = cfg.get("template", "dark-card")
    _cover_map = {
        "sketch-card": ("sketch_card", "SketchCardCover"),
        "dark-card":   ("dark_card",   "DarkCardCover"),
    }
    _tmpl_dir, _scene_cls = _cover_map.get(template_name, ("dark_card", "DarkCardCover"))
    cover_script = os.path.join(project_dir, "templates", _tmpl_dir, "cover.py")
    cover_render_dir = os.path.join(cfg["_manim_media_dir"], "videos", "cover", "1080p60")
    cover_render_out = os.path.join(cover_render_dir, f"{_scene_cls}.mp4")

    # 封面渲染缓存：若插画文件比渲染结果更新，则重新渲染
    cover_illus_mtime = os.path.getmtime(cover_illus_path) if os.path.exists(cover_illus_path) else 0
    render_mtime = os.path.getmtime(cover_render_out) if os.path.exists(cover_render_out) else 0
    cover_render_stale = not os.path.exists(cover_render_out) or cover_illus_mtime > render_mtime
    if cover_render_stale:
        print("  封面渲染: 运行 Manim...")
        env = os.environ.copy()
        env["CARD_CAROUSEL_PROJECT_DIR"] = project_dir
        env["CARD_CAROUSEL_CONFIG_PATH"] = cfg["_config_path"]
        env["CARD_CAROUSEL_AUDIO_DIR"] = audio_dir
        env["CARD_CAROUSEL_ILLUSTRATIONS_DIR"] = cfg["_illustrations_dir"]
        env["CARD_CAROUSEL_COVER_DIR"] = cfg["_cover_dir"]
        cmd = ["manim", "-qh", "--media_dir", cfg["_manim_media_dir"], cover_script, _scene_cls]
        r = subprocess.run(cmd, cwd=project_dir, env=env, capture_output=True)
        if r.returncode != 0:
            print("  封面渲染失败!")
            print(r.stderr.decode(errors="replace")[-800:])
            return
        print(f"    -> {cover_render_out}")
    else:
        print("  封面渲染: 已存在，跳过")

    if not os.path.exists(cover_render_out):
        print("  封面视频不存在，跳过合并")
        return

    # 4. 合并 TTS 音频到封面视频
    cover_voiced = os.path.join(voiced_dir, "cover_voiced.mp4")
    render_mtime = os.path.getmtime(cover_render_out)
    voiced_mtime = os.path.getmtime(cover_voiced) if os.path.exists(cover_voiced) else 0

    if not os.path.exists(cover_voiced) or render_mtime > voiced_mtime:
        print("  封面配音: 合并中...")
        if os.path.exists(cover_audio):
            video_dur = get_duration(cover_render_out)
            audio_dur = get_duration(cover_audio)
            if audio_dur > video_dur:
                # 冻结末帧延长视频
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", cover_render_out, "-i", cover_audio,
                    "-filter_complex",
                    f"[0:v]tpad=stop_mode=clone:stop_duration={audio_dur - video_dur + 0.3}[v]",
                    "-map", "[v]", "-map", "1:a",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-c:a", "aac", "-b:a", "128k", "-shortest",
                    cover_voiced,
                ], capture_output=True, check=True)
            else:
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", cover_render_out, "-i", cover_audio,
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    "-map", "0:v", "-map", "1:a", "-shortest",
                    cover_voiced,
                ], capture_output=True, check=True)
        else:
            shutil.copy2(cover_render_out, cover_voiced)
        print(f"    -> {cover_voiced} ({get_duration(cover_voiced):.1f}s)")
    else:
        print("  封面配音: 已存在，跳过")


# ── Step 6: Concat ───────────────────────────────────────────


def step_concat(cfg):
    """拼接所有场景 → 输出最终视频"""
    src_dir = cfg["_voiced_dir"]
    speed = float(cfg["output"].get("speed", 1.0))
    output_dir = cfg["output"].get("dir", cfg["_project_dir"])
    os.makedirs(output_dir, exist_ok=True)

    print("=" * 50)
    print(f"Step: 拼接 → {speed}x")
    print("=" * 50)

    concat_file = None
    tmp_video_path = None
    try:
        # 收集所有视频文件（封面 + 场景）
        video_files = []
        cover_voiced = os.path.join(src_dir, "cover_voiced.mp4")
        if cfg.get("cover") and os.path.exists(cover_voiced):
            video_files.append(cover_voiced)
        for scene in cfg["scenes"]:
            path = os.path.join(src_dir, f"{scene['name']}.mp4")
            if not os.path.exists(path):
                print(f"\n  错误: 场景视频不存在 ({path})")
                sys.exit(1)
            video_files.append(path)

        n = len(video_files)
        final_name = _output_name(cfg, speed=speed)
        final_output = os.path.join(output_dir, final_name)

        # 安全校验：输出文件必须在 output_dir 内
        if not os.path.normpath(os.path.abspath(final_output)).startswith(
            os.path.normpath(os.path.abspath(output_dir))
        ):
            print(f"\n  错误: 输出路径越界 ({final_output})")
            sys.exit(1)

        # 构建 filter_complex concat（自动处理不同音频采样率/声道数）
        def _build_concat_cmd(inputs, output, extra_filters=""):
            """用 filter_complex concat 拼接，兼容不同音频格式"""
            cmd = ["ffmpeg", "-y"]
            for f in inputs:
                cmd += ["-i", f]
            filter_inputs = "".join(f"[{i}:v][{i}:a]" for i in range(len(inputs)))
            filter_str = f"{filter_inputs}concat=n={len(inputs)}:v=1:a=1[v][a]"
            if extra_filters:
                filter_str += f";{extra_filters}"
            cmd += [
                "-filter_complex", filter_str,
                "-map", "[v]", "-map", "[a]",
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2",
            ]
            cmd.append(output)
            return cmd

        if speed == 1.0:
            print(f"\n  拼接 → {final_name}")
            cmd = _build_concat_cmd(video_files, final_output)
            subprocess.run(cmd, capture_output=True, check=True)
        else:
            tmp_fd = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp_video_path = tmp_fd.name
            tmp_fd.close()

            cmd = _build_concat_cmd(video_files, tmp_video_path)
            subprocess.run(cmd, capture_output=True, check=True)

            print(f"\n  拼接 + {speed}x → {final_name}")
            subprocess.run([
                "ffmpeg", "-y", "-i", tmp_video_path,
                "-filter_complex",
                f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]",
                "-map", "[v]", "-map", "[a]",
                final_output,
            ], capture_output=True, check=True)

        # ── 背景音乐混入 ──
        bgm_cfg = cfg.get("bgm", {})
        bgm_file_rel = bgm_cfg.get("file", "") if isinstance(bgm_cfg, dict) else ""
        if bgm_file_rel:
            _proj = cfg.get("_project_dir", ".")
            bgm_file_abs = (bgm_file_rel if os.path.isabs(bgm_file_rel)
                            else os.path.join(_proj, bgm_file_rel))
            if os.path.exists(bgm_file_abs):
                bgm_vol = bgm_cfg.get("volume", 0.05)
                voice_vol = bgm_cfg.get("voice_volume", 1.0)
                fade_out_sec = bgm_cfg.get("fade_out", 3)
                vid_dur = get_duration(final_output)
                fade_start = max(0, vid_dur - fade_out_sec)
                tmp_bgm = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", final_output,
                    "-stream_loop", "-1", "-i", bgm_file_abs,
                    "-filter_complex",
                    (f"[0:a]volume={voice_vol}[voice];"
                     f"[1:a]volume={bgm_vol},atrim=0:{vid_dur},"
                     f"afade=t=out:st={fade_start}:d={fade_out_sec}[bgm];"
                     f"[voice][bgm]amix=inputs=2:duration=first[aout]"),
                    "-map", "0:v", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                    tmp_bgm,
                ], capture_output=True, check=True)
                os.replace(tmp_bgm, final_output)
                print(f"  背景音乐: 已混入 ({bgm_vol*100:.0f}% 音量, {fade_out_sec}s 淡出)")

        dur = get_duration(final_output)
        size_mb = os.path.getsize(final_output) / 1024 / 1024
        print(f"    -> {final_output}")
        print(f"    -> {dur:.1f}s ({size_mb:.1f}MB)")
        print("\n  完成!")
    finally:
        if concat_file and os.path.exists(concat_file):
            os.remove(concat_file)
        if tmp_video_path and os.path.exists(tmp_video_path):
            os.remove(tmp_video_path)


# ── Pipeline 编排 ────────────────────────────────────────────


def step_keywords(cfg):
    """用 AI 自动为每个场景生成插画关键词（每3-5句一张图）"""
    import anthropic

    print("=" * 50)
    print("Step: 自动生成插画关键词")
    print("=" * 50)

    media_dir = cfg["_manim_media_dir"]
    os.makedirs(media_dir, exist_ok=True)
    cache_path = os.path.join(media_dir, "auto_keywords.json")

    # 读已有缓存
    cached = {}
    if os.path.exists(cache_path):
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)

    client = anthropic.Anthropic()
    result = {}

    for scene in cfg["scenes"]:
        name = scene["name"]

        # 手动写了 illustration_keywords → 跳过，优先用手写的
        manual_kws = scene.get("illustration_keywords", [])
        if any(k for k in manual_kws if k):
            print(f"  [{name}] 使用手动 keywords，跳过")
            result[name] = manual_kws
            continue

        # 取 narration 句子列表
        full_text = scene.get("narration", "").strip()
        sentences = [s.strip() for s in full_text.split("\n") if s.strip()]
        if not sentences:
            continue

        # 用句子列表做缓存 key（内容不变就复用）
        content_hash = hashlib.md5("\n".join(sentences).encode()).hexdigest()[:8]
        if name in cached and cached[name].get("_hash") == content_hash:
            print(f"  [{name}] 已缓存，跳过（{sum(1 for k in cached[name]['keywords'] if k)} 张图）")
            result[name] = cached[name]["keywords"]
            continue

        print(f"  [{name}] 生成中（{len(sentences)} 句）...")

        numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(sentences))
        prompt = f"""你是一个视频分镜助手。下面是一段口播视频的逐句文稿，共 {len(sentences)} 句。

请将这些句子分成若干「概念块」（每块3-5句，内容讲同一件事），每块生成一个简洁的英文关键词（3-6个词），用于生成手绘插画。

规则：
- 每个概念块只出现一张图，块内其余句子填 null
- 关键词必须是英文，描述画面内容（人物动作/场景），不是主题词
- 图片总数控制在 {max(4, len(sentences)//4)} 到 {max(8, len(sentences)//3)} 张之间
- 优先在语义转折点换图（比如"转折词：但/然而/所以/第一/第二"出现时）

文稿：
{numbered}

请直接输出 JSON 数组，长度与句子数相同，每个元素是英文关键词字符串或 null。
例如（4句文稿）：["boss overwhelmed at desk", null, null, "vicious cycle arrows spinning"]
只输出 JSON，不要其他文字。"""

        message = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = message.content[0].text.strip()

        # 解析 JSON
        try:
            # 去掉可能的 markdown 代码块
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            keywords = json.loads(raw.strip())
            if not isinstance(keywords, list) or len(keywords) != len(sentences):
                raise ValueError(f"长度不匹配: {len(keywords)} vs {len(sentences)}")
        except Exception as e:
            print(f"  [{name}] 解析失败: {e}，使用回退策略")
            # 回退：每4句换一张图
            keywords = []
            for i in range(len(sentences)):
                if i % 4 == 0:
                    keywords.append(f"scene concept {i//4 + 1}")
                else:
                    keywords.append(None)

        count = sum(1 for k in keywords if k)
        print(f"  [{name}] 完成，共 {count} 张图")
        result[name] = keywords

        # 保存缓存
        cached[name] = {"_hash": content_hash, "keywords": keywords}
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(cached, f, ensure_ascii=False, indent=2)

    # 将结果注入 cfg，供后续步骤使用
    _inject_auto_keywords(cfg, result)

    # 保存完整结果
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cached, f, ensure_ascii=False, indent=2)

    print("\n  关键词生成完成!")


def _inject_auto_keywords(cfg, keywords_map):
    """将自动生成的 keywords 注入 cfg scenes，供 illustrations 和 render 使用"""
    for scene in cfg["scenes"]:
        name = scene["name"]
        if name in keywords_map:
            manual = scene.get("illustration_keywords", [])
            if not any(k for k in manual if k):
                scene["illustration_keywords"] = keywords_map[name]


def _load_auto_keywords(cfg):
    """从缓存文件读取并注入 auto keywords（单步运行时使用）"""
    cache_path = os.path.join(cfg["_manim_media_dir"], "auto_keywords.json")
    if not os.path.exists(cache_path):
        return
    with open(cache_path, "r", encoding="utf-8") as f:
        cached = json.load(f)
    result = {name: data["keywords"] if isinstance(data, dict) else data
              for name, data in cached.items()}
    _inject_auto_keywords(cfg, result)


STEPS = {
    "keywords": step_keywords,
    "tts": step_tts,
    "illustrations": step_illustrations,
    "render": step_render,
    "voice": step_voice,
    "cover": step_cover,
    "concat": step_concat,
}

STEP_ORDER = ["keywords", "tts", "illustrations", "render", "voice", "cover", "concat"]


def _validate_narration(cfg):
    """校验旁白质量，关键词数量不匹配时阻断，其他问题打印警告"""
    max_chars = cfg.get("layout", {}).get("max_chars_per_card", 18)
    warnings = []
    errors = []

    for scene in cfg.get("scenes", []):
        name = scene["name"]
        narration = scene.get("narration", "").strip()
        sentences = [s.strip() for s in narration.split("\n") if s.strip()]
        keywords = scene.get("illustration_keywords", [])

        # 硬错误: 关键词数量与句子数量不匹配
        if keywords and len(keywords) != len(sentences):
            errors.append(
                f"[{name}] illustration_keywords ({len(keywords)}) "
                f"与 narration 句数 ({len(sentences)}) 不匹配"
            )

        for i, sent in enumerate(sentences):
            # 警告: 句子超长
            if len(sent) > max_chars:
                warnings.append(
                    f"[{name}] 句{i} 超长 ({len(sent)}>{max_chars}字): "
                    f"{sent[:25]}..."
                )

            # 警告: 结尾标点不规范
            if sent and sent[-1] not in "。！？…—":
                warnings.append(
                    f"[{name}] 句{i} 结尾非句号/问号/感叹号: ...{sent[-5:]}"
                )

            # 警告: 句内逗号（影响 TTS 静音检测）
            if "，" in sent or "," in sent:
                warnings.append(
                    f"[{name}] 句{i} 含逗号（可能影响音画同步）: "
                    f"{sent[:25]}..."
                )

    if warnings:
        print("=" * 50)
        print("旁白质量检查")
        print("=" * 50)
        for w in warnings:
            print(f"  [警告] {w}")
        print()

    if errors:
        if not warnings:
            print("=" * 50)
            print("旁白质量检查")
            print("=" * 50)
        for e in errors:
            print(f"  [错误] {e}")
        print("\n  关键词数量不匹配是硬错误，请修复后重试")
        sys.exit(1)


def run_pipeline(cfg, step=None):
    """编排所有步骤或单独运行某一步"""
    title = cfg["title"]
    print(f"\n{'#' * 50}")
    print(f"  图文卡片视频管线: {title}")
    print(f"{'#' * 50}\n")

    # 全量运行时自动校验旁白质量
    if not step:
        _validate_narration(cfg)

    if step:
        if step not in STEPS:
            print(f"未知步骤: {step}")
            print(f"可用步骤: {', '.join(STEP_ORDER)}")
            sys.exit(1)
        # 单步运行 illustrations/render 时，自动加载已缓存的 auto keywords
        if step in ("illustrations", "render"):
            _load_auto_keywords(cfg)
        STEPS[step](cfg)
    else:
        t0 = time.time()
        for s in STEP_ORDER:
            # keywords 步骤：插画未启用则跳过
            if s == "keywords" and not cfg.get("illustrations", {}).get("enabled"):
                continue
            # 插画未启用则跳过
            if s == "illustrations" and not cfg.get("illustrations", {}).get("enabled"):
                continue
            # 封面未配置则跳过
            if s == "cover" and not cfg.get("cover"):
                continue
            print()
            STEPS[s](cfg)

        elapsed = time.time() - t0
        print(f"\n{'#' * 50}")
        print(f"  全部完成! 总耗时: {elapsed:.0f}s")
        print(f"{'#' * 50}")
