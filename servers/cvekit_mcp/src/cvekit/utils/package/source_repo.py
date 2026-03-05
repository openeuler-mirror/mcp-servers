import logging
import git
import os
import shutil
import re
from typing import Optional

logger = logging.getLogger(__name__)

def _spec_version_from_ref(repo: git.Repo, repo_name: str, ref_name: str) -> Optional[str]:
    """从指定 Git 引用读取 spec 并解析 Version，失败返回 None。"""
    spec_candidates = []
    if repo_name:
        spec_candidates.extend(
            [
                f"{repo_name}.spec",
                f"SPECS/{repo_name}.spec",
            ]
        )
    # 兜底：遍历分支内所有 spec 文件
    if not spec_candidates:
        tree_files = repo.git.ls_tree("-r", "--name-only", ref_name).splitlines()
        spec_candidates.extend([p for p in tree_files if p.endswith(".spec")])
    seen = set()
    for spec_path in spec_candidates:
        if spec_path in seen:
            continue
        seen.add(spec_path)
        try:
            spec_text = repo.git.show(f"{ref_name}:{spec_path}")
        except git.exc.GitCommandError:
            continue
        for line in spec_text.splitlines():
            if line.strip().startswith("Version:"):
                return line.split(":", 1)[1].strip()
    return None

def get_spec_version_from_branch(repo: git.Repo, branch_name: str, repo_name: str = "") -> Optional[str]:
    """读取指定分支的 spec 文件中的 Version 值。

    Args:
        repo: Git 仓库对象
        branch_name: 目标分支名
        repo_name: 可选仓库名，用于优先匹配 {repo_name}.spec
    """

    try:
        # 先尝试本地分支/标签名，再回退到远程分支引用。
        version = _spec_version_from_ref(repo, repo_name, branch_name)
        if version is not None:
            return version
        origin_ref = f"remotes/origin/{branch_name}"
        return _spec_version_from_ref(repo, repo_name, origin_ref)
    except Exception as exc:
        logger.warning("读取分支 %s 的 spec 版本失败: %s", branch_name, exc)
    return None

def sync_rpmbuild_to_repo(rpmbuild_path: str, repo_path: str, rpm_name: str) -> None:
    """
    同步 rpmbuild 目录中的 新增patch 文件和 更新后的spec 文件到目标仓库。

    Args:
        rpmbuild_path: rpmbuild 目录路径
        repo_path: 目标仓库路径
        rpm_name: rpm 包名
    """
    if not rpmbuild_path or not repo_path or not rpm_name:
        logger.info("Skip sync: missing rpmbuild_path/repo_path/rpm_name")
        return
    rpmbuild_path = os.path.expanduser(rpmbuild_path)
    specs_src = os.path.join(rpmbuild_path, "SPECS")
    sources_src = os.path.join(rpmbuild_path, "SOURCES")

    if not os.path.isdir(repo_path):
        logger.info("Skip sync: repo path not found: %s", repo_path)
        return

    spec_file = os.path.join(specs_src, f"{rpm_name}.spec")
    if os.path.isfile(spec_file):
        shutil.copy2(spec_file, repo_path)
    else:
        logger.info("Spec file not found: %s", spec_file)

    spec_in_sources = os.path.join(sources_src, f"{rpm_name}.spec")
    spec_bak = os.path.join(sources_src, f"{rpm_name}.spec.bak")
    new_patch_names = _get_added_patch_names(spec_in_sources, spec_bak)
    if not new_patch_names and os.path.isfile(spec_in_sources):
        new_patch_names = _get_patch_names(spec_in_sources)

    patch_files = []
    for patch_name in new_patch_names:
        patch_name = os.path.basename(patch_name)
        if not patch_name or patch_name == "." or patch_name == "..":
            continue
        patch_files.append(os.path.join(sources_src, patch_name))

    if patch_files:
        for patch_file in patch_files:
            if os.path.isfile(patch_file):
                dst_path = os.path.join(repo_path, os.path.basename(patch_file))
                if os.path.exists(dst_path):
                    continue
                shutil.copy2(patch_file, repo_path)
    else:
        raise ValueError(f"No patch files found under {sources_src}")

def _get_added_patch_names(spec_path: str, spec_bak_path: str) -> list:
    if not os.path.isfile(spec_path) or not os.path.isfile(spec_bak_path):
        return []
    current = set(_get_patch_names(spec_path))
    previous = set(_get_patch_names(spec_bak_path))
    return sorted(current - previous)

def _get_patch_names(spec_path: str) -> list:
    patch_names = []
    try:
        with open(spec_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                match = re.match(r"^\s*Patch\d*\s*:\s*(\S+)", line)
                if match:
                    patch_names.append(match.group(1).strip())
    except Exception as exc:
        logger.info("Failed to parse spec patches: %s, error: %s", spec_path, exc)
    return patch_names
