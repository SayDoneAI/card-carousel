# Card Carousel — 图文卡片口播视频生成管线

## 项目概述
可扩展模板系统的竖屏图文卡片口播视频生成器。通过 Manim 渲染 + AI 生图 + TTS 配音，一键生成成品视频。

## 技术栈
- **渲染引擎**: Manim Community v0.20+ (竖屏 1080x1440, 3:4)
- **TTS**: 火山引擎 TTS
- **AI 生图**: Gemini (主) / Kling (备) / Doubao (备) — 通过 tools/image_gen.py
- **视频处理**: FFmpeg
- **配置格式**: YAML

## 引擎价格
- gemini-3.1-flash-image-preview: ¥0.099/张
- kling-v3: ¥0.168/张
- doubao-seedream-5.0: ¥0.220/张

## 项目结构
```
card-carousel/
├── pipeline.py              # CLI 入口（argparse → load_config → run_pipeline）
├── config.yaml              # 旧模式配置（无 template 字段）
├── brand.example.yaml       # 品牌资产配置示例
├── brand.yaml               # 本地品牌资产（gitignored）
├── explainer.py             # 向后兼容 shim → templates/minimal_insight/scene.py
├── core/
│   ├── config.py            # 配置加载 + .env + 模板合并 + 路径派生
│   ├── orchestrator.py      # 管线编排（5 步: tts → illustrations → render → voice → concat）
│   └── utils.py             # 工具函数（get_duration, sanitize_filename）
├── engines/
│   ├── tts/                 # TTS 引擎 ABC + 工厂
│   │   ├── __init__.py      # TTSEngine ABC, TTSResult, get_tts_engine()
│   │   └── volcengine.py    # 火山引擎 TTS
│   └── image/               # 图片引擎 ABC + 工厂
│       ├── __init__.py      # ImageEngine ABC, ImageResult, get_image_engine()
│       └── tool_adapter.py  # 外部工具适配器（包装 tools/image_gen.py）
├── templates/
│   ├── __init__.py          # 模板 Registry + @register 装饰器
│   ├── base.py              # BaseTemplate ABC
│   ├── shared.py            # 统一渲染引擎（GenericCardScene）
│   ├── minimal_insight/     # "极简洞见" 模板
│   │   ├── __init__.py      # MinimalInsightTemplate 注册
│   │   ├── scene.py         # Manim 场景渲染（参数化颜色/字体/布局）
│   │   └── defaults.yaml    # 模板默认配置
│   └── portrait_notebook/   # "人物笔记" 模板
│       ├── __init__.py      # PortraitNotebookTemplate 注册
│       ├── scene.py         # Manim 场景渲染（参数化颜色/字体/布局）
│       └── defaults.yaml    # 模板默认配置
├── content/
│   ├── example.yaml         # 新模式配置示例（带 template 字段）
│   ├── template_standard.yaml # sketch-card 标准配置（最佳实践）
│   └── portrait_example.yaml  # 人物模板示例配置
├── assets/
│   ├── illustrations/       # Manim 引用的插画文件（从 cache 复制）
│   └── huangfu.png          # 示例素材
├── docs/
│   └── POSITION_SYSTEM_SPEC.md # 位置系统规范
└── tools/
    ├── image_gen.py         # AI 图片生成工具
    ├── preview_server.py    # 预览服务器
    └── template_preview.html # 前端预览编辑器
```

## 两种配置模式

### 旧模式（无 template 字段）
```yaml
title: "标题"
manim_script: "explainer.py"
scenes: [...]
```

### 模板模式（有 template 字段）
```yaml
template: minimal-insight
title: "标题"
scenes: [...]
```
模板的 `defaults.yaml` 自动合并，用户配置优先级更高。

## 快速使用
```bash
python pipeline.py config.yaml              # 全量执行
python pipeline.py config.yaml --step tts   # 只跑 TTS
python pipeline.py config.yaml --step illustrations  # 只生成插画
python pipeline.py config.yaml --step render # 只渲染 Manim
python pipeline.py config.yaml --step voice  # 合并音频到视频
python pipeline.py config.yaml --step concat # 拼接最终视频
python pipeline.py config.yaml --speed 1.5  # 1.5 倍速
```

## 环境变量 (.env)
- `VOLC_API_KEY` — 火山引擎 TTS API Key
- `GEMINI_API_KEY` — sucloud 中转 API Key（插画生成，Gemini / Kling / Doubao 共用）
- `GEMINI_BASE_URL` — sucloud 基础 URL（Gemini / Kling / Doubao 共用）

## 环境变量（运行时注入，由 orchestrator 设置）
- `CARD_CAROUSEL_PROJECT_DIR` — 项目根目录
- `CARD_CAROUSEL_CONFIG_PATH` — 配置文件路径
- `CARD_CAROUSEL_AUDIO_DIR` — 音频目录
- `CARD_CAROUSEL_TIMING_FILE` — 时间线文件路径

## 目录约定
- `media/` — Manim 输出、音频、配音视频（gitignored）
- `.cache/` — 插画缓存（gitignored）
- `assets/illustrations/` — Manim 引用的插画文件（从 cache 复制）

## 架构要点
- **引擎模式**: ABC + dataclass Result + 工厂函数（白名单校验）
- **模板系统**: BaseTemplate ABC + Registry 字典 + @register 装饰器
- **配置合并**: deep merge（template.defaults < 用户 config）
- **Fallback**: 主引擎失败自动切换备用引擎（支持链式：Gemini → Kling → Doubao；顺序由配置决定）
- **路径兼容**: scene.py 回退到 `Path(__file__).parents[2]`，兼容直接 manim 调用
- **Media 隔离**: 模板模式用模板名作 media 目录名，避免多模板冲突

## 编码规范
- Python UTF-8，配置集中在 YAML，代码中不硬编码品牌/文案
- 插画按关键词缓存，`null` 关键词表示复用上一张图
- 引擎返回 Result 对象（不 sys.exit），orchestrator 统一处理错误

## 最佳实践（经过多次迭代验证）

### 黄金标准配置

**所有新视频必须以 `content/golden_standard.yaml` 为起点**。该文件包含经 6+ 次视频迭代验证的全部最佳参数（dark-card 模板）。复制后只需修改 title、brand.topic、scenes 三处。

另有 `content/template_standard.yaml` 对应 sketch-card 模板。

### Pipeline 质量护栏

`run_pipeline()` 启动时自动执行 `_validate_narration()` 校验：
- **阻断**：关键词数量与句子数量不匹配（直接 exit）
- **警告**：句子超长（>max_chars）、结尾标点不规范、句内含逗号

### 语速与 BGM
- **TTS 语速**: 1.2x（`voice.speed: 1.2`）— 平衡流畅度与理解度
- **BGM 音量**: 5%（`bgm.volume: 0.05`）— 不抢配音，营造氛围
- **BGM 淡出**: 3秒（`bgm.fade_out: 3`）

### 旁白规则（确保字幕音频同步）
1. **每句 ≤18 字** — 确保单行显示，避免换行
2. **用句号、问号、感叹号结尾** — 不用冒号、逗号结尾
3. **避免句内逗号** — 逗号会导致 TTS 停顿，影响静音检测时长切分
4. **1 句 = 1 卡片 = 1 TTS 片段** — 保证字幕音频严格同步

### 插画关键词规则
1. 每句旁白对应一个关键词或 `null`
2. `null` = 复用上一张插画（无切换动画）
3. 非 `null` = 生成新插画 + 切换动画
4. 建议每 3-4 句换一张图
5. 内容转折或场景变化时用新关键词

### 插画风格（PPT 图解，不要概念图）
- 每张图都是**信息图/图表/流程图**，像 PPT 讲解一样拆解逻辑
- 用对比表、时间线、柱状图、分支图等具体图表类型
- 数据说话：突出具体数字和对比
- **步骤类内容用同一底图逐步展开**（img2img, strength=0.4），不要每步一张完全不同的图
- 坏例子：`"missing puzzle piece"`（抽象概念图）
- 好例子：`"two-column chart, left X 违规 right checkmark 合法"`（具体图表）

### 封面设计
- 使用 `cover_fullscreen: true`，插画自带完整信息，模板不叠加标题
- 站在客户角度设计：回答"跟我有关吗？值得看吗？"
- 铁证清单型（勾号+要点）、数据冲击型（对比数字）等效果较好

### 缓存清理
更新插画后如果视频仍显示旧图，需清理：
- `media/<config>/illustrations/*_nobg.png`（去背景缓存）
- `media/<config>/videos/*/partial_movie_files/`（Manim 分片缓存）
- `media/<config>/videos/cover/`（封面渲染缓存）
- `assets/cover_*.jpg`（封面插画缓存）

### 插画生成注意事项
- **纯中文要求**: style_prompt 已强制 "no English text, no Latin letters"
- **缓存机制**: 插画按关键词缓存在 `.cache/illustrations/`，复制到 `assets/illustrations/` 供 Manim 使用
- **重新生成**: 若需重新生成，必须同时删除 `.cache/` 和 `assets/` 中的文件，并清除 `media/videos/scene/1080p60/partial_movie_files/`（Manim 分片缓存）

### 字幕同步算法
- **策略**: 按字数比例计算每个句子边界的期望时间点，然后为每个边界找最近的静音区间（搜索窗口±70%平均句长）
- **避免**: 旧算法取全局最长静音会被 TTS 戏剧性停顿误导，导致时长严重偏移
- **实现**: `core/orchestrator.py::_split_by_silences()`

### 品牌签名
- **作者**: "创业向导，少走弯路，多做正事"
- **tagline**: "成长分享，伴你前行"（封面及卡片底部显示）

### 标准配置模板
参考 `content/template_standard.yaml`，包含所有经过验证的最佳参数。
