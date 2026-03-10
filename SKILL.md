---
name: card-carousel
description: "Generate vertical card-style narration videos with Manim rendering, AI illustrations, and TTS voiceover. Use when the user wants to create 竖屏卡片口播视频, card carousel videos, or narration videos with text cards and illustrations."
---

# Card Carousel — 图文卡片口播视频生成器

Generate vertical card-style narration videos: Manim rendering + AI illustrations + TTS voiceover → final video.

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
- **模板选择** — `minimal-insight`（1080x1440）或 `portrait-notebook`（1080x1920）
- **主题句**（topic）— 强调色居中显示的金句，不提供则留空
- **播放倍速** — 默认 1.0x
- **配色方案** — 17 款可选（见下方配色方案章节）
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

输出视频保存在**用户启动 Claude Code 的当前目录**（不是 skill 项目目录）。

```bash
ffprobe -v quiet -show_format -show_streams <title>_*.mp4 2>/dev/null | grep -E 'width|height|duration|size'
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

## Available Templates

| Template | Resolution | Description |
|----------|-----------|-------------|
| `minimal-insight` | 1080x1440 (3:4) | 极简洞见 — 白底大字卡片 + 水墨插画 + 底栏标签 |
| `portrait-notebook` | 1080x1920 (9:16) | 人像卡片 — 真人照片背景 + AI插画 + 字幕 |

两个模板共享相同的 17 款配色方案和标准元素集（logo、作者名、头像、主标题、副标题、拼音、插画、字幕、免责声明、底栏），仅 `visible` 默认值和布局位置不同。

## Color Palettes (17 款)

所有配色方案均通过 WCAG AA 对比度审查。

### 浅色系（7 款）
| 名称 | 风格 | 背景色 | 强调色 |
|------|------|--------|--------|
| 经典黑白 | 经典极简 | #FFFFFF | #C0392B |
| 清新薄荷 | 清透绿色 | #F0FDF4 | #059669 |
| 柔雾薰衣草 | 紫色柔和 | #FAF5FF | #7C3AED |
| 暖桃微光 | 温暖粉色 | #FFF5F5 | #D94F3E |
| 晴空蔚蓝 | 知识清透风 | #F0F7FF | #2563EB |
| 奶油暖阳 | ins 暖调 | #FFF8F0 | #C87941 |
| 水墨丹青 | 极简国风 | #F5F2ED | #6B7F5E |

### 暖色氛围系（3 款）
| 名称 | 风格 | 背景色 | 强调色 |
|------|------|--------|--------|
| 冬日暖阳 | 暖棕色调 | #3D2B1F | #E8B86D |
| 日落琥珀 | 琥珀橙调 | #2D1810 | #FF8C42 |
| 焦糖拿铁 | 咖啡色调 | #2C1E14 | #C89B7B |

### 暗色高级系（7 款）
| 名称 | 风格 | 背景色 | 强调色 |
|------|------|--------|--------|
| 莫兰迪灰粉 | 低饱和高级感 | #F2EDEB | #7A5C52 |
| 极夜蓝紫 | 深紫神秘 | #0F0F1A | #A78BFA |
| 深邃星空 | 深蓝科技 | #0A192F | #64FFDA |
| 故宫朱砂 | 新中式国风 | #1A0A0E | #C4473A |
| 午夜墨绿 | 暗绿自然 | #000000 | #4ADE80 |
| 暖金黑 | 金色奢华 | #121212 | #FFD700 |
| 深酒红 | 酒红浪漫 | #18000A | #FF2E63 |

每个配色方案包含 8 个颜色字段（bg, text, accent, subtitle, pinyin, muted, bar_bg, bar_text）和配套渐变背景。用户可在预览编辑器中切换配色方案，也可自由编辑单个颜色或渐变停止点。

## Preview Editor

模板预览编辑器可实时调整所有视觉参数：

```bash
cd $PROJECT
python tools/preview_server.py  # 启动预览服务器（端口 8766）
open tools/template_preview.html  # 打开编辑器
```

编辑器功能：
- **模板切换** — 在两个模板之间切换
- **配色方案** — 一键应用 17 款配色，支持纯色/渐变背景切换
- **渐变编辑** — 可编辑渐变停止点（位置、颜色）
- **元素控制** — 每个元素可独立开关、调整位置（x/y 百分比）
- **字体大小** — 每个文字元素可独立调整字号
- **插画设置** — 大小、比例、切换动画
- **品牌定制** — Logo 文字、作者名、拼音、免责声明、底栏标签
- **参数持久化** — 修改自动保存到 localStorage，重载时恢复

渲染机制：点击"渲染预览"按钮 → 调用 preview_server 的 Manim 单帧渲染 → 返回 PNG 预览图。

## Template Defaults

### minimal-insight
| 配置项 | 默认值 |
|--------|--------|
| 分辨率 | 1080x1440 (3:4) |
| 配色 | 经典黑白（白底红色强调） |
| Logo | 赋 |
| 作者 | @黄赋 |
| 拼音 | HUANG FU |
| 语音 | 火山引擎 `zh_male_ruyayichen_uranus_bigtts` |
| 生图 | Gemini 主 / Doubao 备 |
| 画风 | 极简线描，黑墨+红色点缀，白底 |

### portrait-notebook
| 配置项 | 默认值 |
|--------|--------|
| 分辨率 | 1080x1920 (9:16) |
| 配色 | 暖金黑（黑底金色强调） |
| 主标题 | AI生存指南 ①（企业篇） |
| 副标题 | 企业人工智能转型三个目标 |
| 语音 | 同上 |
| 生图 | 同上 |

## Positionable Elements

两个模板共享相同的标准元素集（ID 和类型一致，仅 visible/位置不同）：

| Element ID | Type | Description |
|-----------|------|-------------|
| `gradient_overlay` | gradient_overlay | 毛玻璃蒙版 |
| `portrait` | image | 背景图片 |
| `logo` | logo | Logo 圆圈 |
| `author_name` | text | 作者名 |
| `author_avatar` | image | 作者头像 |
| `topic` | text | 主标题（HEAVY 粗体） |
| `subtitle` | text | 副标题（HEAVY 粗体） |
| `pinyin_text` | text | 拼音 |
| `illustration` | illustration | AI 插画 |
| `caption` | caption | 字幕（纯黑/白色，基于背景亮度） |
| `disclaimer` | text | 免责声明 |
| `footer_bar` | bar | 底栏背景 + 标签 |

## Illustration Keywords Guide

- 每句旁白对应一个关键词或 `null`
- `null` = 复用上一张插画（无切换动画）
- 非 null = 生成新插画 + 左右滑动切换动画
- 关键词用**英文**，描述性短语
- 好的关键词：`"mountain path"`, `"thin ice walking"`, `"lion roaring"`
- 差的关键词：`"认知"`, `"a person thinking about something"` (太抽象或太长)
- 节奏建议：每 2-3 句换一张图

## Creating a New Template

1. Create `templates/<name>/` with:
   - `__init__.py` — subclass `BaseTemplate`, register with `REGISTRY["name"] = Class`
   - `scene.py` — Manim scene classes (read config via `_load_config()`)
   - `defaults.yaml` — default layout/colors/brand config

2. Register in `templates/__init__.py`

3. Template `defaults.yaml` must include:
   - `canvas` — pixel_width, pixel_height
   - `layout` — font, colors (all 8 fields), background (gradient config)
   - `brand_defaults` — brand text values
   - `color_palettes` — 17 款标准配色（与其他模板保持同步）
   - `positionable_elements` — 标准元素集（ID 与其他模板一致）

4. Template scene.py must:
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
| Preview server port busy | Server uses `allow_reuse_address`; if still busy, kill existing process on port 8766 |
| Colors not applying | Clear localStorage for the template, reload preview editor |

## Architecture

```
pipeline.py (CLI entry)
  → core/config.py (load YAML + .env + template merge + path derivation)
  → core/orchestrator.py (5-step pipeline)
      → engines/tts/ (ABC + factory: volcengine)
      → engines/image/ (ABC + factory: gemini | doubao)
      → templates/ (registry + BaseTemplate ABC)
          → shared.py (unified Manim rendering engine for all templates)
          → minimal_insight/defaults.yaml
          → portrait_notebook/defaults.yaml

tools/
  → preview_server.py (Flask API: single-frame Manim rendering, port 8766)
  → template_preview.html (browser-based visual editor)
  → image_gen.py (AI image generation tool)
```
