"""NoneAdapter — 默认适配器，保持原始 patch 不变。"""
from .protocol import AdaptResult, TargetConfigLayout


class NoneAdapter:
    """默认适配器：不处理任何 defconfig，原样返回源 patch。

    当 target_config_layout=none 或未配置时使用。
    """

    @property
    def name(self) -> str:
        return "none"

    def detect(self, repo_path: str, target_ref: str) -> bool:
        # NoneAdapter 不匹配任何仓库
        return False

    def adapt(
        self,
        source_patch: str,
        repo_path: str,
        target_ref: str,
        **options,
    ) -> AdaptResult:
        return AdaptResult(
            filtered_patch=source_patch,
            config_patches="",
            unresolved=[],
            handled_source_paths=[],
        )
