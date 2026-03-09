# 模板预览系统使用说明

## 概述

模板预览系统已重构为 **Manim 真实渲染** 模式，去掉了 Fabric.js，所有预览都通过调用 Manim 生成真实帧。

## 架构

- **后端**: `tools/preview_server.py` — 轻量 HTTP 服务器（Python 标准库）
- **前端**: `tools/template_preview.html` — 纯 HTML/CSS/JS，无外部依赖
- **端口**: 8766

## 启动方式

```bash
cd /path/to/card-carousel
python tools/preview_server.py
```

服务器启动后，访问：http://localhost:8766/template_preview.html

## 功能特性

### 1. 模板选择
- 支持 `minimal-insight` 和 `portrait-notebook` 模板
- 切换模板自动加载对应的默认参数

### 2. 参数编辑
- **Layout**: 字体、尺寸、布局参数
- **Colors**: 背景色、文字色、强调色等（支持颜色选择器）
- **Brand**: Logo、作者、主题、拼音、免责声明
- **Footer**: 底栏标签（可添加/删除）

### 3. 一键配色
- 10 套预设配色方案
- 点击即可应用到当前模板

### 4. 渲染预览
- 点击「渲染预览」按钮 → 调用 Manim 渲染单帧（约 5-10 秒）
- 显示真实的 Manim 渲染结果（PNG 图片）
- 参数修改后按钮会高亮提示

### 5. 已有视频帧
- 点击「已有视频帧」→ 从已渲染的视频中抽取第一帧
- 快速预览已有渲染效果

### 6. 重置为默认
- 清除 localStorage 缓存
- 恢复模板默认参数

### 7. 自动保存
- 所有参数修改自动保存到 localStorage
- 下次打开自动恢复上次的参数

## API 接口

### POST /api/render_frame
调用 Manim 渲染单帧，返回 PNG 二进制数据。

**请求体**:
```json
{
  "template": "minimal-insight",
  "params": {
    "colors": {
      "bg": "#FFFFFF",
      "text": "#000000",
      "accent": "#C0392B"
    },
    "brand": {
      "logo_char": "赋",
      "author": "@黄赋",
      "topic": "测试预览",
      "pinyin": "HUANG FU"
    }
  }
}
```

**响应**: PNG 图片（Content-Type: image/png）

### GET /api/video_frame?template=xxx
从已有渲染视频中抽取第一帧。

**参数**:
- `template`: 模板名称（如 `minimal-insight`）

**响应**: PNG 图片（Content-Type: image/png）

## 技术细节

### 后端渲染流程
1. 接收前端参数
2. 生成临时 YAML 配置文件
3. 调用 `load_config()` 合并模板默认配置
4. 设置环境变量（`CARD_CAROUSEL_PROJECT_DIR`, `CARD_CAROUSEL_CONFIG_PATH`）
5. 执行 `manim render -s -ql --format png` 渲染单帧
6. 查找输出的 PNG 文件
7. 返回 PNG 二进制数据
8. 清理临时文件

### 前端交互流程
1. 用户修改参数 → 自动保存到 localStorage
2. 点击「渲染预览」→ 收集参数 → POST /api/render_frame
3. 显示 spinner（渲染中...）
4. 收到响应 → 显示 PNG 图片
5. 更新状态栏（成功/失败/耗时）

### 并发控制
- 后端使用 `threading.Lock` 保证同一时刻只有一个渲染任务
- 多个请求会排队等待

### 错误处理
- Manim 渲染失败 → 返回错误信息
- 后端连接失败 → 前端显示提示
- 超时保护（35 秒）

## 与旧版本的区别

| 特性 | 旧版本（Fabric.js） | 新版本（Manim 真实渲染） |
|------|-------------------|----------------------|
| 渲染引擎 | Fabric.js Canvas | Manim |
| 预览速度 | 即时 | 5-10 秒 |
| 预览精度 | 近似 | 100% 真实 |
| 外部依赖 | Fabric.js CDN | 无 |
| 代码量 | 1817 行 | 879 行 |

## 故障排查

### 问题：渲染失败
- 检查 Manim 是否正确安装：`python -m manim --version`
- 检查模板 scene.py 是否存在
- 查看后端日志：`tail -f /tmp/server.log`

### 问题：端口被占用
```bash
# 查找占用端口的进程
lsof -ti:8766

# 停止进程
kill $(lsof -ti:8766)
```

### 问题：前端无法连接后端
- 确认后端已启动：`curl http://localhost:8766/`
- 检查浏览器控制台是否有 CORS 错误

## 开发建议

### 添加新模板
1. 在 `templates/` 下创建新模板目录
2. 在 `preview_server.py` 的 `template_to_script` 字典中添加映射
3. 在前端 HTML 的 `<select>` 中添加选项
4. 在 `TEMPLATE_DEFAULTS` 中添加默认参数

### 调整渲染质量
修改 `preview_server.py` 中的 `--quality` 参数：
- `l`: low (快速，低质量)
- `m`: medium
- `h`: high (慢速，高质量)

### 调整超时时间
修改前端 `fetch()` 调用中的超时时间（默认 35 秒）。

## 性能优化建议

1. **缓存渲染结果**: 可以根据参数 hash 缓存 PNG，避免重复渲染
2. **异步队列**: 使用 Celery 等任务队列处理渲染请求
3. **WebSocket**: 实时推送渲染进度
4. **预渲染**: 预先渲染常用配色方案

## 许可证

与主项目相同。
