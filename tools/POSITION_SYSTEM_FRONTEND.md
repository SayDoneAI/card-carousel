# 位置调整系统 - 前端实现完成

## 实现概述

已在 `tools/template_preview.html` 中完成位置调整系统的前端部分，与后端 API 完全集成。

## 实现的功能

### 1. 动态模板选择器
- 从 `/api/templates` 动态加载模板列表
- 自动填充模板下拉选择器
- 兼容 `{templates: [...]}` 和直接数组两种响应格式

### 2. 位置调整面板
- 从 `/api/template_manifest` 获取模板的 `positionable_elements`
- 为每个可定位元素生成独立的控件卡片
- 每个元素包含：
  - 元素标签（label）
  - X 轴滑块（min/max/step/default 从 manifest 读取）
  - Y 轴滑块（min/max/step/default 从 manifest 读取）
  - 单元素重置按钮
- 全部重置按钮恢复所有位置到默认值
- 如果模板没有 positionable_elements，面板自动隐藏

### 3. 位置数据流
- `currentPositions` 状态：`{element_id: {x: number, y: number}}`
- `currentManifestElements` 状态：存储当前模板的元数据
- 滑块拖拽实时更新数值显示（带 % 后缀）
- 滑块 input 事件触发 `renderPreview()`（与现有样式滑块行为一致）
- 只发送与默认值不同的位置数据（通过 `getModifiedPositions()` 优化）

### 4. API 集成
- `POST /api/render_frame` 请求体中包含 `params.positions`
- 格式：`{element_id: {x: number, y: number}}`
- 模板切换时自动清理旧的位置状态
- 重置功能清空 `currentPositions`

## 新增的 CSS 类

```css
.position-section          /* 位置区块容器 */
.position-element-card     /* 单个元素卡片 */
.position-element-title    /* 卡片标题行 */
.position-element-name     /* 元素名称 */
.position-reset-btn        /* 单元素重置按钮 */
.position-axis-label       /* X/Y 轴标签 */
.position-slider-field     /* 滑块字段容器 */
.position-reset-all-bar    /* 全部重置按钮容器 */
.position-reset-all-btn    /* 全部重置按钮 */
```

## 新增的 JS 函数

1. `populateTemplateSelector()` - 动态加载模板列表
2. `fetchTemplateManifest(template)` - 获取模板 manifest（带缓存）
3. `loadTemplateManifest(template)` - 加载并更新 currentManifestElements
4. `renderPositionSection()` - 渲染位置调整区块
5. `createPositionElementCard(el)` - 创建单个元素卡片
6. `createPositionAxisSlider(...)` - 创建 X/Y 轴滑块
7. `getModifiedPositions()` - 计算与默认值不同的位置

## 新增的状态变量

```javascript
let currentPositions = {};           // 用户修改的位置
let currentManifestElements = [];    // 当前模板的 positionable_elements
const templateManifestCache = {};    // manifest 缓存
```

## UI/UX 特性

- 位置面板放在"样式调整"之后
- 可折叠区块（与其他区块一致）
- 滑块实时更新数值显示
- 单元素重置 + 全部重置双重控制
- 模板切换时自动清理状态
- 空 manifest 时面板自动隐藏

## 代码统计

- 原始文件：1562 行
- 更新后：1872 行
- 新增代码：~310 行（包含 CSS + JS）

## 测试建议

1. 启动预览服务器：`python tools/preview_server.py`
2. 在浏览器打开：`http://localhost:8765/tools/template_preview.html`
3. 选择模板（如果模板有 positionable_elements）
4. 验证位置面板出现
5. 拖拽滑块，观察数值变化
6. 点击"渲染预览"，验证位置变化生效
7. 测试重置功能
8. 切换模板，验证状态清理

## 兼容性

- 纯 vanilla JS，无外部依赖
- 与现有代码风格一致
- 复用现有 slider 样式
- 不可变数据更新模式
- 向后兼容（无 positionable_elements 的模板正常工作）
