# 位置调整系统规范 (POSITION_SYSTEM_SPEC)

> 版本: v1.0 | 日期: 2026-03-09
> 状态: DRAFT — 待实现
>
> 本文档基于 5 轮代码审查 + 双 CLI 联合诊断的结论，定义位置调整系统的完整契约。
> 所有实现必须严格遵循本规范，优先级高于现有代码行为。

---

## 1. 背景与根因

### 1.1 发现的三个系统性问题

| 问题编号 | 描述 | 影响范围 |
|---------|------|---------|
| P1 | **数据模型混层** — `positionable_elements[].default_x/y` 同时承担三个职责：UI 滑块初始值、模板默认布局、运行时覆盖写回 | `defaults.yaml`, `scene.py`, `preview_server.py` |
| P2 | **跨层契约缺失** — 前端/后端/模板/配置系统无统一的位置数据通道，显式定位判定逻辑散落在 `_build_pinyin()` 和插画渲染两处，且判定逻辑不一致 | `scene.py:375-388`, `scene.py:523-535` |
| P3 | **取消只做到前端** — 前端 `AbortController` 只取消 HTTP fetch，服务端 Manim 子进程继续运行、持续占锁，导致后续渲染 5 秒超时后才能执行 | `preview_server.py:679-686`, `preview_server.py:1008-1023` |

### 1.2 现状（Before）

```
defaults.yaml
  positionable_elements:
    - id: "logo"
      default_x: 10.0    ← 三种用途混用同一字段
      default_y: 7.8
      min_x/max_x/...    ← 约束元数据

preview_server.py _write_temp_yaml()
  # 用户拖动位置后 → 直接写回 positionable_elements[].default_x/y
  elem_copy["default_x"] = pos["x"]   ← 运行时覆盖写入 manifest 字段

scene.py _get_element_position()
  # 读取 positionable_elements[].default_x/y 作为布局坐标
  # 无法区分"模板默认"和"用户覆盖"

scene.py _build_pinyin()
  # 通过检查 positionable_elements[] 中是否有 default_x/y 来判断是否显式定位
  # defaults.yaml 中所有元素都有 default_x/y，导致判定逻辑失效
```

---

## 2. 数据模型三层架构（核心）

### 2.1 三层定义

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: 元数据层 (manifest)                                     │
│  位置: positionable_elements[] in defaults.yaml                   │
│  职责: 声明哪些元素可调整 + 约束范围 + UI label                     │
│  字段: id, label, min_x, max_x, min_y, max_y, step              │
│  关键: 不包含坐标！default_x/y 是 UI 滑块初始值，语义独立            │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: 默认层 (defaults)                                       │
│  位置: positionable_elements[].default_x/y in defaults.yaml       │
│  职责: 为前端滑块提供初始显示值；为没有 layout.positions 覆盖的      │
│        固定定位元素提供模板默认坐标                                   │
│  分两类:                                                          │
│    A. 绝对定位元素 (logo, disclaimer, footer_bar 等)               │
│       有固定的默认百分比坐标 → 参与布局计算                          │
│    B. 流式布局元素 (pinyin, illustration)                          │
│       默认跟随其他元素动态计算，default_x/y 仅作前端滑块初始值        │
│       不参与布局计算（除非 layout.positions 中有该元素的覆盖）        │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: 覆盖层 (overrides)                                      │
│  位置: layout.positions in config YAML                            │
│  职责: 用户/运行时的位置覆盖，独立字段，不经过 _deep_merge            │
│  格式: { element_id: { x: float, y: float }, ... }               │
│  关键: 只有在此层中存在的元素才算"显式定位"                           │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 字段规范

#### 元数据层字段（`positionable_elements[]`）

```yaml
# defaults.yaml
positionable_elements:
  - id: "logo"               # 必填，字符串，模板内唯一
    label: "Logo 圆圈"        # 必填，字符串，前端显示名
    default_x: 10.0          # 必填，float，前端滑块初始值（百分比，0-100）
    default_y: 7.8           # 必填，float，前端滑块初始值（百分比，0-100）
    min_x: 0                 # 必填，float，滑块最小值
    max_x: 30                # 必填，float，滑块最大值
    min_y: 0                 # 必填，float，滑块最小值
    max_y: 20                # 必填，float，滑块最大值
    step: 0.5                # 可选，float，默认 1.0
    flow_layout: false       # 可选，bool，默认 false
                             # true = 流式布局元素，default_x/y 不参与布局计算
```

**`flow_layout` 字段说明：**

| `flow_layout` | `layout.positions` 中有覆盖 | 布局行为 |
|--------------|---------------------------|---------|
| `false`（默认）| 否 | 使用 `default_x/y` 计算 Manim 坐标 |
| `false` | 是 | 使用 `layout.positions[id]` 计算 Manim 坐标（覆盖优先） |
| `true` | 否 | 跟随相对布局算法（next_to / 动态计算） |
| `true` | 是 | 使用 `layout.positions[id]` 计算 Manim 坐标（显式定位） |

#### 覆盖层字段（`layout.positions`）

```yaml
# config YAML（用户配置 / 预览服务器写入的临时 YAML）
layout:
  positions:                 # 可选，dict
    logo:                    # key = element id
      x: 12.5                # float，百分比，0-100
      y: 8.0                 # float，百分比，0-100
    illustration:
      x: 50.0
      y: 60.0
```

**`layout.positions` 约束：**
- 坐标值必须在对应元素的 `[min_x, max_x]` / `[min_y, max_y]` 范围内（后端校验）
- `x` 和 `y` 必须**同时提供**且均为数值类型（int/float，不含 bool）
- 缺失任意一个或类型非法的条目由 `sanitize_positions()` 自动过滤，不参与布局
- 空 `{}` 等价于不存在

---

## 3. 位置优先级

从低到高：

```
Level 1（最低）: 相对布局算法
   flow_layout=true 且 layout.positions 中无该元素
   → next_to / 跟随动态计算

Level 2: 模板默认固定坐标
   flow_layout=false 且 layout.positions 中无该元素
   → positionable_elements[id].default_x/y

Level 3（最高）: 用户/运行时覆盖
   layout.positions[id] 存在
   → layout.positions[id].x/y，覆盖以上所有
```

---

## 4. 显式定位判定规则

**唯一判定条件：`layout.positions[element_id]` 存在且 `x`/`y` 均为数值**

```python
def is_explicitly_positioned(cfg: dict, element_id: str) -> bool:
    """
    当且仅当 layout.positions 中存在该元素且 x/y 均为数值时，返回 True。
    positionable_elements[].default_x/y 不触发显式定位。
    partial positions（只有 x 或只有 y，或非数值）不算显式定位。
    """
    positions = cfg.get("layout", {}).get("positions", {})
    if element_id not in positions:
        return False
    pos = positions[element_id]
    if not isinstance(pos, dict):
        return False
    x, y = pos.get("x"), pos.get("y")
    return (
        isinstance(x, (int, float)) and not isinstance(x, bool)
        and isinstance(y, (int, float)) and not isinstance(y, bool)
    )
```

**禁止的判定方式（现行代码的 bug，需修复）：**

```python
# ❌ 错误：通过 positionable_elements 中有无 default_x/y 来判断
if pinyin_elem and "default_x" in pinyin_elem and "default_y" in pinyin_elem:
    # 这会让所有模板默认坐标触发显式定位，违反语义
```

---

## 5. 合并规则

### 5.1 `_deep_merge` 语义（不变）

```python
# core/config.py
# template.defaults < user_config
merged = _deep_merge(template_defaults, user_config)
```

规则（现有行为，保持不变）：
- `user_config` 中的值覆盖 `template_defaults`
- `user_config` 中的 `null` 覆盖 `template_defaults`（清空语义）
- 嵌套 `dict` 递归合并
- `user_config` 中不存在的键继承 `template_defaults`

### 5.2 `layout.positions` 独立通道

`layout.positions` **不经过 `_deep_merge`**，作为独立通道传递：

```
用户配置 YAML 中的 layout.positions
          ↓
  直接传入 scene.py（通过 env CARD_CAROUSEL_CONFIG_PATH）
          ↓
  scene.py 读取 cfg["layout"]["positions"]
          ↓
  优先级判定 → 计算 Manim 坐标
```

`_deep_merge` 中 `layout` 是普通 dict，`layout.positions` 会随 `layout` 一起合并，但合并后的 `positions` dict 本身是用户提供的原始值（非 template_defaults 中的值，因为 template_defaults 不应有 `layout.positions`）。

**模板 defaults.yaml 不得包含 `layout.positions` 字段。**

### 5.3 preview_server 写入临时 YAML 的规则（重要变更）

```python
# ❌ 当前行为（需修复）：
# _write_temp_yaml() 将 positions 写入 positionable_elements[].default_x/y
elem_copy["default_x"] = pos["x"]

# ✅ 目标行为：
# _write_temp_yaml() 将 positions 写入 layout.positions
cfg["layout"]["positions"] = params.get("positions", {})
# positionable_elements 从模板 defaults 原样复制，不修改
```

---

## 6. 前端状态管理

### 6.1 状态结构

```javascript
// currentParams 统一管理所有参数，包含位置
const currentParams = {
  colors: { ... },
  brand: { ... },
  layout: { ... },
  footer_tags: [...],
  scenes: [...],
  positions: {}   // ← 位置并入 currentParams，不再是独立的 currentPositions
}
```

**废弃**独立的 `currentPositions` 变量（如果存在），改为 `currentParams.positions`。

### 6.2 localStorage 持久化

```javascript
// 按模板分开存储，避免不同模板的位置数据互相污染
const STORAGE_KEY = `card_carousel_positions_${templateId}`;

// 保存：只存储用户修改过的位置（dirty positions）
localStorage.setItem(STORAGE_KEY, JSON.stringify(currentParams.positions));

// 加载：页面初始化 / 模板切换时恢复
const saved = localStorage.getItem(STORAGE_KEY);
if (saved) {
  currentParams.positions = JSON.parse(saved);
}
```

### 6.3 只发送修改过的位置

```javascript
// ✅ 只发送用户拖动过的位置，未修改的不发送
// dirtyPositions 是用户实际拖动过的元素 id 集合
function getPositionsToSend() {
  const result = {};
  for (const [id, pos] of Object.entries(currentParams.positions)) {
    // 只有 dirtyPositions 中有标记的才发送
    if (dirtyPositions.has(id)) {
      result[id] = pos;
    }
  }
  return result;
}
```

---

## 7. 渲染请求生命周期

### 7.1 前端：last-write-wins 串行化（推荐方案）

```
用户拖动滑块
    ↓
更新 currentParams.positions[id]
标记 dirtyPositions.add(id)
    ↓
if (renderInProgress) {
    pendingRenderParams = currentParams  // 记录最新参数
    return  // 不立即发起新渲染
} else {
    triggerRender(currentParams)
}
    ↓
渲染完成（无论成功/失败）
    ↓
if (pendingRenderParams !== null) {
    const params = pendingRenderParams
    pendingRenderParams = null
    triggerRender(params)  // 发起一次补偿渲染
}
```

**优点**：不 debounce，用户停止拖动后立即触发一次精确渲染。
**vs debounce**：debounce 会在用户还在拖动时等待，延迟感更强。

**简化方案**（可接受，适合 preview tool）：
```javascript
// 前端用 change 事件（松手后触发）+ 500ms debounce
slider.addEventListener('change', debounce(triggerRender, 500));
// 后端保持现有锁机制（503 繁忙时前端重试）
```

### 7.2 后端：request_id 机制（完整方案）

```python
# 每个渲染请求携带 request_id
# { template, params, request_id: "uuid" }

_current_render: dict | None = None  # { request_id, process }
_render_lock = threading.Lock()

def _handle_render_frame():
    request_id = payload.get("request_id") or str(uuid.uuid4())

    with _render_lock:
        # 取消进行中的渲染（如果有）
        if _current_render:
            old_proc = _current_render["process"]
            if old_proc and old_proc.poll() is None:
                old_proc.terminate()
                old_proc.wait(timeout=3)
        _current_render = {"request_id": request_id, "process": None}

    # 异步渲染，非阻塞获取锁
    proc = subprocess.Popen(cmd, ...)
    with _render_lock:
        if _current_render["request_id"] == request_id:
            _current_render["process"] = proc

    try:
        stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise RuntimeError("渲染超时")

    # 检查是否被取消
    with _render_lock:
        if _current_render["request_id"] != request_id:
            raise RenderCancelledError("请求已被取消")
```

**简化方案**（可接受）：
```python
# 保持现有 threading.Lock，但改为 non-blocking acquire
acquired = _render_lock.acquire(blocking=False)
if not acquired:
    return 503  # 直接返回，不等待
# 渲染完成后 release
```

> **阶段性建议**：preview tool 先用简化方案（change + debounce / non-blocking lock）。
> 完整方案（request_id + subprocess kill）在需要高响应度时实现。

---

## 8. `pixel_height` / `_render_dir` 安全

### 8.1 问题

`_render_dir` 路径依赖 `pixel_height`：

```python
quality_dir = f"{pixel_height}p{fps}"
cfg["_render_dir"] = os.path.join(media_base, quality_dir)
```

如果调用方（前端/用户 config）传入错误的 `pixel_height`，会导致 `_render_dir` 指向错误路径，`step_voice` 找不到渲染产物。

### 8.2 修复规则

**模板模式下，`pixel_height` 从模板 scene 常量推导，不信任调用方输入。**

```python
# preview_server.py _write_temp_yaml()
# 当前已有此修复（第547-548行），需确保正式管线也遵循此规则

# core/config.py _apply_template()
# 模板模式下，pixel_height 强制从模板 defaults 取值，忽略用户 config 中的 pixel_height
if "template" in cfg:
    # pixel_height 由模板固定，不允许用户覆盖
    template_pixel_height = tmpl_defaults.get("layout", {}).get("pixel_height")
    if template_pixel_height:
        cfg.setdefault("layout", {})["pixel_height"] = template_pixel_height
        # 覆盖用户可能传入的错误值
```

### 8.3 向后兼容（旧模式）

旧模式（无 `template` 字段）：`pixel_height` 从用户 config 读取，保持现有行为。

---

## 9. 向后兼容

### 9.1 旧模式（无 `template` 字段）

旧模式 config 不含 `template` 字段，走 `config.py` 的旧路径，不受本规范影响：
- 无 `positionable_elements`
- 无 `layout.positions`
- scene.py 的 `_get_element_position()` 在 `elements=[]` 时返回硬编码 fallback

### 9.2 现有模板（有 `positionable_elements` 但无 `flow_layout` 字段）

`flow_layout` 字段默认为 `false`，意味着所有现有 `positionable_elements` 元素保持绝对定位语义。

**迁移路径**：
1. 为 `pinyin_text` 和 `illustration` 添加 `flow_layout: true`（在 defaults.yaml 中）
2. scene.py 的 `_build_pinyin()` 和插画渲染读取 `flow_layout`，替代现有的 `_has_explicit_position` 检查
3. 位置覆盖从 `layout.positions` 读取，替代现有的 `elem["default_x"]` 检查

### 9.3 新模板扩展

新模板只需在 `defaults.yaml` 中声明 `positionable_elements`，`scene.py` 调用统一的 `get_element_position(cfg, element_id)` 函数（见第 10 节）。

---

## 10. 统一接口（需新增/修改的函数）

### 10.1 `get_element_position(cfg, element_id, fallback)` (scene.py)

替代现有的 `_get_element_position()`，实现完整优先级逻辑：

```python
def get_element_position(
    cfg: dict,
    element_id: str,
    fallback_manim_coords: tuple[float, float],
) -> tuple[float, float]:
    """
    按三层优先级返回 Manim 坐标：
      Level 3: layout.positions[element_id] 存在 → 使用覆盖坐标
      Level 2: positionable_elements[id].default_x/y + flow_layout=false → 使用模板默认坐标
      Level 1: flow_layout=true 且无覆盖 → 返回 None（调用方负责相对布局）
               或 fallback（若不支持相对布局的元素）
    """
    # Level 3: 检查 layout.positions
    positions = cfg.get("layout", {}).get("positions", {})
    if element_id in positions and isinstance(positions[element_id], dict):
        pos = positions[element_id]
        x = pos.get("x")
        y = pos.get("y")
        if x is not None and y is not None:
            return percent_to_manim(x, y, config.frame_width, config.frame_height)

    # Level 2 & 1: 检查 positionable_elements
    elements = cfg.get("positionable_elements", [])
    for elem in elements:
        if elem.get("id") != element_id:
            continue
        flow_layout = elem.get("flow_layout", False)
        if flow_layout:
            # 流式布局：返回 None，调用方负责 next_to 等相对布局
            return None
        # 绝对定位：使用 default_x/y
        default_x = elem.get("default_x")
        default_y = elem.get("default_y")
        if default_x is not None and default_y is not None:
            return percent_to_manim(default_x, default_y, config.frame_width, config.frame_height)

    # fallback（向后兼容）
    return fallback_manim_coords
```

**返回 `None` 的约定**：调用方需处理 `None`，表示使用相对布局（`next_to`）。

### 10.2 `_validate_positions(positions, template_id)` (preview_server.py)

保持现有逻辑不变（校验 element_id 合法性 + x/y 范围），无需修改。

### 10.3 `_write_temp_yaml()` (preview_server.py) 关键改动

```python
# ❌ 删除现有的 positions → positionable_elements 写回逻辑（第582-599行）

# ✅ 新增：positions → layout.positions
if "positions" in params and isinstance(params["positions"], dict):
    cfg.setdefault("layout", {})["positions"] = params["positions"]
# positionable_elements 不修改，直接从模板 defaults 继承
```

---

## 11. 测试用例清单

### 11.1 位置优先级测试

```python
# test_position_priority.py

def test_level3_overrides_level2():
    """layout.positions 覆盖 positionable_elements.default_x/y"""
    cfg = {
        "layout": { "positions": { "logo": { "x": 20.0, "y": 10.0 } } },
        "positionable_elements": [{ "id": "logo", "default_x": 10.0, "default_y": 7.8 }]
    }
    mx, my = get_element_position(cfg, "logo", (-3.2, 4.5))
    expected = percent_to_manim(20.0, 10.0, 8, 10.667)
    assert (mx, my) == approx(expected)

def test_level2_used_when_no_override():
    """无 layout.positions 时使用 positionable_elements.default_x/y"""
    cfg = {
        "positionable_elements": [{ "id": "logo", "default_x": 10.0, "default_y": 7.8 }]
    }
    mx, my = get_element_position(cfg, "logo", (-3.2, 4.5))
    expected = percent_to_manim(10.0, 7.8, 8, 10.667)
    assert (mx, my) == approx(expected)

def test_flow_layout_returns_none():
    """flow_layout=true 且无覆盖时返回 None"""
    cfg = {
        "positionable_elements": [{ "id": "pinyin_text", "default_x": 50.0, "default_y": 32.0, "flow_layout": True }]
    }
    result = get_element_position(cfg, "pinyin_text", (0, 2.0))
    assert result is None

def test_flow_layout_overridden_by_positions():
    """flow_layout=true 但 layout.positions 有覆盖 → 使用覆盖坐标"""
    cfg = {
        "layout": { "positions": { "pinyin_text": { "x": 50.0, "y": 40.0 } } },
        "positionable_elements": [{ "id": "pinyin_text", "flow_layout": True, "default_x": 50.0, "default_y": 32.0 }]
    }
    result = get_element_position(cfg, "pinyin_text", (0, 2.0))
    assert result is not None
    expected = percent_to_manim(50.0, 40.0, 8, 10.667)
    assert result == approx(expected)

def test_fallback_when_no_elements():
    """无 positionable_elements 时使用 fallback（向后兼容旧模式）"""
    cfg = {}
    result = get_element_position(cfg, "logo", (-3.2, 4.5))
    assert result == (-3.2, 4.5)
```

### 11.2 null 清空测试

```python
def test_null_clears_template_default():
    """user_config 中的 null 覆盖 template_defaults（_deep_merge 语义）"""
    base = { "brand": { "pinyin": "HUANG FU", "disclaimer": "个人观点" } }
    override = { "brand": { "pinyin": None } }
    result = _deep_merge(base, override)
    assert result["brand"]["pinyin"] is None
    assert result["brand"]["disclaimer"] == "个人观点"  # 未覆盖的键继承

def test_positions_not_in_deep_merge():
    """layout.positions 不应出现在模板 defaults 中"""
    from templates import get_template
    for tmpl_name in ["minimal-insight", "portrait-notebook"]:
        tmpl = get_template(tmpl_name)
        defaults = tmpl.get_default_config()
        layout = defaults.get("layout", {})
        assert "positions" not in layout, f"模板 {tmpl_name} 的 defaults 不应含 layout.positions"
```

### 11.3 显式定位判定测试

```python
def test_explicit_only_from_layout_positions():
    """显式定位 = layout.positions 中存在该元素"""
    cfg_explicit = {
        "layout": { "positions": { "illustration": { "x": 50.0, "y": 60.0 } } },
        "positionable_elements": [{ "id": "illustration", "default_x": 50.0, "default_y": 55.0, "flow_layout": True }]
    }
    assert is_explicitly_positioned(cfg_explicit, "illustration") is True

    cfg_implicit = {
        "positionable_elements": [{ "id": "illustration", "default_x": 50.0, "default_y": 55.0, "flow_layout": True }]
    }
    assert is_explicitly_positioned(cfg_implicit, "illustration") is False
```

### 11.4 合并语义测试

```python
def test_write_temp_yaml_positions_in_layout():
    """preview_server _write_temp_yaml 应将 positions 写入 layout.positions"""
    import yaml, tempfile, os
    from tools.preview_server import _write_temp_yaml

    params = {
        "positions": { "logo": { "x": 15.0, "y": 9.0 } },
        "scenes": [{ "name": "Scene01_Cards", "narration": "test", "illustration_keywords": [] }]
    }
    tmp = _write_temp_yaml("minimal-insight", params)
    try:
        with open(tmp) as f:
            cfg = yaml.safe_load(f)
        assert cfg.get("layout", {}).get("positions") == { "logo": { "x": 15.0, "y": 9.0 } }
        # positionable_elements 不应有运行时覆盖的痕迹
        for elem in cfg.get("positionable_elements", []):
            if elem.get("id") == "logo":
                assert elem.get("default_x") == 10.0  # 模板原始值，未被覆盖
    finally:
        os.unlink(tmp)
```

### 11.5 positions 校验测试

```python
def test_positions_validation_rejects_unknown_element():
    """positions 中的未知 element_id 应被拒绝"""
    from tools.preview_server import _validate_positions
    with pytest.raises(ValueError, match="不在模板.*的可定位元素列表中"):
        _validate_positions({"unknown_elem": {"x": 50, "y": 50}}, "minimal-insight")

def test_positions_validation_rejects_out_of_range():
    """positions 中超出 min/max 范围的坐标应被拒绝"""
    from tools.preview_server import _validate_positions
    with pytest.raises(ValueError, match="范围内"):
        _validate_positions({"logo": {"x": 99.0, "y": 7.8}}, "minimal-insight")
        # logo.max_x = 30，传入 99.0 应报错
```

---

## 12. 迁移路径（分阶段实施）

### Phase 1：规范化 defaults.yaml（低风险）

1. `templates/minimal_insight/defaults.yaml`: 为 `pinyin_text`, `illustration` 添加 `flow_layout: true`
2. `templates/portrait_notebook/defaults.yaml`: 同上（对应元素）
3. 更新 `BaseTemplate.get_positionable_elements()` 文档注释，说明 `flow_layout` 字段语义

### Phase 2：修复 preview_server.py 的 positions 写回（中风险）

1. 删除 `_write_temp_yaml()` 中将 positions 写入 `positionable_elements[].default_x/y` 的代码
2. 改为写入 `layout.positions`
3. 运行 11.4 测试验证

### Phase 3：修复 scene.py 的位置读取（中风险）

1. 新增 `get_element_position()` 函数（含三层优先级逻辑）
2. 替换 `_get_element_position()`（旧版无 flow_layout 支持）
3. 修复 `_build_pinyin()` 和插画渲染的显式定位判定，统一使用 `is_explicitly_positioned()`
4. 运行 11.1、11.3 测试验证

### Phase 4：前端状态管理重构（中风险）

1. 将 `currentPositions` 并入 `currentParams.positions`
2. 实现按模板分开的 localStorage 持久化
3. 实现 last-write-wins 串行化（或 change+debounce 简化方案）

### Phase 5：后端取消机制（可选，高收益）

1. 引入 `request_id` + subprocess kill 机制（或改用 non-blocking acquire）
2. 解决 P3 问题（服务端渲染不响应前端取消）

---

## 13. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `templates/minimal_insight/defaults.yaml` | modify | 为 `pinyin_text`, `illustration` 添加 `flow_layout: true` |
| `templates/portrait_notebook/defaults.yaml` | modify | 为流式布局元素添加 `flow_layout: true` |
| `templates/base.py` | modify | `get_positionable_elements()` 文档更新，新增 `get_pixel_height()` 抽象方法（Phase 8 安全修复） |
| `core/config.py` | modify | 模板模式下强制从模板 defaults 取 `pixel_height` |
| `tools/preview_server.py` | modify | `_write_temp_yaml()` 改为写 `layout.positions`；后端取消机制（Phase 5） |
| `templates/minimal_insight/scene.py` | modify | 新增 `get_element_position()` + `is_explicitly_positioned()`；修复显式定位判定 |
| `templates/portrait_notebook/scene.py` | modify | 同上 |
| `tools/template_preview.html` | modify | `currentPositions` 并入 `currentParams.positions`；localStorage 持久化；last-write-wins |
| `test_position_system.py` | create | 11.1-11.5 测试用例 |

---

## 附录 A：坐标系约定

```
坐标系：百分比坐标
  左上角 (0%, 0%)
  右下角 (100%, 100%)

转换函数：percent_to_manim(px, py, frame_width, frame_height)
  mx = (px / 100 - 0.5) * frame_width
  my = (0.5 - py / 100) * frame_height
  (在 core/utils.py 已实现)
```

---

## 附录 B：当前代码 bug 快速索引

| 文件 | 行号 | 问题 | 对应规范节 |
|------|------|------|-----------|
| `preview_server.py` | 582-599 | positions 写回 positionable_elements.default_x/y | §5.3 |
| `scene.py` | 375-388 | 通过 positionable_elements 中有无 default_x/y 判断显式定位 | §4 |
| `scene.py` | 523-535 | 同上（插画渲染路径） | §4 |
| `preview_server.py` | 1008 | `_render_lock.acquire(blocking=True, timeout=5)` 不释放服务端进程 | §7.2 |
| `core/config.py` | 194 | 模板模式下允许用户覆盖 pixel_height | §8.2 |
