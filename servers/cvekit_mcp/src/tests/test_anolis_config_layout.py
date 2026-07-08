"""测试 AnolisAdapter。"""
import subprocess
from pathlib import Path

import pytest

from cvekit.utils.config_layout.anolis_adapter import AnolisAdapter
from cvekit.utils.config_layout.protocol import LayoutError, AdaptResult


def _source_patch(config_line: str, arch: str = "arm64") -> str:
    return "\n".join(
        [
            f"diff --git a/arch/{arch}/configs/defconfig b/arch/{arch}/configs/defconfig",
            "index 1111111..2222222 100644",
            f"--- a/arch/{arch}/configs/defconfig",
            f"+++ b/arch/{arch}/configs/defconfig",
            "@@ -1 +1,2 @@",
            " CONFIG_BASE=y",
            f"+{config_line}",
            "",
        ]
    )


def _deletion_patch(config_line: str, arch: str = "arm64") -> str:
    return "\n".join(
        [
            f"diff --git a/arch/{arch}/configs/defconfig b/arch/{arch}/configs/defconfig",
            "index 1111111..2222222 100644",
            f"--- a/arch/{arch}/configs/defconfig",
            f"+++ b/arch/{arch}/configs/defconfig",
            "@@ -1,2 +1 @@",
            " CONFIG_BASE=y",
            f"-{config_line}",
            "",
        ]
    )


def _mixed_patch() -> str:
    return "\n".join(
        [
            "diff --git a/kernel/sched/core.c b/kernel/sched/core.c",
            "index abc..def 100644",
            "--- a/kernel/sched/core.c",
            "+++ b/kernel/sched/core.c",
            "@@ -100,6 +100,8 @@ void scheduler_function(void)",
            " int main(void) {",
            "+    int new_code = 1;",
            "     return 0;",
            " }",
            "",
            "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
            "index 111..222 100644",
            "--- a/arch/arm64/configs/defconfig",
            "+++ b/arch/arm64/configs/defconfig",
            "@@ -1 +1,2 @@",
            " CONFIG_BASE=y",
            "+CONFIG_NEW_FEATURE=y",
            "",
        ]
    )


def _init_target_repo(path: Path, files: dict[str, str]) -> str:
    """创建临时 git 仓库，files 是 {path: content} 映射。"""
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test"],
        check=True, capture_output=True,
    )
    for filepath, content in files.items():
        full = path / filepath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


class TestAnolisAdapterNewConfig:
    def test_creates_l1_arm64_config(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _source_patch("CONFIG_TEST_FEATURE=y"),
            str(repo_path),
            ref,
        )
        assert result.unresolved == []
        assert "CONFIG_TEST_FEATURE" in result.config_patches
        assert "anolis/configs/L1-RECOMMEND/arm64/CONFIG_TEST_FEATURE" in result.config_patches
        assert "new file mode 100644" in result.config_patches
        assert "+CONFIG_TEST_FEATURE=y" in result.config_patches
        assert result.handled_source_paths == ["arch/arm64/configs/defconfig"]

    def test_creates_with_custom_default_level(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _source_patch("CONFIG_FOO=m"),
            str(repo_path),
            ref,
            default_level="L2-OPTIONAL",
        )
        assert "anolis/configs/L2-OPTIONAL/arm64/CONFIG_FOO" in result.config_patches

    def test_int_hex_string_config_values(self, tmp_path: Path):
        """Kconfig int/hex/string values are correctly parsed and migrated."""
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        source_patch = "\n".join([
            "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
            "--- a/arch/arm64/configs/defconfig",
            "+++ b/arch/arm64/configs/defconfig",
            "@@ -1 +1,5 @@",
            " CONFIG_BASE=y",
            "+CONFIG_NR_CPUS=64",
            "+CONFIG_LOG_BUF_SHIFT=17",
            "+CONFIG_DEFAULT_MMAP_MIN_ADDR=0x10000",
            "+CONFIG_CMDLINE=\"console=ttyS0\"",
            "",
        ])
        result = adapter.adapt(source_patch, str(repo_path), ref)
        assert result.unresolved == []
        assert "CONFIG_NR_CPUS=64" in result.config_patches
        assert "CONFIG_LOG_BUF_SHIFT=17" in result.config_patches
        assert "CONFIG_DEFAULT_MMAP_MIN_ADDR=0x10000" in result.config_patches
        assert "CONFIG_CMDLINE=\"console=ttyS0\"" in result.config_patches

    def test_not_set_config(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _source_patch("# CONFIG_BAZ is not set"),
            str(repo_path),
            ref,
        )
        assert result.unresolved == []
        assert "# CONFIG_BAZ is not set" in result.config_patches


class TestAnolisAdapterUpdate:
    def test_updates_existing_config(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {
                "anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n",
                "anolis/configs/L2-OPTIONAL/arm64/CONFIG_EXISTING": "CONFIG_EXISTING=m\n",
            },
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _source_patch("CONFIG_EXISTING=y"),
            str(repo_path),
            ref,
        )
        assert result.unresolved == []
        assert "-CONFIG_EXISTING=m" in result.config_patches
        assert "+CONFIG_EXISTING=y" in result.config_patches

    def test_updates_config_in_default_dir(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {
                "anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n",
                "anolis/configs/L1-RECOMMEND/default/CONFIG_GLOBAL": "CONFIG_GLOBAL=n\n",
            },
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _source_patch("CONFIG_GLOBAL=y", arch="x86"),
            str(repo_path),
            ref,
        )
        assert result.unresolved == []
        assert "anolis/configs/L1-RECOMMEND/default/CONFIG_GLOBAL" in result.config_patches


class TestAnolisAdapterDelete:
    def test_deletes_existing_config(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {
                "anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n",
                "anolis/configs/L2-OPTIONAL/arm64/CONFIG_DEPRECATED": "CONFIG_DEPRECATED=y\n",
            },
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _deletion_patch("CONFIG_DEPRECATED=y"),
            str(repo_path),
            ref,
        )
        assert result.unresolved == []
        assert "anolis/configs/L2-OPTIONAL/arm64/CONFIG_DEPRECATED" in result.config_patches
        assert "deleted file mode" in result.config_patches
        assert "-CONFIG_DEPRECATED=y" in result.config_patches

    def test_delete_not_set_config(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {
                "anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n",
                "anolis/configs/L1-RECOMMEND/x86/CONFIG_DEPRECATED": "# CONFIG_DEPRECATED is not set\n",
            },
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(
            _deletion_patch("# CONFIG_DEPRECATED is not set", arch="x86"),
            str(repo_path),
            ref,
        )
        assert result.unresolved == []
        assert "anolis/configs/L1-RECOMMEND/x86/CONFIG_DEPRECATED" in result.config_patches
        assert "deleted file mode" in result.config_patches
        assert "-# CONFIG_DEPRECATED is not set" in result.config_patches


class TestAnolisAdapterMixedPatch:
    def test_strips_defconfig_from_filtered_patch(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        result = adapter.adapt(_mixed_patch(), str(repo_path), ref)
        # 代码文件保留在 filtered_patch 中
        assert "kernel/sched/core.c" in result.filtered_patch
        # defconfig 不在 filtered_patch 中
        assert "CONFIG_NEW_FEATURE" not in result.filtered_patch
        # 配置在 config_patches 中
        assert "CONFIG_NEW_FEATURE" in result.config_patches


class TestAnolisAdapterErrors:
    def test_missing_anolis_configs_raises(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"README.md": "# empty repo\n"},
        )
        adapter = AnolisAdapter()
        with pytest.raises(LayoutError, match="anolis/configs"):
            adapter.adapt(
                _source_patch("CONFIG_FOO=y"),
                str(repo_path),
                ref,
            )

    def test_unrecognized_config_line_skipped(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        patch = "\n".join(
            [
                "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
                "--- a/arch/arm64/configs/defconfig",
                "+++ b/arch/arm64/configs/defconfig",
                "@@ -1 +1,3 @@",
                " CONFIG_BASE=y",
                "+CONFIG_VALID=y",
                "+# not a valid config line",
                "",
            ]
        )
        result = adapter.adapt(patch, str(repo_path), ref)
        # 有效行被处理
        assert "CONFIG_VALID" in result.config_patches
        # 无效行被跳过（不引发异常）
        assert result.unresolved == []

    def test_no_defconfig_in_patch(self, tmp_path: Path):
        repo_path = tmp_path / "target"
        ref = _init_target_repo(
            repo_path,
            {"anolis/configs/L0-MANDATORY/default/CONFIG_BASE": "CONFIG_BASE=y\n"},
        )
        adapter = AnolisAdapter()
        code_only = "diff --git a/kernel/sched.c b/kernel/sched.c\n--- a/kernel/sched.c\n+++ b/kernel/sched.c\n@@ -1 +1,2 @@\n old\n+new\n"
        result = adapter.adapt(code_only, str(repo_path), ref)
        assert result.config_patches == ""
        assert result.filtered_patch == code_only
        assert result.handled_source_paths == []

    def test_unresolved_config_preserved_in_filtered_patch(self, tmp_path: Path):
        """Multi-candidate unresolved config stays in filtered_patch, not stripped."""
        repo_path = tmp_path / "target"
        # Create two candidates for the same (arch, CONFIG)
        subprocess.run(["git", "init", "-b", "main", str(repo_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "test@test"], check=True, capture_output=True)
        for path, content in [
            ("anolis/configs/L1-RECOMMEND/arm64/CONFIG_COLLIDE", "CONFIG_COLLIDE=m\n"),
            ("anolis/configs/L2-OPTIONAL/arm64/CONFIG_COLLIDE", "CONFIG_COLLIDE=y\n"),
        ]:
            full = repo_path / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "init"], check=True, capture_output=True)
        result_ref = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        # Also add a valid config that SHOULD be resolved
        (repo_path / "anolis/configs/L0-MANDATORY/default/CONFIG_BASE").parent.mkdir(parents=True, exist_ok=True)
        (repo_path / "anolis/configs/L0-MANDATORY/default/CONFIG_BASE").write_text("CONFIG_BASE=y\n")
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "add base"], check=True, capture_output=True)
        result_ref = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        adapter = AnolisAdapter()
        # Patch with one unresolved config AND one valid config
        source_patch = "\n".join([
            "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
            "--- a/arch/arm64/configs/defconfig",
            "+++ b/arch/arm64/configs/defconfig",
            "@@ -1 +1,3 @@",
            " CONFIG_BASE=y",
            "+CONFIG_COLLIDE=y",
            "+CONFIG_VALID_FEATURE=y",
            "",
        ])

        result = adapter.adapt(source_patch, str(repo_path), result_ref)

        # Unresolved config should be reported
        assert len(result.unresolved) == 1
        assert result.unresolved[0]["config"] == "CONFIG_COLLIDE"

        # No config_patches generated — file has unresolved changes, LLM handles everything
        assert result.config_patches == ""

        # handled_source_paths should NOT include the defconfig (because COLLIDE is unresolved)
        assert "arch/arm64/configs/defconfig" not in result.handled_source_paths

        # Both configs stay in filtered_patch — LLM handles the entire file
        assert "CONFIG_COLLIDE" in result.filtered_patch
        assert "CONFIG_VALID_FEATURE" in result.filtered_patch

    def test_unresolved_config_order_independent(self, tmp_path: Path):
        """Resolved config BEFORE unresolved — same result: no duplication."""
        repo_path = tmp_path / "target"
        # Create two candidates for the same (arch, CONFIG)
        subprocess.run(["git", "init", "-b", "main", str(repo_path)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "config", "user.name", "Test"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "config", "user.email", "test@test"], check=True, capture_output=True)
        for path, content in [
            ("anolis/configs/L1-RECOMMEND/arm64/CONFIG_COLLIDE", "CONFIG_COLLIDE=m\n"),
            ("anolis/configs/L2-OPTIONAL/arm64/CONFIG_COLLIDE", "CONFIG_COLLIDE=y\n"),
        ]:
            full = repo_path / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "init"], check=True, capture_output=True)

        # Also add a valid config that SHOULD be resolved
        (repo_path / "anolis/configs/L0-MANDATORY/default/CONFIG_BASE").parent.mkdir(parents=True, exist_ok=True)
        (repo_path / "anolis/configs/L0-MANDATORY/default/CONFIG_BASE").write_text("CONFIG_BASE=y\n")
        subprocess.run(["git", "-C", str(repo_path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo_path), "commit", "-m", "add base"], check=True, capture_output=True)
        result_ref = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

        adapter = AnolisAdapter()
        # Patch with valid config BEFORE unresolved config — this ordering
        # would cause config_patches duplication in a single-pass approach
        source_patch = "\n".join([
            "diff --git a/arch/arm64/configs/defconfig b/arch/arm64/configs/defconfig",
            "--- a/arch/arm64/configs/defconfig",
            "+++ b/arch/arm64/configs/defconfig",
            "@@ -1 +1,3 @@",
            " CONFIG_BASE=y",
            "+CONFIG_VALID_FEATURE=y",
            "+CONFIG_COLLIDE=y",
            "",
        ])

        result = adapter.adapt(source_patch, str(repo_path), result_ref)

        # Unresolved config should still be reported
        assert len(result.unresolved) == 1
        assert result.unresolved[0]["config"] == "CONFIG_COLLIDE"

        # No config_patches generated — file has unresolved changes despite
        # the resolved config appearing first in the patch
        assert result.config_patches == ""

        # handled_source_paths should NOT include the defconfig
        assert "arch/arm64/configs/defconfig" not in result.handled_source_paths

        # Both configs stay in filtered_patch — LLM handles the entire file
        assert "CONFIG_VALID_FEATURE" in result.filtered_patch
        assert "CONFIG_COLLIDE" in result.filtered_patch
