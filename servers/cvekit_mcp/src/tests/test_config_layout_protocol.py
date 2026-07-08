"""测试 TargetConfigLayout 协议和 AdaptResult 数据结构。"""
from cvekit.utils.config_layout.protocol import (
    AdaptResult,
    TargetConfigLayout,
    TargetConfigLayoutError,
    ConfigError,
    LayoutError,
)


class TestAdaptResult:
    def test_defaults(self):
        result = AdaptResult()
        assert result.filtered_patch == ""
        assert result.config_patches == ""
        assert result.unresolved == []
        assert result.handled_source_paths == []

    def test_as_dict(self):
        result = AdaptResult(
            filtered_patch="code only",
            config_patches="config diff",
            unresolved=[{"source_file": "a", "arch": "arm64", "config": "C", "reason": "test"}],
            handled_source_paths=["arch/arm64/configs/defconfig"],
        )
        d = result.as_dict()
        assert d["filtered_patch"] == "code only"
        assert d["config_patches"] == "config diff"
        assert len(d["unresolved"]) == 1
        assert d["handled_source_paths"] == ["arch/arm64/configs/defconfig"]

    def test_unresolved_mutation_isolation(self):
        result = AdaptResult()
        result.unresolved.append({"key": "value"})
        d = result.as_dict()
        d["unresolved"].append({"key2": "value2"})
        assert len(result.unresolved) == 1
        assert len(result.as_dict()["unresolved"]) == 1


class TestExceptions:
    def test_error_hierarchy(self):
        assert issubclass(ConfigError, TargetConfigLayoutError)
        assert issubclass(LayoutError, TargetConfigLayoutError)
        assert issubclass(TargetConfigLayoutError, RuntimeError)

    def test_config_error_message(self):
        err = ConfigError("未知的 target_config_layout: xxx")
        assert "xxx" in str(err)

    def test_layout_error_message(self):
        err = LayoutError("缺少 anolis/configs")
        assert "anolis/configs" in str(err)


class TestProtocolIsProtocol:
    """验证 TargetConfigLayout 是 typing.Protocol。"""

    def test_is_protocol(self):
        from typing import _ProtocolMeta
        assert isinstance(TargetConfigLayout, _ProtocolMeta)


class TestNoneAdapter:
    def test_name_is_none(self):
        from cvekit.utils.config_layout.none_adapter import NoneAdapter

        adapter = NoneAdapter()
        assert adapter.name == "none"

    def test_detect_always_false(self):
        from cvekit.utils.config_layout.none_adapter import NoneAdapter

        adapter = NoneAdapter()
        assert adapter.detect("/any/path", "HEAD") is False

    def test_adapt_returns_source_unchanged(self):
        from cvekit.utils.config_layout.none_adapter import NoneAdapter

        adapter = NoneAdapter()
        source = "diff --git a/file b/file\n+code change\n"
        result = adapter.adapt(source, "/tmp", "HEAD")
        assert result.filtered_patch == source
        assert result.config_patches == ""
        assert result.unresolved == []
        assert result.handled_source_paths == []

    def test_adapt_ignores_options(self):
        from cvekit.utils.config_layout.none_adapter import NoneAdapter

        adapter = NoneAdapter()
        source = "some patch content"
        result = adapter.adapt(source, "/tmp", "HEAD", default_level="L2-OPTIONAL")
        assert result.filtered_patch == source
