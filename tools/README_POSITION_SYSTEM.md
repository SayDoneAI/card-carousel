# 通用元素位置调整机制设计方案

## 1. 问题分析

### 当前痛点
- **硬编码坐标**：所有元素位置在 scene.py 中硬编码（如 `UP * 3.7`, `RIGHT * 3.3 + DOWN * 4.0`）
- **模板扩展困难**：新增模板时，前端需要手动添加位置编辑控件
- **坐标系不友好**：Manim 使用中心原点 + Y 轴向上，用户难以理解
- **缺乏可视化调整**：只能通过修改代码 → 渲染 → 查看的循环调整位置

### 核心需求
1. 任何模板的元素位置都能通过前端编辑器调整
2. 新增模板时前端自动适配（零前端代码改动）
3. 用户友好的坐标系统（百分比或像素，从左上角）
4. 实时预览调整效果

---

## 2. 架构设计

### 2.1 职责划分

| 组件 | 职责 |
|------|------|
| **defaults.yaml** | 声明可定位元素的元数据（ID、标签、默认位置、约束） |
| **BaseTemplate** | 提供 `get_positionable_elements()` 接口 |
| **scene.py** | 从配置读取位置 → 转换为 Manim 坐标 → 应用到元素 |
| **core/utils.py** | 坐标转换工具（百分比 ↔ Manim） |
| **preview_server.py** | 校验位置参数，传递给 Manim |
| **template_preview.html** | 动态生成位置编辑控件，发送调整后的位置 |

### 2.2 坐标系统设计

#### 用户坐标系（百分比，左上角原点）
```
(0%, 0%)  ────────────────→ X (100%, 0%)
   │
   │  画面中心: (50%, 50%)
   │
   ↓ Y
(0%, 100%)                  (100%, 100%)
```

**优势**：
- ✅ 符合 CSS/设计工具习惯
- ✅ 分辨率无关，可移植
- ✅ 直观（0% = 顶部/左侧，100% = 底部/右侧）

#### Manim 坐标系（中心原点，Y 轴向上）
```
        Y ↑
          │
          │ (0, frame_height/2)
          │
─────────┼─────────→ X
          │ (0, 0) 中心
          │
          │ (0, -frame_height/2)
```

#### 转换公式
```python
# 百分比 → Manim
manim_x = (x_percent / 100 - 0.5) * frame_width
manim_y = (0.5 - y_percent / 100) * frame_height

# Manim → 百分比
x_percent = (manim_x / frame_width + 0.5) * 100
y_percent = (0.5 - manim_y / frame_height) * 100
```

---

## 3. 数据结构设计

### 3.1 元素元数据（defaults.yaml）

```yaml
# templates/minimal_insight/defaults.yaml
positionable_elements:
  - id: "logo_header"
    label: "Logo 和作者名"
    type: "group"
    default_position:
      x: 10  # 百分比，距左边 10%
      y: 5   # 百分比，距顶部 5%
    constraints:
      x: {min: 0, max: 100}
      y: {min: 0, max: 20}

  - id: "topic_line"
    label: "主题句"
    type: "text"
    default_position: {x: 50, y: 12}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 5, max: 30}

  - id: "main_text"
    label: "主文字"
    type: "text"
    default_position: {x: 50, y: 35}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 20, max: 60}

  - id: "illustration"
    label: "插画"
    type: "image"
    default_position: {x: 50, y: 60}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 40, max: 85}

  - id: "disclaimer"
    label: "免责声明"
    type: "text"
    default_position: {x: 85, y: 80}
    constraints:
      x: {min: 50, max: 100}
      y: {min: 70, max: 95}
```

**字段说明**：
- `id`: 元素唯一标识符（scene.py 中引用）
- `label`: 前端显示的中文名称
- `type`: 元素类型（text/image/group），用于前端图标/分组
- `default_position`: 默认位置（百分比）
- `constraints`: 位置约束（防止元素移出画面或重叠）

### 3.2 用户配置（config.yaml）

```yaml
template: minimal-insight
layout:
  positions:
    logo_header: {x: 10, y: 5}    # 使用默认值
    topic_line: {x: 50, y: 15}    # 用户调整：从 12% 移到 15%
    main_text: {x: 50, y: 35}
    illustration: {x: 50, y: 62}  # 用户调整：从 60% 移到 62%
    disclaimer: {x: 85, y: 80}
```

**合并逻辑**：
1. 模板 defaults.yaml 提供默认位置
2. 用户 config.yaml 覆盖特定元素
3. scene.py 优先读取用户配置，回退到默认值

---

## 4. 实现方案

### 4.1 BaseTemplate 扩展

```python
# templates/base.py
from abc import ABC, abstractmethod

class BaseTemplate(ABC):
    name: str

    @abstractmethod
    def get_default_config(self) -> dict:
        """返回模板默认配置（品牌/布局/颜色等）"""
        ...

    @abstractmethod
    def get_manim_script(self) -> str:
        """返回此模板的 Manim 脚本相对路径"""
        ...

    @abstractmethod
    def get_scene_classes(self) -> list[str]:
        """返回 Manim 场景类名列表"""
        ...

    def get_positionable_elements(self) -> list[dict]:
        """返回可定位元素列表（从 defaults.yaml 读取）

        返回格式:
        [
            {
                "id": "logo_header",
                "label": "Logo 和作者名",
                "type": "group",
                "default_position": {"x": 10, "y": 5},
                "constraints": {"x": {"min": 0, "max": 100}, "y": {"min": 0, "max": 20}}
            },
            ...
        ]
        """
        defaults = self.get_default_config()
        return defaults.get("positionable_elements", [])
```

### 4.2 坐标转换工具

```python
# core/utils.py
def percent_to_manim(
    x_percent: float,
    y_percent: float,
    frame_width: float,
    frame_height: float
) -> tuple[float, float]:
    """将百分比坐标（左上角原点）转换为 Manim 坐标（中心原点）

    Args:
        x_percent: X 坐标百分比 (0-100)，0 = 左边缘，100 = 右边缘
        y_percent: Y 坐标百分比 (0-100)，0 = 顶部，100 = 底部
        frame_width: Manim frame_width
        frame_height: Manim frame_height

    Returns:
        (manim_x, manim_y): Manim 坐标系中的位置
    """
    manim_x = (x_percent / 100.0 - 0.5) * frame_width
    manim_y = (0.5 - y_percent / 100.0) * frame_height
    return manim_x, manim_y


def manim_to_percent(
    manim_x: float,
    manim_y: float,
    frame_width: float,
    frame_height: float
) -> tuple[float, float]:
    """将 Manim 坐标转换为百分比坐标（用于导出现有位置）"""
    x_percent = (manim_x / frame_width + 0.5) * 100.0
    y_percent = (0.5 - manim_y / frame_height) * 100.0
    return x_percent, y_percent
```

### 4.3 Scene.py 集成

```python
# templates/minimal_insight/scene.py (示例改造)

def _get_element_position(cfg, element_id, default_x_percent, default_y_percent):
    """从配置读取元素位置，回退到默认值"""
    positions = cfg.get("layout", {}).get("positions", {})
    pos = positions.get(element_id, {})

    x_percent = pos.get("x", default_x_percent)
    y_percent = pos.get("y", default_y_percent)

    from core.utils import percent_to_manim
    manim_x, manim_y = percent_to_manim(
        x_percent, y_percent,
        config.frame_width,
        config.frame_height
    )
    return manim_x, manim_y


def _build_logo_header(cfg, colors, font):
    """构建头部: 左上角圆圈logo + 居中作者名"""
    brand_cfg = cfg.get("brand", {})
    logo_char = brand_cfg.get("logo_char", "深")
    author = brand_cfg.get("author", "@黄赋")

    # 读取位置配置（默认：x=10%, y=5%）
    x, y = _get_element_position(cfg, "logo_header", 10, 5)

    circle = Circle(radius=0.30, color=colors["text"], stroke_width=2.5)
    logo_text = Text(logo_char, font=font, font_size=22, color=colors["text"], weight=BOLD)
    logo = VGroup(circle, logo_text)
    logo.move_to([x, y, 0])

    # 作者名保持与 logo 同一行（或根据需要独立定位）
    author_text = Text(author, font=font, font_size=20, color=colors["text"])
    author_text.move_to([0, y, 0])  # 水平居中，Y 与 logo 对齐

    return VGroup(logo, author_text)


def _build_topic_line(cfg, colors, font):
    """构建红色主题句"""
    brand_cfg = cfg.get("brand", {})
    topic = brand_cfg.get("topic", "")
    if not topic:
        return VGroup()

    # 读取位置配置（默认：x=50%, y=12%）
    x, y = _get_element_position(cfg, "topic_line", 50, 12)

    topic_text = Text(topic, font=font, font_size=24, color=colors["accent"])
    topic_text.move_to([x, y, 0])
    return topic_text
```

**改造要点**：
1. 所有固定元素调用 `_get_element_position()` 获取位置
2. 动态元素（如主文字、插画）在循环中也使用相同机制
3. 保持向后兼容：未配置位置时使用硬编码默认值

---

## 5. 前端自动适配

### 5.1 API 扩展

```python
# preview_server.py
def _handle_template_defaults(self, query_string: str):
    """返回模板默认配置 + 可定位元素元数据"""
    qs = urllib.parse.parse_qs(query_string)
    template = qs.get("template", ["minimal-insight"])[0]
    try:
        from templates import get_template
        tmpl = get_template(template)
        defaults = tmpl.get_default_config()
        positionable = tmpl.get_positionable_elements()

        self._send_json(200, {
            "template": template,
            "defaults": defaults,
            "positionable_elements": positionable
        })
    except Exception:
        log.exception("template_defaults 失败")
        self._send_error_json(500, "加载模板元数据失败")
```

### 5.2 前端动态生成控件

```javascript
// template_preview.html (伪代码)
async function loadTemplateMetadata(templateName) {
  const resp = await fetch(`/api/template_defaults?template=${templateName}`);
  const data = await resp.json();

  const positionable = data.positionable_elements || [];
  const positionPanel = document.getElementById('position-controls');
  positionPanel.innerHTML = '';

  positionable.forEach(element => {
    const section = document.createElement('div');
    section.className = 'position-control-group';
    section.innerHTML = `
      <h4>${element.label}</h4>
      <label>
        X (${element.constraints.x.min}% - ${element.constraints.x.max}%)
        <input type="range"
               data-element="${element.id}"
               data-axis="x"
               min="${element.constraints.x.min}"
               max="${element.constraints.x.max}"
               value="${element.default_position.x}"
               step="0.5">
        <span class="value">${element.default_position.x}%</span>
      </label>
      <label>
        Y (${element.constraints.y.min}% - ${element.constraints.y.max}%)
        <input type="range"
               data-element="${element.id}"
               data-axis="y"
               min="${element.constraints.y.min}"
               max="${element.constraints.y.max}"
               value="${element.default_position.y}"
               step="0.5">
        <span class="value">${element.default_position.y}%</span>
      </label>
    `;
    positionPanel.appendChild(section);
  });

  // 绑定事件监听器
  positionPanel.querySelectorAll('input[type="range"]').forEach(slider => {
    slider.addEventListener('input', handlePositionChange);
  });
}

function getCurrentParams() {
  const positions = {};
  document.querySelectorAll('#position-controls input[type="range"]').forEach(slider => {
    const elementId = slider.dataset.element;
    const axis = slider.dataset.axis;
    if (!positions[elementId]) {
      positions[elementId] = {};
    }
    positions[elementId][axis] = parseFloat(slider.value);
  });

  return {
    layout: {
      colors: getCurrentColors(),
      font_size: getFontSize(),
      positions: positions  // 新增：位置配置
    },
    brand: getCurrentBrand(),
    scenes: getCurrentScenes()
  };
}
```

**关键点**：
- 前端完全由 `positionable_elements` 驱动，无模板特定代码
- 新增模板时，只需在 defaults.yaml 声明元素，前端自动生成控件
- 约束条件在前端强制执行（slider min/max）

---

## 6. Trade-offs 分析

### 6.1 坐标系统选择

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| **百分比（左上角）** | 分辨率无关、直观、符合设计工具习惯 | 需要转换计算 | ✅ **推荐** |
| 像素（左上角） | 精确控制 | 分辨率相关，不可移植 | ❌ |
| Manim 原生坐标 | 无需转换 | 用户难以理解，Y 轴向上反直觉 | ❌ |

### 6.2 元素粒度

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| **粗粒度（逻辑组）** | UI 简洁，易于理解 | 灵活性有限 | ✅ **MVP** |
| 细粒度（每个文本行） | 最大灵活性 | UI 复杂，学习成本高 | 🔄 Phase 2 |
| 混合（可选展开） | 平衡易用性和灵活性 | 实现复杂 | 🔄 Phase 3 |

**建议**：MVP 使用粗粒度（logo_header、topic_line、main_text、illustration、disclaimer），后续根据需求细化。

### 6.3 约束验证

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| 仅前端验证 | 快速反馈 | 可被绕过（直接编辑 YAML） | ❌ |
| 仅后端验证 | 安全可靠 | 反馈延迟（需渲染才知道错误） | ❌ |
| **前后端双重验证** | 快速反馈 + 安全保障 | 代码重复 | ✅ **推荐** |

### 6.4 相对定位 vs 绝对定位

| 方案 | 优势 | 劣势 | 结论 |
|------|------|------|------|
| **绝对定位** | 简单直接，易于实现 | 元素间关系需手动维护 | ✅ **MVP** |
| 相对定位（next_to） | 自动维护间距，响应式布局 | 复杂度高，级联调整 | 🔄 Phase 3 |

**建议**：MVP 使用绝对定位，Phase 3 引入相对定位选项（如 "相对于 topic_line 下方 10%"）。

---

## 7. 风险点与缓解策略

### 7.1 坐标转换错误

**风险**：百分比 ↔ Manim 转换公式错误导致元素错位

**缓解**：
- ✅ 单元测试覆盖边界情况（0%, 50%, 100%）
- ✅ 视觉回归测试（对比调整前后截图）
- ✅ 在前端显示 Manim 坐标（调试模式）

### 7.2 元素重叠

**风险**：用户调整位置导致元素重叠，影响可读性

**缓解**：
- 🔄 Phase 2: 约束条件限制重叠区域（如 disclaimer 只能在右下角）
- 🔄 Phase 3: 碰撞检测 + 警告提示
- ✅ MVP: 预览实时反馈，用户自行调整

### 7.3 模板迁移成本

**风险**：现有 2 个模板需要大量改造（添加元数据 + 重构 scene.py）

**缓解**：
- ✅ 向后兼容：未声明 `positionable_elements` 的模板继续使用硬编码
- ✅ 渐进式迁移：先迁移 minimal-insight（元素少），验证后再迁移 portrait-notebook
- ✅ 工具辅助：编写脚本自动提取现有硬编码位置 → 生成元数据

### 7.4 动态布局复杂度

**风险**：portrait-notebook 使用 `next_to()` 动态定位，难以暴露为百分比

**缓解**：
- ✅ MVP: 仅暴露固定元素（portrait、topic、subtitle）
- 🔄 Phase 2: 动态元素（notebook、caption）使用锚点 + 偏移量
- 🔄 Phase 3: 引入布局模式（固定 vs 流式）

### 7.5 性能影响

**风险**：更多参数导致预览渲染变慢

**缓解**：
- ✅ 已有渲染锁，串行化请求
- ✅ 位置参数不影响 Manim 渲染速度（仅改变 move_to 参数）
- 🔄 Phase 2: 前端防抖（拖动滑块时延迟 500ms 再渲染）

---

## 8. 实施计划

### Phase 1: MVP（核心功能）

**目标**：minimal-insight 模板支持位置调整

**任务**：
1. ✅ 添加 `core/utils.py::percent_to_manim()` 和 `manim_to_percent()`
2. ✅ 扩展 `BaseTemplate::get_positionable_elements()`
3. ✅ 在 `templates/minimal_insight/defaults.yaml` 添加 `positionable_elements`
4. ✅ 重构 `templates/minimal_insight/scene.py`：
   - 添加 `_get_element_position()` 辅助函数
   - 改造 `_build_logo_header()`, `_build_topic_line()`, `_build_disclaimer()` 使用配置位置
5. ✅ 更新 `preview_server.py::_handle_template_defaults()` 返回 `positionable_elements`
6. ✅ 前端 `template_preview.html` 添加位置编辑面板（动态生成）
7. ✅ 测试：调整位置 → 精确预览 → 验证效果

**验收标准**：
- minimal-insight 的 logo、主题句、免责声明可通过前端滑块调整位置
- 调整后点击"精确预览"，元素出现在正确位置
- 导出的 config.yaml 包含 `layout.positions` 配置

### Phase 2: 扩展与优化

**目标**：portrait-notebook 支持 + 约束验证 + 视觉辅助

**任务**：
1. ✅ 在 `templates/portrait_notebook/defaults.yaml` 添加 `positionable_elements`
2. ✅ 重构 `templates/portrait_notebook/scene.py`（固定元素：portrait、topic、subtitle）
3. ✅ 后端约束验证：`preview_server.py::_validate_positions()`
4. ✅ 前端视觉辅助：网格线、标尺、元素边界框
5. ✅ 前端防抖：拖动滑块时延迟渲染

**验收标准**：
- portrait-notebook 的人像、主题、副标题可调整位置
- 超出约束范围时前端显示警告，后端拒绝渲染
- 前端显示网格线辅助对齐

### Phase 3: 高级特性

**目标**：相对定位 + 碰撞检测 + 预设布局

**任务**：
1. 🔄 支持相对定位：`{relative_to: "topic_line", offset: {x: 0, y: 10}}`
2. 🔄 碰撞检测：计算元素边界框，重叠时显示警告
3. 🔄 预设布局：提供 3-5 种布局模板（紧凑、宽松、左对齐、居中）
4. 🔄 导出工具：从现有视频反推元素位置 → 生成配置

---

## 9. 示例：minimal-insight 完整改造

### 9.1 defaults.yaml（新增部分）

```yaml
# templates/minimal_insight/defaults.yaml
positionable_elements:
  - id: "logo_header"
    label: "Logo 和作者名"
    type: "group"
    default_position: {x: 10, y: 5}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 0, max: 15}

  - id: "topic_line"
    label: "主题句"
    type: "text"
    default_position: {x: 50, y: 12}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 5, max: 30}

  - id: "pinyin"
    label: "拼音"
    type: "text"
    default_position: {x: 50, y: 25}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 15, max: 40}

  - id: "illustration"
    label: "插画"
    type: "image"
    default_position: {x: 50, y: 60}
    constraints:
      x: {min: 0, max: 100}
      y: {min: 40, max: 85}

  - id: "disclaimer"
    label: "免责声明"
    type: "text"
    default_position: {x: 85, y: 80}
    constraints:
      x: {min: 50, max: 100}
      y: {min: 70, max: 95}
```
