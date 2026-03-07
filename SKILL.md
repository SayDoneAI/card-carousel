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
- API keys 已配置在 `$PROJECT/.env`（TTS + 生图）

## User Input

**用户只需提供一个 Markdown 文档**，包含视频文案。其余所有配置走默认值。

示例输入（`认知升级.md`）：
```markdown
# 认知升级

真正阻碍一个人成长的从来不是能力不足
而是认知顺序的严重错位
他们把该敬畏的东西当成了敌人
面对专业他们毫无敬畏总觉得差不多就行了
```

用户也可以选择性提供：
- **主题句**（topic）— 红色居中显示的金句，不提供则留空
- **播放倍速** — 默认 1.0x
- **品牌覆盖** — 如果不是默认作者"黄赋"，需要提供 logo_char/author/pinyin

## Execution Workflow

**CRITICAL: Follow every step in order. Do NOT skip any step.**

### Step 1: 解析用户文案 → 生成 config.yaml

从用户的 md 文档中提取：
1. **标题** — 取 `# 标题` 或文件名
2. **旁白文案** — 正文内容，每行一句
3. **主题句** — 用户指定的金句，或从文案中提炼一句
4. **插画关键词** — **由你（Claude）自动生成**，规则：
   - 为每句旁白分配一个关键词或 `null`
   - 关键词用英文，描述性短语（如 `"growth obstacle"`, `"lion roaring"`）
   - 相邻句子内容相近时用 `null`（复用上一张插画，无切换动画）
   - 内容转折或场景变化时用新关键词（触发滑动动画）
   - 建议每 2-3 句换一张图，节奏感更好

生成的 config.yaml 放在 `$PROJECT/content/` 目录：

```yaml
template: minimal-insight
title: "认知升级"

brand:
  topic: "从文案中提炼的主题句"

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
  style_prompt: "Minimalist line drawing illustration, black ink with red accents only, simple clean sketch on pure white background, no background elements, no border, no frame, no text, centered composition, the illustration should seamlessly blend into a white page"
  cache_dir: ".cache/illustrations"
  gen_tool: "tools/image_gen.py"

output:
  speed: 1.0

scenes:
  - name: Scene01_Cards
    narration: |
      真正阻碍一个人成长的从来不是能力不足
      而是认知顺序的严重错位
      他们把该敬畏的东西当成了敌人
      面对专业他们毫无敬畏总觉得差不多就行了
    illustration_keywords:
      - growth obstacle
      - null
      - shield and sword
      - null
```

**注意**：
- `brand` 中只需要写 `topic`，其余字段（logo_char/author/pinyin 等）全部走模板默认值（黄赋）
- `voice` 和 `illustrations` 固定使用上述配置，不需要用户指定
- 如果文案很长（超过 15 句），拆成多个 Scene（Scene01_Cards, Scene02_Cards...）

### Step 2: Run Pipeline

```bash
cd $PROJECT
python pipeline.py content/<config>.yaml
```

如需单步调试：
```bash
python pipeline.py content/<config>.yaml --step tts           # 只跑 TTS
python pipeline.py content/<config>.yaml --step illustrations  # 只生成插画
python pipeline.py content/<config>.yaml --step render         # 只渲染 Manim
python pipeline.py content/<config>.yaml --step voice          # 合并音频
python pipeline.py content/<config>.yaml --step concat         # 拼接最终视频
```

### Step 3: Verify Output

```bash
ffprobe -v quiet -show_format -show_streams $PROJECT/<title>_*.mp4 2>/dev/null | grep -E 'width|height|duration|size'
```

## Pipeline Steps

```
tts → illustrations → render → voice → concat
```

| Step | What it does |
|------|-------------|
| `tts` | 逐句 TTS → 测时长 → 拼接 → 写 timing JSON |
| `illustrations` | 按关键词生成 AI 插画，缓存到 `.cache/`，复制到 `assets/` |
| `render` | Manim 渲染所有场景（注入环境变量供模板 scene.py 读取） |
| `voice` | 合并 TTS 音频到渲染好的视频 |
| `concat` | 拼接所有场景 → 应用倍速 → 最终输出 |

## Defaults (minimal-insight template)

| 配置项 | 默认值 |
|--------|--------|
| 模板 | `minimal-insight` |
| Logo | 赋 |
| 作者 | @黄赋 |
| 拼音 | HUANG FU |
| 语音 | 火山引擎 `zh_male_ruyayichen_uranus_bigtts` |
| 生图 | Gemini 主 / Doubao 备 |
| 画风 | 极简线描，黑墨+红色点缀，白底 |
| 倍速 | 1.0x |

## Illustration Keywords Guide

- 每句旁白对应一个关键词或 `null`
- `null` = 复用上一张插画（无切换动画）
- 非 null = 生成新插画 + 左右滑动切换动画
- 关键词用**英文**，描述性短语
- 好的关键词：`"mountain path"`, `"thin ice walking"`, `"lion roaring"`
- 差的关键词：`"认知"`, `"a person thinking about something"` (太抽象或太长)
- 节奏建议：每 2-3 句换一张图

## Available Templates

| Template | Description | Style |
|----------|-------------|-------|
| `minimal-insight` | 极简洞见 | 白底大字卡片 + 水墨插画 + 底栏标签 |

## Creating a New Template

1. Create `templates/<name>/` with:
   - `__init__.py` — subclass `BaseTemplate`, register with `REGISTRY["name"] = Class`
   - `scene.py` — Manim scene classes (read config via `_load_config()`)
   - `defaults.yaml` — default layout/colors/brand config

2. Register in `templates/__init__.py`

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
