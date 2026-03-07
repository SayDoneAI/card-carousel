# Card Carousel — 图文卡片口播视频生成管线

## 项目概述
还原 @深度进化Theo 风格的竖屏图文卡片口播视频。通过 Manim 渲染 + AI 生图 + TTS 配音，一键生成成品视频。

## 技术栈
- **渲染引擎**: Manim Community v0.20+ (竖屏 1080x1440, 3:4)
- **TTS**: 火山引擎 TTS (主) / Edge TTS (备)
- **AI 生图**: doubao-seedream-5-0 (通过 tools/image_gen.py)
- **视频处理**: FFmpeg
- **配置格式**: YAML

## 核心文件
| 文件 | 职责 |
|------|------|
| pipeline.py | 管线编排（tts → illustrations → render → voice → concat） |
| explainer.py | Manim 场景渲染脚本（竖屏卡片布局） |
| config.yaml | 视频配置（品牌、场景、旁白、插画关键词） |
| tools/image_gen.py | AI 图片生成工具（外部依赖） |

## 快速使用
python pipeline.py config.yaml              # 全量执行
python pipeline.py config.yaml --step tts   # 只跑 TTS
python pipeline.py config.yaml --step render # 只渲染

## 环境变量 (.env)
- VOLC_API_KEY — 火山引擎 TTS API Key
- GEMINI_API_KEY — sucloud 中转 API Key（插画生成）
- GEMINI_BASE_URL — sucloud 基础 URL

## 目录结构约定
- media/ — Manim 输出、音频、配音视频（gitignored）
- .cache/ — 插画缓存（gitignored）
- assets/illustrations/ — Manim 引用的插画文件（从 cache 复制）

## 编码规范
- Python 文件使用 UTF-8 编码
- 配置通过 config.yaml 集中管理，代码中不硬编码品牌/文案信息
- 插画按关键词缓存，null 关键词表示复用上一张图
