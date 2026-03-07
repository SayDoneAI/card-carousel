---
name: card-carousel
description: "Generate vertical card-style narration videos with Manim rendering, AI illustrations, and TTS voiceover. Use when the user wants to create 竖屏卡片口播视频, card carousel videos, or narration videos with text cards and illustrations."
---

# Card Carousel — 图文卡片口播视频生成器

Generate vertical (1080x1440, 3:4) card-style narration videos: Manim rendering + AI illustrations + TTS voiceover → final video.

## Quick Reference

```
PROJECT=~/Documents/RedCode/card-carousel
```

## Prerequisites

- Repo cloned at `~/Documents/RedCode/card-carousel`
- Python deps: `pip install -r $PROJECT/requirements.txt`
- System deps: `brew install ffmpeg`
- Manim: `pip install manim`
- TTS: `export VOLC_API_KEY=<key>` in `$PROJECT/.env`
- AI images: `export GEMINI_API_KEY=<key>` and `export GEMINI_BASE_URL=<url>` in `$PROJECT/.env`

## Pipeline Steps

```
tts → illustrations → render → voice → concat
```

| Step | What it does |
|------|-------------|
| `tts` | Sentence-level TTS → measure duration → concat → write timing JSON |
| `illustrations` | Generate AI illustrations per keyword, cache to `.cache/`, copy to `assets/` |
| `render` | Manim render all scenes (injects env vars for template scene.py) |
| `voice` | Merge TTS audio onto rendered video (ffmpeg) |
| `concat` | Concatenate all scenes → apply speed → final output |

## Execution Workflow

**CRITICAL: Follow every step in order. Do NOT skip any step.**

### Step 1: Prepare Content Config

Create a YAML config file. Two modes are supported:

#### Template Mode (recommended for new content)

```yaml
template: minimal-insight
title: "视频标题"

brand:
  logo_char: "赋"
  author: "@黄赋"
  topic: "主题句（红色居中显示）"
  pinyin: "HUANG FU"

voice:
  provider: volcengine
  voice_type: zh_male_ruyayichen_uranus_bigtts
  cluster: volcano_tts
  speed: 1.0

illustrations:
  enabled: true
  engine: gemini
  model: gemini-3.1-flash-image-preview
  fallback_engine: doubao
  fallback_model: doubao-seedream-5-0-260128
  style_prompt: "Minimalist line drawing, black ink with red accents, white background"
  cache_dir: ".cache/illustrations"
  gen_tool: "tools/image_gen.py"

output:
  speed: 1.0

scenes:
  - name: Scene01_Cards
    narration: |
      第一句旁白
      第二句旁白
      第三句旁白
    illustration_keywords:
      - keyword for illustration 1
      - null
      - keyword for illustration 2
```

#### Legacy Mode (direct script reference)

```yaml
title: "标题"
manim_script: "explainer.py"
render_quality: "l"
voice: { ... }
scenes: [ ... ]
```

### Step 2: Run Pipeline

```bash
cd $PROJECT

# Full pipeline
python pipeline.py <config.yaml>

# Single step
python pipeline.py <config.yaml> --step tts
python pipeline.py <config.yaml> --step illustrations
python pipeline.py <config.yaml> --step render
python pipeline.py <config.yaml> --step voice
python pipeline.py <config.yaml> --step concat

# With speed adjustment
python pipeline.py <config.yaml> --speed 1.5
```

### Step 3: Verify Output

Output video will be at `$PROJECT/<title>_<date>.mp4` (or in `output.dir` if configured).

Check the output:
```bash
ffprobe -v quiet -show_format -show_streams <output.mp4> 2>/dev/null | grep -E 'width|height|duration|size'
```

## Available Templates

| Template | Description | Style |
|----------|-------------|-------|
| `minimal-insight` | 极简洞见 | 白底大字卡片 + 水墨插画 + 底栏标签 |

## Config Fields Reference

### Brand (per template, override defaults)

| Field | Description | Example |
|-------|-------------|---------|
| `logo_char` | Circle logo character | `"赋"` |
| `author` | Author name display | `"@黄赋"` |
| `topic` | Red centered theme line | `"在专业面前像学徒"` |
| `pinyin` | Pinyin subtitle | `"HUANG FU"` |
| `disclaimer` | Bottom-right disclaimer | `"个人观点\n仅供参考"` |
| `footer_tags` | Bottom bar tag lines (list) | `["强者思维 ｜ 认知进化"]` |

### Illustration Keywords

- Each sentence in `narration` maps to one entry in `illustration_keywords`
- `null` = reuse previous illustration (no slide animation)
- Non-null keyword = generate new illustration, slide transition left→right
- Keywords should be English, descriptive (e.g., `"growth obstacle"`, `"lion roaring"`)

### Voice Providers

| Provider | Required Config |
|----------|----------------|
| `volcengine` | `voice_type`, `cluster`, needs `VOLC_API_KEY` |
| `edge` | `voice_type` (e.g., `zh-CN-YunxiNeural`), no API key needed |

### Image Engines

| Engine | Description | Cost |
|--------|-------------|------|
| `gemini` | Gemini via sucloud proxy, fast | Low |
| `doubao` | Doubao seedream, high quality | High |
| `kling` | Kling built-in async polling | Medium |

Use `engine` + `fallback_engine` for automatic failover.

## Creating a New Template

1. Create `templates/<name>/` with:
   - `__init__.py` — subclass `BaseTemplate`, register with `REGISTRY["name"] = Class`
   - `scene.py` — Manim scene classes (read config via `_load_config()`)
   - `defaults.yaml` — default layout/colors/brand config

2. Register in `templates/__init__.py`:
   ```python
   from templates.<name> import <ClassName>
   REGISTRY["<name>"] = <ClassName>
   ```

3. Template scene.py must:
   - Read `CARD_CAROUSEL_PROJECT_DIR` env var for project root (fallback: `Path(__file__).parents[2]`)
   - Read `CARD_CAROUSEL_CONFIG_PATH` env var for config (fallback: `<project_root>/config.yaml`)
   - Read `CARD_CAROUSEL_AUDIO_DIR` and `CARD_CAROUSEL_TIMING_FILE` for audio/timing

## Troubleshooting

| Issue | Solution |
|-------|---------|
| TTS fails | Check `VOLC_API_KEY` in `.env`, try `--step tts` alone |
| Image gen fails | Check `GEMINI_API_KEY`/`GEMINI_BASE_URL`, fallback engine will be tried automatically |
| Manim render fails | Ensure `manim` installed, try `manim -ql templates/minimal_insight/scene.py Scene01_Cards` directly |
| Video too short/long | Check `_timing.json` in media dir, re-run `--step tts` to regenerate |
| Audio/video mismatch | Delete `media/videos/<template>/voiced/` and re-run `--step voice` |

## Architecture

```
pipeline.py (CLI entry)
  → core/config.py (load YAML + .env + template merge + path derivation)
  → core/orchestrator.py (5-step pipeline)
      → engines/tts/ (ABC + factory: volcengine | edge)
      → engines/image/ (ABC + factory: gemini | doubao | kling)
      → templates/ (registry + BaseTemplate ABC)
          → minimal_insight/scene.py (Manim rendering)
```
