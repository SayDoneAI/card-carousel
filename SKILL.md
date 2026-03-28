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

**用户只需提供一个 Markdown 文档**，包含视频文案。其余所有配置走黄金标准默认值。

示例输入（`认知升级.md`）：
```markdown
# 认知升级

真正阻碍一个人成长的从来不是能力不足。
而是认知顺序的严重错位。
他们把该敬畏的东西当成了敌人。
面对专业他们毫无敬畏总觉得差不多就行了。
```

用户也可以选择性提供：
- **主题句**（topic）— 强调色居中显示的金句，不提供则留空
- **播放倍速** — 默认 1.0x
- **配色方案** — 17 款可选（见下方配色方案章节）
- **品牌覆盖** — 如果不是默认作者"黄赋"，需要提供 logo_char/author/pinyin

## 黄金标准配置

所有新视频**必须**以 `content/golden_standard.yaml` 为起点（复制后修改）。该文件包含经 6+ 次视频迭代验证的最佳参数：

| 参数 | 黄金值 | 原因 |
|------|--------|------|
| voice.speed | **1.2** | 平衡流畅与理解度，不要用默认 1.0 |
| bgm.volume | **0.05** | 5% 不抢配音 |
| bgm.voice_volume | **1.5** | 配音放大 |
| bgm.fade_out | **3** | 结尾 3 秒淡出 |
| cover | **必须配置** | 封面是标配，包含 illustration_prompt + opening_sfx |
| 每句 ≤18 字 | **硬性要求** | 超出会自动拆分但容易导致排版问题 |

## Pipeline 质量护栏

pipeline 启动时自动执行旁白质量校验：

| 检查项 | 级别 | 说明 |
|--------|------|------|
| 关键词数 ≠ 句子数 | **阻断** | 必须一一对应，否则 pipeline 直接退出 |
| 句子超过 max_chars | 警告 | 会自动拆分但建议手动拆短 |
| 结尾非句号/问号/感叹号 | 警告 | 影响 TTS 停顿和静音检测 |
| 句内含逗号 | 警告 | 可能导致 TTS 停顿，破坏音画同步 |

## Execution Workflow

**CRITICAL: Follow every step in order. Do NOT skip any step.**

### Step 0: 发现可用模板并询问用户（必须）

收到用户文案后，**必须先发现模板、询问选择**，再进行任何后续步骤。

**1. 动态发现模板**（不要依赖 SKILL.md 中的硬编码列表）：

```bash
ls $PROJECT/templates/
```

对每个子目录（排除 `__pycache__`、`base.py`、`shared.py` 等非模板文件），读取：
- `templates/<name>/defaults.yaml` — 取 `name`、`description`、`canvas.pixel_width`、`canvas.pixel_height`、`illustrations` 字段
- `templates/<name>/scene.py` — 取 `SCENE_NAME` 常量值

**2. 向用户展示选项并询问**，格式示例：

> 请问你想用哪个模板生成视频？
>
> **模板1 — minimal-insight**（1080×1440）
> 极简洞见 — 白底大字卡片 + 水墨插画 + 底栏标签
>
> **模板2 — portrait-notebook**（1080×1920）
> 人像卡片 — 真人照片背景 + AI插画 + 字幕

若用户已在文案或指令中明确指定模板，则跳过此步骤。

### Step 1: 解析用户文案 → 生成 config.yaml

**以 `content/golden_standard.yaml` 为起点**，复制一份后修改以下内容：

从用户的 md 文档中提取：
1. **标题** — 取 `# 标题` 或文件名
2. **旁白文案** — 正文内容，每行一句
3. **主题句** — 用户指定的金句，或从文案中提炼一句
4. **封面** — cover.narration 填标题，illustration_prompt 描述封面画面
5. **插画关键词** — **由你（Claude）自动生成**，规则：
   - 为每句旁白分配一个关键词或 `null`
   - **关键词数量必须与句子数量完全一致**（pipeline 会校验，不匹配直接报错）
   - 关键词用**中文**，描述性短语（如 `"成长障碍"`, `"狮子咆哮"`）
   - 相邻句子内容相近时用 `null`（复用上一张插画，无切换动画）
   - 内容转折或场景变化时用新关键词（触发滑动动画）
   - 建议每 2-3 句换一张图，节奏感更好

生成的 config.yaml 放在 `$PROJECT/content/` 目录。

**旁白质量硬性要求**（违反会导致音画不同步，pipeline 会警告）：
- 每句 ≤18 字
- 句号/问号/感叹号结尾（不用逗号/冒号）
- 避免句内逗号

**voice.speed 必须为 1.2**（不是默认的 1.0）。

**config 中的关键字段必须从模板文件中动态读取，不能硬编码**：

| config 字段 | 来源 |
|------------|------|
| `template` | 用户选择的模板目录名 |
| `scenes[].name` | 从 `templates/<name>/scene.py` 读取的 `SCENE_NAME` |
| `illustrations.*` | 从 `templates/<name>/defaults.yaml` 读取的 `illustrations` 字段 |

config.yaml 结构模板：

```yaml
template: <模板名>
title: "<标题>"

cover:
  narration: "<标题>"
  illustration_prompt: "黑白铅笔素描，{封面画面描述}，白色背景，漫画分镜风格，线条简洁有张力，画面显眼位置有一个简短中文手写标注"
  opening_sfx: "assets/综艺咚咚特效音.mp3"

brand:
  topic: "<从文案中提炼的主题句>"

voice:
  provider: volcengine
  voice_type: zh_male_ruyayichen_uranus_bigtts
  cluster: volcano_tts
  speed: 1.2  # 必须 1.2，不要用默认 1.0

illustrations:
  enabled: true
  # 其余字段（engine, model, style_prompt, use_character, use_reference_image 等）
  # 从 templates/<name>/defaults.yaml 的 illustrations 节读取后填入
  # character_desc 如需覆盖 brand.yaml 的默认人物描述，可在此指定
  cache_dir: ".cache/illustrations"
  gen_tool: "tools/image_gen.py"

output:
  speed: 1.0

scenes:
  - name: <SCENE_NAME>   # 从 scene.py 读取，不同模板不同
    narration: |
      <旁白文案>
    illustration_keywords:
      - <关键词或 null>
```

**注意**：
- `scenes[].name` 必须与模板 `scene.py` 中的 `SCENE_NAME` 完全一致，否则 Manim 找不到场景类会报错
- `brand` 中只需写 `topic`，其余字段走模板默认值
- 如果文案很长（超过 15 句），拆成多个 Scene，命名规则参考模板的 `SCENE_NAME`（如 `Scene01_Cards`、`Scene02_Cards`）

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
[validate] → keywords → tts → illustrations → render → voice → cover → concat
```

| Step | What it does |
|------|-------------|
| `validate` | 自动校验旁白质量（关键词数量匹配、句长、标点、逗号），不匹配直接阻断 |
| `keywords` | 用 AI 自动为每个场景生成插画关键词（每3-5句一张图） |
| `tts` | 整场合成 TTS → 静音检测拆分时长 → 写 timing JSON |
| `illustrations` | 按关键词生成 AI 插画，缓存到 `.cache/`，复制到 `assets/` |
| `render` | Manim 渲染所有场景（注入环境变量供模板 scene.py 读取） |
| `voice` | 合并 TTS 音频到渲染好的视频 |
| `cover` | 封面制作（专用插画 + TTS + Manim 渲染 + 开场音效） |
| `concat` | 拼接封面 + 所有场景 → 混入 BGM → 最终输出 |

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
- **保存模板** — 点击「💾 保存模板」将当前配置写入 `.user/templates/<name>.yaml`，管线运行时自动使用

渲染机制：点击"渲染预览"按钮 → 调用 preview_server 的 Manim 单帧渲染 → 返回 PNG 预览图。

## User Template Overrides

编辑器中的配置默认只存在浏览器 localStorage 中，不影响视频生成管线。点击「💾 保存模板」后，配置会写入磁盘，管线自动使用。

**四层合并优先级**（从低到高）：
```
templates/<name>/defaults.yaml   ← Git 开发者默认值（只读）
brand.yaml                       ← 品牌资产层（作者信息，gitignored）
.user/templates/<name>.yaml      ← 用户自定义覆盖（编辑器保存，gitignored）
content/<config>.yaml            ← 内容配置（每次生成视频的具体参数，最高优先级）
```

- `.user/templates/` 目录已加入 `.gitignore`，不会提交到 git
- 用户不保存模板时，管线行为与之前完全一致（git defaults + content config）
- 保存后管线自动读取，无需额外配置

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
| 生图 | 纯文生图（character_desc 文字描述人物，不用参考图） |
| 画风 | 手绘笔记风格信息图，黑色线条+红色强调，图标/箭头/简笔画，白底 |

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

## Character Description (人物描述)

插画中的人物形象通过**纯文字描述**生成（不使用参考图 img2img），效果更好且风格更一致。

### 配置层级（优先级从高到低）

```
content/<config>.yaml → illustrations.character_desc    # 最高优先级
templates/<name>/defaults.yaml → illustrations.character_desc
brand.yaml → author.character_desc                      # 最低优先级
```

### 相关配置字段

| 字段 | 说明 |
|------|------|
| `illustrations.use_character` | `true` 时在生图 prompt 中注入人物描述 |
| `illustrations.character_desc` | 人物文字描述（覆盖 brand.yaml） |
| `illustrations.use_reference_image` | 仅显式 `true` 时允许 img2img 参考图（已废弃，推荐用 character_desc） |
| `illustrations.style_prompt` | 画风提示词，可用 `{character}` 占位符控制人物描述插入位置 |

### `{character}` 占位符

模板的 `style_prompt` 中可以用 `{character}` 控制人物描述的插入位置：
- 有占位符 → 替换为 character_desc
- 无占位符 → character_desc 前缀拼接到 style_prompt 前面

示例：
```yaml
# 模板 defaults.yaml
illustrations:
  use_character: true
  style_prompt: "手绘笔记风格信息图，白底黑线条。{character}"
```

### brand.yaml 品牌资产

`brand.yaml`（从 `brand.example.yaml` 复制）存放跨模板复用的作者信息：

```yaml
author:
  character_desc: "画面右下角有一个Q版卡通小人：光头圆脸的中国男性，戴黑框方形眼镜..."
  # reference_image / reference_strength 已废弃
```

`brand.yaml` 已加入 `.gitignore`，不会提交到 git。

## Illustration Keywords Guide

### 基本规则
- 每句旁白对应一个关键词或 `null`
- **关键词数量必须与句子数量完全一致**（pipeline 会校验，不匹配直接报错）
- `null` = 复用上一张插画（无切换动画）
- 非 null = 生成新插画 + 切换动画
- 节奏建议：每 3-4 句换一张图

### 插画风格：PPT 图解（不要概念图）

**核心原则**：每张图都是信息图/图表/流程图，像 PPT 讲解一样拆解逻辑，不要散装概念画。

| 类型 | 好的关键词示例 | 坏的关键词示例 |
|------|--------------|--------------|
| 对比 | `"two-column chart, left X 违规 right checkmark 合法"` | `"balance scale"` |
| 数据 | `"timeline 2003-2026 with large number 0 above"` | `"zero icon"` |
| 流程 | `"circular flow diagram: 越忙→判断差→返工→越忙"` | `"vicious cycle spiral"` |
| 分支 | `"company split diagram left 2.5% grey right 6.5% red"` | `"two paths"` |
| 总结 | `"three stacked blocks 政策 事实 逻辑 arrow to 合法合规"` | `"conclusion"` |

### 步骤类内容：底图渐进展开

步骤/流程类内容不要每步一张完全不同的图，而是**基于同一底图逐步展开**（像 PPT 动画）：

1. 先生成一张「总览图」（所有步骤灰色占位）
2. 后续每步用 img2img（`strength=0.4`）基于总览图生成变体，逐步点亮
3. 在 pipeline 外手动生成：`python3 tools/image_gen.py "prompt" --input base.jpg --strength 0.4`

### 封面插画

封面使用 `cover_fullscreen: true`，插画自带完整信息（标题+要点），模板不叠加红色标题：
- 信息图风格：大标题 + 2-3 个要点（带勾号/图标）+ 底部钩子文案
- 站在客户角度：封面要回答"跟我有关吗？值得看吗？"

### 缓存注意事项

更新插画后，如果视频中看到的还是旧图，需要清理以下缓存：
1. `media/<config>/illustrations/*_nobg.png` — 去背景缓存
2. `media/<config>/videos/*/partial_movie_files/` — Manim 分片缓存
3. `media/<config>/videos/cover/` — 封面渲染缓存
4. `assets/cover_*.jpg` — 封面插画缓存

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
  → core/config.py (load YAML + .env + brand.yaml + template merge + user override + path derivation)
  → core/orchestrator.py (5-step pipeline)
      → engines/tts/ (ABC + factory: volcengine)
      → engines/image/ (ABC + factory: gemini | doubao)
      → templates/ (registry + BaseTemplate ABC)
          → shared.py (unified Manim rendering engine for all templates)
          → minimal_insight/defaults.yaml
          → portrait_notebook/defaults.yaml

.user/templates/              (user overrides, gitignored)
  → <template-name>.yaml      (saved from preview editor)

tools/
  → preview_server.py (HTTP API: render, save template, upload image, port 8766)
  → template_preview.html (browser-based visual editor)
  → image_gen.py (AI image generation tool)
```
