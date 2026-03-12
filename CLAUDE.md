# Card Carousel — 图文卡片口播视频生成管线

## 项目概述
可扩展模板系统的竖屏图文卡片口播视频生成器。通过 Manim 渲染 + AI 生图 + TTS 配音，一键生成成品视频。

## 技术栈
- **渲染引擎**: Manim Community v0.20+ (竖屏 1080x1440, 3:4)
- **TTS**: 火山引擎 TTS
- **AI 生图**: Gemini (主) / Doubao (备) — 通过 tools/image_gen.py
- **视频处理**: FFmpeg
- **配置格式**: YAML

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
- `GEMINI_API_KEY` — sucloud 中转 API Key（插画生成）
- `GEMINI_BASE_URL` — sucloud 基础 URL

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
- **Fallback**: 主引擎失败自动切换备用引擎（Gemini → Doubao）
- **路径兼容**: scene.py 回退到 `Path(__file__).parents[2]`，兼容直接 manim 调用
- **Media 隔离**: 模板模式用模板名作 media 目录名，避免多模板冲突

## 编码规范
- Python UTF-8，配置集中在 YAML，代码中不硬编码品牌/文案
- 插画按关键词缓存，`null` 关键词表示复用上一张图
- 引擎返回 Result 对象（不 sys.exit），orchestrator 统一处理错误
