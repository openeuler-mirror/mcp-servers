"""编排层集成测试 — target config layout 端到端流程。"""
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from cvekit.utils.config_layout import get_registry, AdaptResult
from cvekit.utils import backport_batch


class TestEndToEndAnolis:
    """端到端测试：从配置解析到适配器调用。"""

    def _make_target_repo(self, path: Path) -> str:
        subprocess.run(
            ["git", "init", "-b", "main", str(path)], check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(path), "config", "user.name", "Test"],
            check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(path), "config", "user.email", "test@test"],
            check=True, capture_output=True,
        )
        base_config = path / "anolis" / "configs" / "L0-MANDATORY" / "default"
        base_config.mkdir(parents=True)
        (base_config / "CONFIG_BASE").write_text("CONFIG_BASE=y\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(path), "add", "."], check=True, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(path), "commit", "-m", "init"],
            check=True, capture_output=True,
        )
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()

    def test_full_flow_resolve_and_adapt(self, tmp_path: Path):
        """完整流程：解析配置 → 获取 adapter → 调用 adapt → 得到结果。"""
        target_path = tmp_path / "target"
        ref = self._make_target_repo(target_path)

        # 模拟 backport-batch 的配置解析
        args = SimpleNamespace(target_config_layout="anolis", target_config_layout_opts="")
        item_config = {}
        base_config = {}

        layout_name = backport_batch._resolve_target_config_layout(args, item_config, base_config)
        opts = backport_batch._resolve_target_config_layout_opts(args, item_config, base_config)
        assert layout_name == "anolis"

        # 获取 adapter
        registry = get_registry()
        adapter = registry.resolve(layout_name)
        assert adapter.name == "anolis"

        # 构造测试 patch
        source_patch = "\n".join([
            "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
            "index 111..222 100644",
            "--- a/arch/arm64/configs/defconfig",
            "+++ b/arch/arm64/configs/defconfig",
            "@@ -1 +1,2 @@",
            " CONFIG_BASE=y",
            "+CONFIG_INTEGRATION_TEST=m",
            "",
        ])

        # 调用 adapter
        result = adapter.adapt(source_patch, str(target_path), ref, **opts)

        assert isinstance(result, AdaptResult)
        assert result.unresolved == []
        assert "CONFIG_INTEGRATION_TEST" in result.config_patches
        # 纯 defconfig patch 被完全剥离，filtered_patch 应为空
        assert result.filtered_patch == ""
        assert len(result.handled_source_paths) == 1

    def test_new_config_created_when_no_candidates(self, tmp_path: Path):
        """新的 CONFIG symbol（无候选文件）按 default_level 新建。"""
        target_path = tmp_path / "target"
        ref = self._make_target_repo(target_path)

        args = SimpleNamespace(target_config_layout="anolis", target_config_layout_opts="")
        layout_name = backport_batch._resolve_target_config_layout(args, {}, {})
        opts = backport_batch._resolve_target_config_layout_opts(args, {}, {})

        registry = get_registry()
        adapter = registry.resolve(layout_name)

        # 构造不会产生任何匹配的 patch（config symbol 在 anolis 中不存在，且使用新 arch）
        source_patch = "\n".join([
            "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
            "--- a/arch/arm64/configs/defconfig",
            "+++ b/arch/arm64/configs/defconfig",
            "@@ -1 +1,2 @@",
            " CONFIG_BASE=y",
            "+CONFIG_NEW_TEST_FEATURE=y",
            "",
        ])

        result = adapter.adapt(source_patch, str(target_path), ref, **opts)
        assert result.unresolved == []
        # 不存在所以新建
        assert "CONFIG_NEW_TEST_FEATURE" in result.config_patches
        assert "L1-RECOMMEND" in result.config_patches
