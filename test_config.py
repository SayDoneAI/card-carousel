"""
单元测试 — core/config.py 配置加载
"""

import os
import textwrap


def _write_config(tmpdir: str, yaml_content: str) -> str:
    """写入最小化 YAML 配置，创建占位文件，返回配置路径。"""
    cfg_path = os.path.join(tmpdir, "test.yaml")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write(yaml_content)
    # _find_project_dir 通过 pipeline.py 识别项目根
    open(os.path.join(tmpdir, "pipeline.py"), "w").close()
    # 路径安全校验要求 manim_script 存在于项目目录内（路径检查，不需要文件真实存在）
    return cfg_path


class TestMaxCharsPerCardEnforcement:
    """测试 max_chars_per_card 与 wrap_chars 不一致时被强制修正"""

    def test_inconsistent_max_chars_corrected(self, tmp_path, capsys):
        """wrap_chars=20, max_chars_per_card=30（应为40）→ 加载后强制修正为 40"""
        yaml_content = textwrap.dedent("""\
            title: "测试"
            manim_script: "scene.py"
            layout:
              pixel_height: 1440
              wrap_chars: 20
              max_chars_per_card: 30
            scenes:
              - text: "test"
        """)
        cfg_path = _write_config(str(tmp_path), yaml_content)

        from core.config import load_config

        cfg = load_config(cfg_path)

        assert cfg["layout"]["max_chars_per_card"] == 40
        out = capsys.readouterr().out
        assert "警告" in out
        assert "max_chars_per_card" in out
        assert "强制修正" in out

    def test_consistent_max_chars_unchanged(self, tmp_path, capsys):
        """wrap_chars=20, max_chars_per_card=40（正确）→ 保持不变，无警告"""
        yaml_content = textwrap.dedent("""\
            title: "测试"
            manim_script: "scene.py"
            layout:
              pixel_height: 1440
              wrap_chars: 20
              max_chars_per_card: 40
            scenes:
              - text: "test"
        """)
        cfg_path = _write_config(str(tmp_path), yaml_content)

        from core.config import load_config

        cfg = load_config(cfg_path)

        assert cfg["layout"]["max_chars_per_card"] == 40
        out = capsys.readouterr().out
        assert "警告" not in out

    def test_missing_max_chars_auto_set(self, tmp_path):
        """max_chars_per_card 缺失 → 自动设置为 wrap_chars*2"""
        yaml_content = textwrap.dedent("""\
            title: "测试"
            manim_script: "scene.py"
            layout:
              pixel_height: 1440
              wrap_chars: 15
            scenes:
              - text: "test"
        """)
        cfg_path = _write_config(str(tmp_path), yaml_content)

        from core.config import load_config

        cfg = load_config(cfg_path)

        assert cfg["layout"]["max_chars_per_card"] == 30

    def test_inconsistent_value_after_correction_equals_expected(self, tmp_path):
        """强制修正后值严格等于 wrap_chars*2，与传入值无关"""
        yaml_content = textwrap.dedent("""\
            title: "测试"
            manim_script: "scene.py"
            layout:
              pixel_height: 1440
              wrap_chars: 10
              max_chars_per_card: 99
            scenes:
              - text: "test"
        """)
        cfg_path = _write_config(str(tmp_path), yaml_content)

        from core.config import load_config

        cfg = load_config(cfg_path)

        assert cfg["layout"]["max_chars_per_card"] == 20  # 10 * 2


class TestTemplateManifestBounds:
    """验证所有模板 positionable_elements 的 default 值在 min/max 范围内"""

    def _get_all_elements(self):
        """收集所有已注册模板的 positionable_elements"""
        import templates  # noqa: F401 — 触发自注册
        from templates import get_all_templates
        result = []
        for template_name, tmpl in get_all_templates().items():
            for elem in tmpl.get_positionable_elements():
                result.append((template_name, elem))
        return result

    def test_default_x_within_bounds(self):
        """所有元素的 default_x 必须在 [min_x, max_x] 范围内"""
        for template_name, elem in self._get_all_elements():
            elem_id = elem.get("id", "?")
            if elem.get("fixed"):
                continue
            default_x = elem["default_x"]
            min_x = elem["min_x"]
            max_x = elem["max_x"]
            assert min_x <= default_x <= max_x, (
                f"模板 {template_name!r} 元素 {elem_id!r}: "
                f"default_x={default_x} 超出范围 [{min_x}, {max_x}]"
            )

    def test_default_y_within_bounds(self):
        """所有元素的 default_y 必须在 [min_y, max_y] 范围内"""
        for template_name, elem in self._get_all_elements():
            elem_id = elem.get("id", "?")
            if elem.get("fixed"):
                continue
            default_y = elem["default_y"]
            min_y = elem["min_y"]
            max_y = elem["max_y"]
            assert min_y <= default_y <= max_y, (
                f"模板 {template_name!r} 元素 {elem_id!r}: "
                f"default_y={default_y} 超出范围 [{min_y}, {max_y}]"
            )
