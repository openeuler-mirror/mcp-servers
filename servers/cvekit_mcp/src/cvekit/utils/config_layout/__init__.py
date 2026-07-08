"""Target Config Layout -- 拆分配置适配器系统。

使用方式:
    from cvekit.utils.config_layout import get_registry

    registry = get_registry()
    adapter = registry.resolve("anolis")
    result = adapter.adapt(source_patch, repo_path, target_ref)
"""

from .protocol import (
    AdaptResult,
    TargetConfigLayout,
    TargetConfigLayoutError,
    ConfigError,
    LayoutError,
)
from .none_adapter import NoneAdapter
from .anolis_adapter import AnolisAdapter
from .registry import ConfigLayoutRegistry

__all__ = [
    "AdaptResult",
    "TargetConfigLayout",
    "TargetConfigLayoutError",
    "ConfigError",
    "LayoutError",
    "NoneAdapter",
    "AnolisAdapter",
    "ConfigLayoutRegistry",
    "get_registry",
]

_registry: ConfigLayoutRegistry | None = None


def get_registry() -> ConfigLayoutRegistry:
    """获取全局配置布局注册表（惰性初始化）。

    预注册 NoneAdapter 和 AnolisAdapter。
    """
    global _registry
    if _registry is None:
        _registry = ConfigLayoutRegistry()
        _registry.register(NoneAdapter())
        _registry.register(AnolisAdapter())
    return _registry
