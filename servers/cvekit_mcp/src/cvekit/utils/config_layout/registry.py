"""ConfigLayoutRegistry — 布局适配器注册表。"""
from .protocol import TargetConfigLayout, ConfigError


class ConfigLayoutRegistry:
    """布局适配器注册表。

    管理所有已注册的 TargetConfigLayout 实现，提供按名称查找和自动检测。
    """

    def __init__(self) -> None:
        self._adapters: dict[str, TargetConfigLayout] = {}

    def register(self, adapter: TargetConfigLayout) -> None:
        """注册一个布局适配器。同名 adapter 后注册的覆盖先注册的。"""
        self._adapters[adapter.name] = adapter

    def resolve(self, name: str) -> TargetConfigLayout:
        """按名称获取适配器。

        Raises:
            ConfigError: 名称未知或为空。
        """
        if not name or name not in self._adapters:
            raise ConfigError(
                f"未知的 target_config_layout: {name!r}，"
                f"可用值: {sorted(self._adapters.keys())}"
            )
        return self._adapters[name]

    def detect(self, repo_path: str, target_ref: str) -> str | None:
        """自动检测目标仓库使用的布局。

        遍历所有已注册的 adapter，调用其 detect() 方法。

        Returns:
            匹配的布局名称，零匹配返回 None。

        Raises:
            ConfigError: 多个 adapter 都声称匹配，无法确定。
        """
        matches = [
            name
            for name, adapter in self._adapters.items()
            if adapter.detect(repo_path, target_ref)
        ]
        if len(matches) > 1:
            raise ConfigError(
                f"多个布局匹配目标仓库: {matches}，请显式指定 --target-config-layout"
            )
        return matches[0] if matches else None
