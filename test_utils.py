"""
单元测试 — core/utils.py 坐标转换函数
"""

import pytest
from core.utils import percent_to_manim, manim_to_percent, is_explicitly_positioned, get_element_position, sanitize_positions


class TestCoordinateConversion:
    """测试百分比坐标与 Manim 坐标的双向转换"""

    def test_percent_to_manim_center(self):
        """测试中心点转换：(50%, 50%) → (0, 0)"""
        width, height = 8.0, 10.67
        mx, my = percent_to_manim(50, 50, width, height)
        assert mx == pytest.approx(0.0, abs=1e-6)
        assert my == pytest.approx(0.0, abs=1e-6)

    def test_percent_to_manim_top_left(self):
        """测试左上角转换：(0%, 0%) → (-w/2, h/2)"""
        width, height = 8.0, 10.67
        mx, my = percent_to_manim(0, 0, width, height)
        assert mx == pytest.approx(-4.0, abs=1e-6)
        assert my == pytest.approx(5.335, abs=1e-3)

    def test_percent_to_manim_bottom_right(self):
        """测试右下角转换：(100%, 100%) → (w/2, -h/2)"""
        width, height = 8.0, 10.67
        mx, my = percent_to_manim(100, 100, width, height)
        assert mx == pytest.approx(4.0, abs=1e-6)
        assert my == pytest.approx(-5.335, abs=1e-3)

    def test_manim_to_percent_center(self):
        """测试中心点反向转换：(0, 0) → (50%, 50%)"""
        width, height = 8.0, 10.67
        px, py = manim_to_percent(0, 0, width, height)
        assert px == pytest.approx(50.0, abs=1e-6)
        assert py == pytest.approx(50.0, abs=1e-6)

    def test_manim_to_percent_top_left(self):
        """测试左上角反向转换：(-w/2, h/2) → (0%, 0%)"""
        width, height = 8.0, 10.67
        px, py = manim_to_percent(-4.0, 5.335, width, height)
        assert px == pytest.approx(0.0, abs=1e-6)
        assert py == pytest.approx(0.0, abs=1e-3)

    def test_manim_to_percent_bottom_right(self):
        """测试右下角反向转换：(w/2, -h/2) → (100%, 100%)"""
        width, height = 8.0, 10.67
        px, py = manim_to_percent(4.0, -5.335, width, height)
        assert px == pytest.approx(100.0, abs=1e-6)
        assert py == pytest.approx(100.0, abs=1e-3)

    def test_roundtrip_conversion(self):
        """测试往返转换的一致性"""
        width, height = 8.0, 10.67
        test_cases = [
            (25, 25),
            (75, 75),
            (10, 90),
            (90, 10),
            (50, 20),
            (30, 60),
        ]
        for px_orig, py_orig in test_cases:
            mx, my = percent_to_manim(px_orig, py_orig, width, height)
            px_back, py_back = manim_to_percent(mx, my, width, height)
            assert px_back == pytest.approx(px_orig, abs=1e-6)
            assert py_back == pytest.approx(py_orig, abs=1e-6)

    def test_different_aspect_ratios(self):
        """测试不同宽高比的场景"""
        # 16:9 横屏
        width, height = 16.0, 9.0
        mx, my = percent_to_manim(50, 50, width, height)
        assert mx == pytest.approx(0.0, abs=1e-6)
        assert my == pytest.approx(0.0, abs=1e-6)

        # 9:16 竖屏
        width, height = 9.0, 16.0
        mx, my = percent_to_manim(50, 50, width, height)
        assert mx == pytest.approx(0.0, abs=1e-6)
        assert my == pytest.approx(0.0, abs=1e-6)

    def test_edge_values(self):
        """测试边界值"""
        width, height = 8.0, 10.67

        # X 轴边界
        mx_left, _ = percent_to_manim(0, 50, width, height)
        mx_right, _ = percent_to_manim(100, 50, width, height)
        assert mx_left == pytest.approx(-4.0, abs=1e-6)
        assert mx_right == pytest.approx(4.0, abs=1e-6)

        # Y 轴边界
        _, my_top = percent_to_manim(50, 0, width, height)
        _, my_bottom = percent_to_manim(50, 100, width, height)
        assert my_top == pytest.approx(5.335, abs=1e-3)
        assert my_bottom == pytest.approx(-5.335, abs=1e-3)


# ── 位置系统测试 ────────────────────────────────────────────

W, H = 8.0, 10.667  # minimal_insight 帧尺寸


class TestIsExplicitlyPositioned:
    def test_returns_false_when_no_layout(self):
        assert is_explicitly_positioned({}, "logo") is False

    def test_returns_false_when_positions_empty(self):
        cfg = {"layout": {"positions": {}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_false_when_element_not_in_positions(self):
        cfg = {"layout": {"positions": {"illustration": {"x": 50.0, "y": 60.0}}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_true_when_element_in_positions(self):
        cfg = {"layout": {"positions": {"logo": {"x": 12.5, "y": 8.0}}}}
        assert is_explicitly_positioned(cfg, "logo") is True

    def test_returns_false_when_positions_value_not_dict(self):
        """positions[id] 不是 dict 时不算显式定位"""
        cfg = {"layout": {"positions": {"logo": None}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_false_when_only_x_present(self):
        """partial positions: 只有 x 没有 y → 不算显式定位"""
        cfg = {"layout": {"positions": {"logo": {"x": 12.5}}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_false_when_only_y_present(self):
        """partial positions: 只有 y 没有 x → 不算显式定位"""
        cfg = {"layout": {"positions": {"logo": {"y": 8.0}}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_false_when_x_is_not_numeric(self):
        """x 不是数值类型 → 不算显式定位"""
        cfg = {"layout": {"positions": {"logo": {"x": "50", "y": 8.0}}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_false_when_y_is_not_numeric(self):
        """y 不是数值类型 → 不算显式定位"""
        cfg = {"layout": {"positions": {"logo": {"x": 12.5, "y": "8"}}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_returns_false_when_x_is_bool(self):
        """x 为 bool（Python bool 是 int 子类）→ 不算显式定位"""
        cfg = {"layout": {"positions": {"logo": {"x": True, "y": 8.0}}}}
        assert is_explicitly_positioned(cfg, "logo") is False

    def test_default_x_y_in_positionable_elements_not_explicit(self):
        """positionable_elements 中有 default_x/y 不触发显式定位"""
        cfg = {"positionable_elements": [{"id": "logo", "default_x": 10.0, "default_y": 7.8}]}
        assert is_explicitly_positioned(cfg, "logo") is False


class TestGetElementPosition:
    def test_no_config_uses_fallback(self):
        """无 positionable_elements 时使用 fallback（向后兼容旧模式）"""
        result = get_element_position({}, "logo", W, H, fallback_fn=lambda: (-3.2, 4.5))
        assert result == (-3.2, 4.5)

    def test_no_config_no_fallback_returns_none(self):
        """无配置且无 fallback 时返回 None"""
        assert get_element_position({}, "logo", W, H) is None

    def test_level2_default_xy_used_when_no_override(self):
        """flow_layout=false：无 layout.positions 时使用 default_x/y"""
        cfg = {"positionable_elements": [{"id": "logo", "default_x": 10.0, "default_y": 7.8}]}
        result = get_element_position(cfg, "logo", W, H, fallback_fn=lambda: (-3.2, 4.5))
        expected = percent_to_manim(10.0, 7.8, W, H)
        assert result == pytest.approx(expected)

    def test_level3_layout_positions_overrides_default_xy(self):
        """layout.positions 覆盖 positionable_elements.default_x/y"""
        cfg = {
            "layout": {"positions": {"logo": {"x": 20.0, "y": 10.0}}},
            "positionable_elements": [{"id": "logo", "default_x": 10.0, "default_y": 7.8}],
        }
        result = get_element_position(cfg, "logo", W, H, fallback_fn=lambda: (-3.2, 4.5))
        expected = percent_to_manim(20.0, 10.0, W, H)
        assert result == pytest.approx(expected)

    def test_flow_layout_true_returns_none_without_override(self):
        """flow_layout=true 且无 layout.positions → 返回 None"""
        cfg = {
            "positionable_elements": [
                {"id": "pinyin_text", "default_x": 50.0, "default_y": 32.0, "flow_layout": True}
            ]
        }
        assert get_element_position(cfg, "pinyin_text", W, H) is None

    def test_flow_layout_true_calls_fallback_fn(self):
        """flow_layout=true 且无 layout.positions → 调用 fallback_fn"""
        cfg = {
            "positionable_elements": [
                {"id": "pinyin_text", "default_x": 50.0, "default_y": 32.0, "flow_layout": True}
            ]
        }
        result = get_element_position(cfg, "pinyin_text", W, H, fallback_fn=lambda: (0, 2.0))
        assert result == (0, 2.0)

    def test_flow_layout_true_overridden_by_layout_positions(self):
        """flow_layout=true 但 layout.positions 有覆盖 → 使用覆盖坐标"""
        cfg = {
            "layout": {"positions": {"pinyin_text": {"x": 50.0, "y": 40.0}}},
            "positionable_elements": [
                {"id": "pinyin_text", "default_x": 50.0, "default_y": 32.0, "flow_layout": True}
            ],
        }
        result = get_element_position(cfg, "pinyin_text", W, H)
        expected = percent_to_manim(50.0, 40.0, W, H)
        assert result == pytest.approx(expected)

    def test_element_not_in_positionable_elements_uses_fallback(self):
        """元素不在 positionable_elements 中时使用 fallback"""
        cfg = {"positionable_elements": [{"id": "other", "default_x": 10.0, "default_y": 10.0}]}
        result = get_element_position(cfg, "logo", W, H, fallback_fn=lambda: (-3.2, 4.5))
        assert result == (-3.2, 4.5)

    def test_partial_override_xy_ignored_if_missing(self):
        """layout.positions[id] 中只有 x 没有 y 时，不使用该覆盖"""
        cfg = {"layout": {"positions": {"logo": {"x": 20.0}}}}
        result = get_element_position(cfg, "logo", W, H, fallback_fn=lambda: (-3.2, 4.5))
        # 覆盖无效（缺少 y），回退到 positionable_elements 或 fallback
        assert result == (-3.2, 4.5)

    def test_portrait_notebook_frame_dimensions(self):
        """portrait_notebook 帧尺寸（9x16）下坐标转换正确"""
        W2, H2 = 9.0, 16.0
        cfg = {"positionable_elements": [{"id": "topic", "default_x": 50.0, "default_y": 17.5}]}
        result = get_element_position(cfg, "topic", W2, H2)
        expected = percent_to_manim(50.0, 17.5, W2, H2)
        assert result == pytest.approx(expected)


# ── sanitize_positions 测试 ─────────────────────────────────

class TestSanitizePositions:
    def test_empty_dict_returns_empty(self):
        assert sanitize_positions({}) == {}

    def test_non_dict_input_returns_empty(self):
        assert sanitize_positions(None) == {}
        assert sanitize_positions("bad") == {}
        assert sanitize_positions([]) == {}

    def test_valid_entry_preserved(self):
        positions = {"logo": {"x": 10.0, "y": 7.8}}
        result = sanitize_positions(positions)
        assert result == {"logo": {"x": 10.0, "y": 7.8}}

    def test_multiple_valid_entries_preserved(self):
        positions = {
            "logo": {"x": 10.0, "y": 7.8},
            "illustration": {"x": 50.0, "y": 60.0},
        }
        result = sanitize_positions(positions)
        assert result == {
            "logo": {"x": 10.0, "y": 7.8},
            "illustration": {"x": 50.0, "y": 60.0},
        }

    def test_missing_x_filtered(self):
        """只有 y 没有 x → 过滤掉"""
        positions = {"logo": {"y": 7.8}}
        result = sanitize_positions(positions)
        assert result == {}

    def test_missing_y_filtered(self):
        """只有 x 没有 y → 过滤掉"""
        positions = {"logo": {"x": 10.0}}
        result = sanitize_positions(positions)
        assert result == {}

    def test_non_numeric_x_filtered(self):
        positions = {"logo": {"x": "50", "y": 7.8}}
        result = sanitize_positions(positions)
        assert result == {}

    def test_non_numeric_y_filtered(self):
        positions = {"logo": {"x": 10.0, "y": "bad"}}
        result = sanitize_positions(positions)
        assert result == {}

    def test_bool_x_filtered(self):
        """bool 是 int 子类，但不应被接受"""
        positions = {"logo": {"x": True, "y": 7.8}}
        result = sanitize_positions(positions)
        assert result == {}

    def test_bool_y_filtered(self):
        positions = {"logo": {"x": 10.0, "y": False}}
        result = sanitize_positions(positions)
        assert result == {}

    def test_none_value_filtered(self):
        """None 值的条目被过滤"""
        positions = {"logo": None}
        result = sanitize_positions(positions)
        assert result == {}

    def test_non_dict_value_filtered(self):
        """pos 不是 dict（如字符串/数字）被过滤"""
        positions = {"logo": "invalid", "other": 42}
        result = sanitize_positions(positions)
        assert result == {}

    def test_mixed_valid_and_invalid(self):
        """混合合法与非法条目：只保留合法的"""
        positions = {
            "logo": {"x": 10.0, "y": 7.8},          # 合法
            "topic": {"x": 50.0},                     # 缺 y → 过滤
            "subtitle": {"x": "bad", "y": 69.0},      # x 非数值 → 过滤
            "illustration": {"x": 50.0, "y": 55.0},   # 合法
        }
        result = sanitize_positions(positions)
        assert result == {
            "logo": {"x": 10.0, "y": 7.8},
            "illustration": {"x": 50.0, "y": 55.0},
        }

    def test_integer_coordinates_accepted(self):
        """整数坐标（非 bool）也应被接受"""
        positions = {"logo": {"x": 10, "y": 8}}
        result = sanitize_positions(positions)
        assert result == {"logo": {"x": 10, "y": 8}}

    def test_output_is_new_dict(self):
        """返回新 dict，不修改原输入"""
        positions = {"logo": {"x": 10.0, "y": 7.8}}
        result = sanitize_positions(positions)
        assert result is not positions
        assert result["logo"] is not positions["logo"]
