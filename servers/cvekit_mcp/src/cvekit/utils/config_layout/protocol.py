"""Target Config Layout 适配器协议与数据结构。"""
from dataclasses import dataclass, field
from typing import Protocol


class TargetConfigLayoutError(RuntimeError):
    """所有 target config layout 相关错误的基类。"""


class ConfigError(TargetConfigLayoutError):
    """配置错误 — 启动时 fail-fast。如未知 layout name、无效 option 值。"""


class LayoutError(TargetConfigLayoutError):
    """布局错误 — 适配过程中目标仓库不满足布局要求。"""


@dataclass
class AdaptResult:
    """适配器返回结果。

    适配器从源 patch 中剥离 defconfig 变更，生成目标布局的配置 patch。
    LLM 仅处理 filtered_patch（代码部分），config_patches 直接合并到最终结果。
    """

    filtered_patch: str = ""
    """剥离已处理 defconfig 后的源 patch。LLM 仅处理此部分。"""

    config_patches: str = ""
    """确定性生成的配置 patch（unified diff 格式）。直接合并到最终结果。"""

    unresolved: list[dict] = field(default_factory=list)
    """无法自动处理的项。
    每项包含: {source_file, arch, config, reason, candidates[]}
    """

    handled_source_paths: list[str] = field(default_factory=list)
    """已被适配器处理的源文件路径，用于日志和 report。"""

    def as_dict(self) -> dict[str, object]:
        return {
            "filtered_patch": self.filtered_patch,
            "config_patches": self.config_patches,
            "unresolved": list(self.unresolved),
            "handled_source_paths": list(self.handled_source_paths),
        }


class TargetConfigLayout(Protocol):
    """目标仓库配置文件布局适配器协议。

    每种 target config layout 实现此协议，通过 ConfigLayoutRegistry 注册。
    """

    @property
    def name(self) -> str:
        """布局名称，对应 --target-config-layout 参数值。如 'anolis'。"""
        ...

    def detect(self, repo_path: str, target_ref: str) -> bool:
        """自动检测目标仓库是否使用此布局。

        用于未来的 --target-config-layout=auto 模式。
        返回 True 表示仓库结构匹配此布局。
        """
        ...

    def adapt(
        self,
        source_patch: str,
        repo_path: str,
        target_ref: str,
        **options,
    ) -> AdaptResult:
        """将源 patch 中的 defconfig 变更适配到目标布局。

        Args:
            source_patch: 源补丁全文（unified diff 格式）。
            repo_path: 目标仓库本地路径。
            target_ref: 目标分支/commit ref。
            **options: adapter-specific 配置，如 default_level="L1-RECOMMEND"。

        Returns:
            AdaptResult 包含剥离后的 patch、确定性生成的配置 patch、未决项。
        """
        ...
