#!/usr/bin/env python3
"""
Nano Banana Image Generator — 多引擎图片生成工具

支持两个引擎:
  - gemini (默认): Google GenAI SDK，走 Proxy 或 Official 模式
  - doubao: OpenAI 兼容 /v1/images/generations，支持图生图

依赖:
  pip install google-genai Pillow python-dotenv httpx
"""

import os
import sys
import time
import base64
import argparse
import mimetypes
from pathlib import Path
from dotenv import load_dotenv


def _load_project_dotenv():
    """自动加载脚本向上目录中的 .env（若存在）"""
    for parent in Path(__file__).resolve().parents:
        env_file = parent / ".env"
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)
            break


_load_project_dotenv()

# 可选依赖: PIL (用于报告图片分辨率)
try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Constants                                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

# Gemini 支持的全部宽高比
VALID_ASPECT_RATIOS = [
    "1:1", "1:4", "1:8",
    "2:3", "3:2", "3:4", "4:1", "4:3",
    "4:5", "5:4", "8:1", "9:16", "16:9", "21:9"
]

# 官方文档: "512px", "1K", "2K", "4K" (必须大写 K)
VALID_IMAGE_SIZES = ["512px", "1K", "2K", "4K"]

# 引擎 → 默认模型
ENGINE_DEFAULTS = {
    "gemini": "gemini-3.1-flash-image-preview",
    "doubao": "doubao-seedream-5-0-260128",
}

VALID_ENGINES = list(ENGINE_DEFAULTS.keys())

# 宽高比 → doubao 尺寸映射
ASPECT_RATIO_TO_SIZE = {
    "1:1": "1024x1024",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
    "3:4": "1024x1365",
    "4:3": "1365x1024",
    "4:5": "1024x1280",
    "5:4": "1280x1024",
    "9:16": "1024x1820",
    "16:9": "1820x1024",
}

# 重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 10
RETRY_BACKOFF = 2


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Utilities                                                      ║
# ╚══════════════════════════════════════════════════════════════════╝

def save_binary_file(file_name: str, data: bytes):
    """保存二进制数据到文件"""
    with open(file_name, "wb") as f:
        f.write(data)
    print(f"File saved to: {file_name}")


def _resolve_output_path(prompt: str, output_dir: str = None,
                         filename: str = None, ext: str = ".png") -> str:
    """根据参数计算最终的输出文件路径"""
    if filename:
        file_name = os.path.splitext(filename)[0]
    else:
        safe = "".join(c for c in prompt if c.isalnum() or c in (' ', '_')).rstrip()
        safe = safe.replace(" ", "_").lower()[:30]
        file_name = safe or "generated_image"

    full_name = f"{file_name}{ext}"
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        return os.path.join(output_dir, full_name)
    return full_name


def _normalize_image_size(image_size: str) -> str:
    """大小写容错: "2k" → "2K", "512PX" → "512px" """
    s = image_size.strip()
    upper = s.upper()
    if upper in ("1K", "2K", "4K"):
        return upper
    if upper in ("512PX", "512"):
        return "512px"
    return s


def _report_resolution(path: str):
    """尝试用 PIL 报告图片分辨率"""
    if HAS_PIL:
        try:
            img = PILImage.open(path)
            print(f"  Resolution:   {img.size[0]}x{img.size[1]}")
        except Exception:
            pass


def _is_rate_limit_error(e: Exception) -> bool:
    """判断异常是否为速率限制 (429) 错误"""
    err_str = str(e).lower()
    return "429" in err_str or "rate" in err_str or "quota" in err_str or "resource_exhausted" in err_str


def _load_reference_image(input_path: str, target_aspect_ratio: str = None) -> str:
    """加载参考图片，按目标比例居中裁剪后返回 data URL (base64)。

    doubao img2img 模式会忽略 size 参数，输出跟着参考图比例走，
    所以必须在上传前把参考图裁成目标比例。
    """
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Reference image not found: {input_path}")

    if target_aspect_ratio and HAS_PIL:
        # 解析目标比例
        parts = target_aspect_ratio.split(":")
        if len(parts) == 2:
            try:
                tw, th = float(parts[0]), float(parts[1])
                target_ratio = tw / th

                img = PILImage.open(p).convert("RGBA")
                src_w, src_h = img.size
                src_ratio = src_w / src_h

                # 只在比例差异 > 5% 时适配
                if abs(src_ratio - target_ratio) / target_ratio > 0.05:
                    # contain 模式：缩放适配 + 白色填充，保留完整图片内容
                    # （裁剪会丢失人像等关键内容）
                    target_size = ASPECT_RATIO_TO_SIZE.get(target_aspect_ratio, "1024x1024")
                    tw_px, th_px = [int(x) for x in target_size.split("x")]
                    # 计算缩放比例（contain：取小的一边）
                    scale = min(tw_px / src_w, th_px / src_h)
                    new_w = int(src_w * scale)
                    new_h = int(src_h * scale)
                    resized = img.resize((new_w, new_h), PILImage.LANCZOS)
                    # 创建白色画布，居中放置
                    canvas = PILImage.new("RGB", (tw_px, th_px), (255, 255, 255))
                    paste_x = (tw_px - new_w) // 2
                    paste_y = (th_px - new_h) // 2
                    canvas.paste(resized, (paste_x, paste_y), resized if resized.mode == "RGBA" else None)
                    img = canvas
                    print(f"  Reference image fitted: {src_w}x{src_h} → {tw_px}x{th_px} ({target_aspect_ratio}, contain)")

                import io
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                return f"data:image/png;base64,{b64}"
            except (ValueError, ZeroDivisionError):
                pass  # 解析失败，回退到原图

    mime, _ = mimetypes.guess_type(str(p))
    if not mime:
        mime = "image/png"

    with open(p, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    return f"data:{mime};base64,{b64}"


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Gemini — Google GenAI SDK (Official / Proxy)                   ║
# ╚══════════════════════════════════════════════════════════════════╝

def _generate_gemini_official(api_key: str, prompt: str, negative_prompt: str = None,
                              aspect_ratio: str = "1:1", image_size: str = "2K",
                              output_dir: str = None, filename: str = None,
                              model: str = "gemini-3.1-flash-image-preview") -> str:
    """Official Mode: 直连 Google 官方 GenAI API (流式)"""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    final_prompt = prompt
    if negative_prompt:
        final_prompt += f"\n\nNegative prompt: {negative_prompt}"

    config_kwargs = {
        "response_modalities": ["IMAGE"],
        "image_config": types.ImageConfig(
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        ),
    }
    if "flash" in model.lower():
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_level="MINIMAL")
    config = types.GenerateContentConfig(**config_kwargs)

    print(f"[Gemini Official Mode]")
    print(f"  Model:        {model}")
    print(f"  Prompt:       {final_prompt[:120]}{'...' if len(final_prompt) > 120 else ''}")
    print(f"  Aspect Ratio: {aspect_ratio}")
    print(f"  Image Size:   {image_size}")
    print()

    import threading
    start_time = time.time()
    print(f"  ⏳ Generating...", end="", flush=True)

    heartbeat_stop = threading.Event()

    def _heartbeat():
        while not heartbeat_stop.is_set():
            heartbeat_stop.wait(5)
            if not heartbeat_stop.is_set():
                elapsed = time.time() - start_time
                print(f" {elapsed:.0f}s...", end="", flush=True)

    hb_thread = threading.Thread(target=_heartbeat, daemon=True)
    hb_thread.start()

    last_image_data = None
    chunk_count = 0
    total_bytes = 0

    for chunk in client.models.generate_content_stream(
        model=model, contents=[final_prompt], config=config,
    ):
        elapsed = time.time() - start_time
        if chunk.parts is None:
            continue
        for part in chunk.parts:
            if part.text is not None:
                print(f"\n  Model says: {part.text}", end="", flush=True)
            elif part.inline_data is not None:
                chunk_count += 1
                data_size = len(part.inline_data.data) if part.inline_data.data else 0
                total_bytes += data_size
                size_str = f"{data_size / 1024:.0f}KB" if data_size < 1048576 else f"{data_size / 1048576:.1f}MB"
                print(f"\n  📦 Chunk #{chunk_count} received ({size_str}, {elapsed:.1f}s)", end="", flush=True)
                last_image_data = part

    heartbeat_stop.set()
    hb_thread.join(timeout=1)

    elapsed = time.time() - start_time
    print(f"\n  ✅ Stream complete ({elapsed:.1f}s, {chunk_count} chunk(s), {total_bytes / 1024:.0f}KB total)")

    if last_image_data is not None and last_image_data.inline_data is not None:
        if chunk_count > 1:
            print(f"  Keeping the final chunk (highest quality).")
        image = last_image_data.as_image()
        path = _resolve_output_path(prompt, output_dir, filename, ".png")
        image.save(path)
        print(f"File saved to: {path}")
        _report_resolution(path)
        return path

    raise RuntimeError("No image was generated. The server may have refused the request.")


def _generate_gemini_proxy(api_key: str, base_url: str, prompt: str,
                           negative_prompt: str = None,
                           aspect_ratio: str = "1:1", image_size: str = "4K",
                           output_dir: str = None, filename: str = None,
                           model: str = "gemini-3.1-flash-image-preview") -> str:
    """Proxy Mode: 通过 sucloud 等代理访问 Gemini (Google GenAI SDK 流式)"""
    from google import genai
    from google.genai import types

    client = genai.Client(
        api_key=api_key,
        http_options={'base_url': base_url},
    )

    final_prompt = f"{prompt} --ar {aspect_ratio}"
    if negative_prompt:
        final_prompt += f"\n\nNegative prompt: {negative_prompt}"

    config = types.GenerateContentConfig(response_modalities=["IMAGE"])
    contents = [types.Content(role="user", parts=[types.Part.from_text(text=final_prompt)])]

    print(f"[Gemini Proxy Mode]")
    print(f"  Base URL:     {base_url}")
    print(f"  Model:        {model}")
    print(f"  Prompt:       {final_prompt[:120]}{'...' if len(final_prompt) > 120 else ''}")
    print(f"  Aspect Ratio: {aspect_ratio}")
    print(f"  Image Size:   {image_size}")
    print()

    last_image_data = None
    chunk_count = 0

    for chunk in client.models.generate_content_stream(
        model=model, contents=contents, config=config,
    ):
        # 从 chunk 中提取 parts（兼容两种响应格式）
        parts = None
        if chunk.parts:
            parts = chunk.parts
        elif (hasattr(chunk, 'candidates') and chunk.candidates
              and chunk.candidates[0].content
              and chunk.candidates[0].content.parts):
            parts = chunk.candidates[0].content.parts

        if not parts:
            continue
        part = parts[0]
        if part.inline_data and part.inline_data.data:
            chunk_count += 1
            last_image_data = (part.inline_data.data, part.inline_data.mime_type)
        elif hasattr(part, 'text') and part.text:
            print(f"  Server says: {part.text}")

    if last_image_data:
        data_buffer, mime_type = last_image_data
        if chunk_count > 1:
            print(f"  Received {chunk_count} image chunks, keeping the final (highest quality) one.")

        ext = mimetypes.guess_extension(mime_type) or ".png"
        if ext in ('.jpe', '.jpeg'):
            ext = '.jpg'

        path = _resolve_output_path(prompt, output_dir, filename, ext)
        save_binary_file(path, data_buffer)
        _report_resolution(path)
        return path

    raise RuntimeError("No image was generated. The server may have refused the request.")


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Doubao — OpenAI 兼容 /v1/images/generations                    ║
# ╚══════════════════════════════════════════════════════════════════╝

def _generate_doubao(api_key: str, base_url: str, prompt: str,
                     negative_prompt: str = None,
                     aspect_ratio: str = "1:1",
                     output_dir: str = None, filename: str = None,
                     model: str = "doubao-seedream-5-0-260128",
                     input_image: str = None,
                     strength: float = None) -> str:
    """
    通过 OpenAI 兼容接口 (/v1/images/generations) 生成图片。
    支持文生图和图生图（传入 input_image）。
    """
    import httpx

    url = f"{base_url.rstrip('/')}/v1/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    size = ASPECT_RATIO_TO_SIZE.get(aspect_ratio, "1024x1024")

    final_prompt = prompt
    if negative_prompt:
        final_prompt += f"\n\nNegative prompt: {negative_prompt}"

    body = {
        "model": model,
        "prompt": final_prompt,
        "n": 1,
        "size": size,
        "response_format": "b64_json",
    }

    mode_label = "图生图" if input_image else "文生图"
    if input_image:
        body["image"] = input_image
        if strength is not None:
            body["strength"] = strength

    print(f"[Doubao Mode — {mode_label}]")
    print(f"  Base URL:     {base_url}")
    print(f"  Model:        {model}")
    print(f"  Prompt:       {final_prompt[:120]}{'...' if len(final_prompt) > 120 else ''}")
    print(f"  Size:         {size}")
    if input_image:
        if input_image.startswith("http"):
            print(f"  Input Image:  {input_image[:80]}...")
        else:
            print(f"  Input Image:  base64 ({len(input_image)} chars)")
    print()

    start_time = time.time()
    print(f"  ⏳ Generating...", end="", flush=True)

    timeout = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)
    resp = httpx.post(url, json=body, headers=headers, timeout=timeout, verify=False)

    elapsed = time.time() - start_time

    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
        err_msg = data.get("error", {}).get("message", str(e))
        raise RuntimeError(f"API error ({resp.status_code}): {err_msg}") from e

    data = resp.json()
    items = data.get("data") if isinstance(data, dict) else None
    if not items or not isinstance(items, list) or not isinstance(items[0], dict):
        raise RuntimeError(f"Unexpected response format: {data}")

    item = items[0]
    b64_data = item.get("b64_json")

    print(f"\n  ✅ Generated ({elapsed:.1f}s)")

    if b64_data:
        # b64_json 模式：直接解码保存，无需下载 CDN
        import base64 as b64mod
        img_bytes = b64mod.b64decode(b64_data)
        # 火山引擎可能在数据前插入 AIGC 水印头，需要找到真正的图片起始位置
        jpg_offset = img_bytes.find(b'\xff\xd8\xff')
        png_offset = img_bytes.find(b'\x89PNG\r\n\x1a\n')
        if jpg_offset >= 0 and (png_offset < 0 or jpg_offset < png_offset):
            img_bytes = img_bytes[jpg_offset:]
            ext = '.jpg'
        elif png_offset >= 0:
            img_bytes = img_bytes[png_offset:]
            ext = '.png'
        else:
            ext = '.png'
        if jpg_offset > 0 or png_offset > 0:
            print(f"  Mode: b64_json (跳过 {max(jpg_offset, png_offset)} 字节 AIGC 水印头)")
        else:
            print(f"  Mode: b64_json (直接解码，跳过 CDN)")
        path = _resolve_output_path(prompt, output_dir, filename, ext)
        save_binary_file(path, img_bytes)
    else:
        # fallback: URL 模式（兼容不支持 b64_json 的情况）
        image_url = item.get("url")
        if not image_url:
            raise RuntimeError("Response missing both 'b64_json' and 'url' fields")
        print(f"  Image URL: {image_url[:100]}...")
        dl_url = image_url.replace("https://", "http://", 1)
        dl_resp = httpx.get(dl_url, timeout=60, follow_redirects=True)
        dl_resp.raise_for_status()
        content_type = dl_resp.headers.get("content-type", "image/png")
        ext = mimetypes.guess_extension(content_type.split(";")[0]) or ".png"
        if ext in ('.jpe', '.jpeg'):
            ext = '.jpg'
        path = _resolve_output_path(prompt, output_dir, filename, ext)
        save_binary_file(path, dl_resp.content)

    _report_resolution(path)
    return path


# ╔══════════════════════════════════════════════════════════════════╗
# ║  Entry Point                                                    ║
# ╚══════════════════════════════════════════════════════════════════╝

def generate(prompt: str, negative_prompt: str = None,
             aspect_ratio: str = "1:1", image_size: str = "2K",
             output_dir: str = None, filename: str = None,
             model: str = None, engine: str = "gemini",
             input_image: str = None,
             strength: float = None,
             max_retries: int = MAX_RETRIES) -> str:
    """
    图像生成统一入口（带自动重试）。

    Args:
        prompt: 正向提示词
        negative_prompt: 负面提示词
        aspect_ratio: 宽高比
        image_size: 图片尺寸，仅 gemini 引擎有效
        output_dir: 输出目录
        filename: 输出文件名 (不含扩展名)
        model: 模型名称（默认按 engine 自动选择）
        engine: 引擎 "gemini" | "doubao"
        input_image: 参考图片路径（仅 doubao 引擎支持图生图）
        max_retries: 最大重试次数

    Returns:
        保存的图片文件路径
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    base_url = os.environ.get("GEMINI_BASE_URL")

    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is not set.")

    if engine not in VALID_ENGINES:
        raise ValueError(f"Invalid engine '{engine}'. Valid: {VALID_ENGINES}")

    if model is None:
        model = ENGINE_DEFAULTS[engine]

    # 加载参考图片
    ref_data = None
    if input_image:
        if engine != "doubao":
            raise ValueError("--input (图生图) only supported with --engine doubao")
        ref_data = _load_reference_image(input_image, target_aspect_ratio=aspect_ratio)
        print(f"  Loaded reference image: {input_image}")

    # Gemini 引擎校验
    if engine == "gemini":
        image_size = _normalize_image_size(image_size)
        if aspect_ratio not in VALID_ASPECT_RATIOS:
            raise ValueError(f"Invalid aspect ratio '{aspect_ratio}'. Valid: {VALID_ASPECT_RATIOS}")
        if image_size not in VALID_IMAGE_SIZES:
            raise ValueError(f"Invalid image size '{image_size}'. Valid: {VALID_IMAGE_SIZES}")

    # ── Retry loop ──
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            if engine == "doubao":
                if not base_url:
                    raise ValueError("GEMINI_BASE_URL is required for doubao engine (sucloud proxy)")
                return _generate_doubao(
                    api_key, base_url, prompt, negative_prompt,
                    aspect_ratio, output_dir, filename, model, ref_data,
                    strength,
                )
            else:  # gemini
                if base_url:
                    return _generate_gemini_proxy(
                        api_key, base_url, prompt, negative_prompt,
                        aspect_ratio, image_size, output_dir, filename, model,
                    )
                else:
                    return _generate_gemini_official(
                        api_key, prompt, negative_prompt,
                        aspect_ratio, image_size, output_dir, filename, model,
                    )
        except Exception as e:
            last_error = e
            if attempt < max_retries and _is_rate_limit_error(e):
                delay = RETRY_BASE_DELAY * (RETRY_BACKOFF ** attempt)
                print(f"\n  ⚠️  Rate limit hit (attempt {attempt + 1}/{max_retries + 1}). "
                      f"Waiting {delay}s before retry...")
                time.sleep(delay)
            elif attempt < max_retries:
                delay = 5
                print(f"\n  ⚠️  Error (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                      f"Retrying in {delay}s...")
                time.sleep(delay)
            else:
                break

    raise RuntimeError(f"Failed after {max_retries + 1} attempts. Last error: {last_error}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Nano Banana — 多引擎图片生成工具 (gemini / doubao)"
    )
    parser.add_argument(
        "prompt", nargs="?", default="Nano Banana",
        help="The text prompt for image generation."
    )
    parser.add_argument(
        "--engine", "-e", default="gemini", choices=VALID_ENGINES,
        help=f"Engine to use. Default: gemini."
    )
    parser.add_argument(
        "--negative_prompt", "-n", default=None,
        help="Negative prompt to specify what to avoid."
    )
    parser.add_argument(
        "--aspect_ratio", default="1:1", choices=VALID_ASPECT_RATIOS,
        help=f"Aspect ratio. Default: 1:1."
    )
    parser.add_argument(
        "--image_size", default="2K",
        help=f"Image size (gemini only). Choices: {VALID_IMAGE_SIZES}. Default: 2K."
    )
    parser.add_argument(
        "--input", "-i", default=None, dest="input_image",
        help="Reference image path for image-to-image (doubao only)."
    )
    parser.add_argument(
        "--output", "-o", default=None,
        help="Output directory. Default: current directory."
    )
    parser.add_argument(
        "--filename", "-f", default=None,
        help="Output filename (without extension). Overrides auto-naming."
    )
    parser.add_argument(
        "--model", "-m", default=None,
        help=f"Model name. Defaults: gemini={ENGINE_DEFAULTS['gemini']}, doubao={ENGINE_DEFAULTS['doubao']}."
    )
    parser.add_argument(
        "--strength", "-s", type=float, default=None,
        help="Reference image strength for img2img (doubao only). 0.0=keep original, 1.0=ignore. Default: 0.5."
    )

    args = parser.parse_args()

    try:
        generate(
            args.prompt, args.negative_prompt, args.aspect_ratio,
            args.image_size, args.output, args.filename, args.model,
            args.engine, args.input_image, args.strength,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f"Error: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nInterrupted by user.")
        sys.exit(130)
