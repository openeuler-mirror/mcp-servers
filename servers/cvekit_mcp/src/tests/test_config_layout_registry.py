"""测试 ConfigLayoutRegistry。"""
import pytest
from cvekit.utils.config_layout.registry import ConfigLayoutRegistry
from cvekit.utils.config_layout.protocol import ConfigError, AdaptResult
from cvekit.utils.config_layout.none_adapter import NoneAdapter


class _FakeAdapter:
    def __init__(self, name, detect_result=False):
        self._name = name
        self._detect_result = detect_result
        self.adapt_called = False

    @property
    def name(self) -> str:
        return self._name

    def detect(self, repo_path: str, target_ref: str) -> bool:
        return self._detect_result

    def adapt(self, source_patch, repo_path, target_ref, **options):
        self.adapt_called = True
        return AdaptResult(filtered_patch=source_patch)


class TestRegistryResolve:
    def test_resolve_registered_name(self):
        registry = ConfigLayoutRegistry()
        registry.register(NoneAdapter())
        adapter = registry.resolve("none")
        assert adapter.name == "none"

    def test_resolve_unknown_name_raises(self):
        registry = ConfigLayoutRegistry()
        with pytest.raises(ConfigError, match="未知的 target_config_layout"):
            registry.resolve("unknown_layout")

    def test_resolve_empty_string_raises(self):
        registry = ConfigLayoutRegistry()
        with pytest.raises(ConfigError):
            registry.resolve("")

    def test_resolve_case_sensitive(self):
        registry = ConfigLayoutRegistry()
        registry.register(NoneAdapter())
        with pytest.raises(ConfigError):
            registry.resolve("NONE")


class TestRegistryDetect:
    def test_detect_one_match(self):
        registry = ConfigLayoutRegistry()
        adapter = _FakeAdapter("anolis", detect_result=True)
        registry.register(adapter)
        registry.register(_FakeAdapter("xxx", detect_result=False))
        result = registry.detect("/repo", "HEAD")
        assert result == "anolis"

    def test_detect_zero_matches(self):
        registry = ConfigLayoutRegistry()
        registry.register(_FakeAdapter("a", detect_result=False))
        registry.register(_FakeAdapter("b", detect_result=False))
        result = registry.detect("/repo", "HEAD")
        assert result is None

    def test_detect_multiple_matches_raises(self):
        registry = ConfigLayoutRegistry()
        registry.register(_FakeAdapter("a", detect_result=True))
        registry.register(_FakeAdapter("b", detect_result=True))
        with pytest.raises(ConfigError, match="多个布局匹配"):
            registry.detect("/repo", "HEAD")


class TestRegistryDuplicateRegistration:
    def test_duplicate_name_overwrites(self):
        registry = ConfigLayoutRegistry()
        a1 = _FakeAdapter("same")
        a2 = _FakeAdapter("same")
        registry.register(a1)
        registry.register(a2)
        # 后注册的覆盖先注册的
        assert registry.resolve("same") is a2
