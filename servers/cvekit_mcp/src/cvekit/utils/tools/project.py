"""
This file is based on the project \"patch-backporting\":
  https://github.com/OS3Lab/patch-backporting
The original code is licensed under the MIT License.
See third_party/patch-backporting/LICENSE for the full license text.

本文件在 OS3Lab/patch-backporting 项目的基础上进行了修改，以适配 CVEKit 的自动回移植流程。

Modifications for CVEKit MCP backport workflow:
  Copyright (c) 2025 CVEKit contributors
  Licensed under the Mulan PSL v2.
"""

import os
import re
import shutil
import subprocess
import tempfile
import time
import warnings
from collections import OrderedDict
from types import SimpleNamespace
from typing import Any, List, Tuple

import Levenshtein
from git import Repo
from git.exc import GitCommandError
from langchain_core.tools import StructuredTool, tool

from . import utils
from .logger import logger

# 抑制 GitPython 关于大量活动更改的警告
warnings.filterwarnings('ignore', message='.*too many active changes.*', category=UserWarning)


def _wait_for_index_lock_release(index_lock, max_wait=30):
    """
    等待 index.lock 释放，必要时清理过期锁文件。
    返回 True 表示锁已释放/不存在，False 表示超时仍存在。
    """
    start = time.time()
    delay = 1
    while os.path.exists(index_lock):
        # 检查锁文件是否过期（超过5分钟认为是过期）
        lock_age = time.time() - os.path.getmtime(index_lock)
        if lock_age > 300:  # 5分钟
            logger.warning(f"发现过期的 index.lock 文件（已存在 {lock_age:.0f} 秒），正在删除...")
            try:
                os.remove(index_lock)
                logger.info("已删除过期的 index.lock 文件")
                return True
            except OSError as e:
                logger.warning(f"删除 index.lock 文件失败: {e}")
        elapsed = time.time() - start
        if elapsed >= max_wait:
            return False
        logger.warning(f"发现 index.lock 文件（存在 {lock_age:.0f} 秒），等待后重试...")
        time.sleep(delay)
        delay = min(delay * 2, 5)
    return True


def cleanup_git_in_progress_state(repo):
    """
    清理仓库中可能残留的 in-progress 状态（am/rebase/merge/cherry-pick）。
    该函数幂等：没有进行中操作时会跳过，不抛异常。
    """
    abort_steps = [
        ("am", lambda: repo.git.am("--abort")),
        ("rebase", lambda: repo.git.rebase("--abort")),
        ("merge", lambda: repo.git.merge("--abort")),
        ("cherry-pick", lambda: repo.git.cherry_pick("--abort")),
    ]
    for name, action in abort_steps:
        try:
            action()
            logger.info("cleanup_git_in_progress_state: 已执行 %s --abort", name)
        except Exception as e:
            logger.debug(
                "cleanup_git_in_progress_state: %s --abort 跳过/失败（通常可忽略）: %s",
                name,
                e,
            )

    # 兜底处理：若历史异常中断导致控制目录残留，尝试清理 rebase 目录
    try:
        git_dir = repo.git.rev_parse("--git-dir").strip()
        if not os.path.isabs(git_dir):
            git_dir = os.path.join(repo.working_tree_dir, git_dir)
        for d in ("rebase-apply", "rebase-merge"):
            stale_path = os.path.join(git_dir, d)
            if os.path.isdir(stale_path):
                logger.warning(
                    "cleanup_git_in_progress_state: 检测到残留目录 %s，尝试删除",
                    stale_path,
                )
                shutil.rmtree(stale_path, ignore_errors=False)
                logger.info(
                    "cleanup_git_in_progress_state: 已删除残留目录 %s",
                    stale_path,
                )
    except Exception as e:
        logger.warning(
            "cleanup_git_in_progress_state: 兜底清理残留 rebase 目录失败: %s",
            e,
        )


def safe_git_reset_hard(repo, max_retries=3, retry_delay=1, cleanup_in_progress=False):
    """
    安全地执行 git reset --hard，自动处理 index.lock 文件问题
    
    Args:
        repo: GitPython Repo 对象
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
        cleanup_in_progress: 是否在 reset 前清理 am/rebase 等中间状态
    
    Raises:
        GitCommandError: 如果所有重试都失败
    """
    for attempt in range(max_retries):
        try:
            if cleanup_in_progress:
                cleanup_git_in_progress_state(repo)
            # 在执行 reset 前，检查并清理锁文件
            git_dir = repo.git_dir
            index_lock = os.path.join(git_dir, 'index.lock')
            if os.path.exists(index_lock):
                # 等待锁释放（可通过环境变量调大）
                max_wait = int(os.getenv("CVEKIT_GIT_LOCK_WAIT", "30"))
                if not _wait_for_index_lock_release(index_lock, max_wait=max_wait):
                    logger.error(
                        f"index.lock 在 {max_wait}s 内未释放，"
                        "可能仍有 git 进程占用"
                    )
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay * (attempt + 1))
                        continue
            
            # 执行 reset
            repo.git.reset("--hard")
            return
        except GitCommandError as e:
            error_msg = str(e)
            if 'index.lock' in error_msg or 'File exists' in error_msg:
                if attempt < max_retries - 1:
                    logger.warning(f"git reset --hard 失败（尝试 {attempt + 1}/{max_retries}）: {error_msg}")
                    # 尝试删除锁文件
                    git_dir = repo.git_dir
                    index_lock = os.path.join(git_dir, 'index.lock')
                    if os.path.exists(index_lock):
                        try:
                            os.remove(index_lock)
                            logger.info("已删除 index.lock 文件，准备重试")
                        except OSError:
                            pass
                    time.sleep(retry_delay * (attempt + 1))
                    continue
                else:
                    logger.error(f"git reset --hard 失败，已重试 {max_retries} 次: {error_msg}")
                    raise
            else:
                # 其他类型的错误，直接抛出
                raise


class Project:
    def __init__(self, data: SimpleNamespace):
        self.project_url = data.project_url
        self.dir = data.project_dir
        # 使用 odbt=GitCmdObjectDB 来避免大量活动更改的警告
        try:
            from git.db import GitCmdObjectDB
            self.repo = Repo(data.project_dir, odbt=GitCmdObjectDB)
        except (ImportError, AttributeError):
            # 如果 GitCmdObjectDB 不可用，使用默认方式（警告已被 warnings.filterwarnings 抑制）
            self.repo = Repo(data.project_dir)

        # 目标仓库配置（如果指定了 target_path）
        if hasattr(data, 'target_path') and data.target_path:
            self.target_dir = data.target_path
            try:
                from git.db import GitCmdObjectDB
                self.target_repo = Repo(data.target_path, odbt=GitCmdObjectDB)
            except (ImportError, AttributeError):
                self.target_repo = Repo(data.target_path)
            logger.debug(f"[Project.__init__] 使用独立的目标仓库: {self.target_dir}")
            logger.debug(f"  - 源仓库: {self.dir}")
            logger.debug(f"  - 目标仓库: {self.target_dir}")
        else:
            # 如果未指定 target_path，使用源仓库作为目标仓库（向后兼容）
            self.target_dir = data.project_dir
            self.target_repo = self.repo
            logger.debug(f"[Project.__init__] 使用源仓库作为目标仓库: {self.target_dir}")

        if not data.error_message:
            self.err_msg = "no err_msg"
        else:
            self.err_msg = data.error_message

        self.new_patch_parent = data.new_patch_parent
        self.target_release = data.target_release
        self.succeeded_patches = []
        # key=(file_path, old_start, old_count), value=latest patch chunk text
        self.succeeded_patch_map = OrderedDict()
        self.context_mismatch_times = 0
        self.round_succeeded = False
        self.all_hunks_applied_succeeded = False
        self.compile_succeeded = False
        self.testcase_succeeded = False
        self.poc_succeeded = False
        self.symbol_map = {}
        self.source_symbol_map = {}
        self.now_hunk = ""
        self.now_hunk_num = 0
        self.hunk_log_info = {}
        self.add_percent = 0
        self.last_context = []
        self.validated_patch = None
        self.last_success_revised_patch = ""
        # Only allow "need not ported" when equivalence is explicitly proven.
        self.equivalent_exists = bool(getattr(data, "equivalent_exists", False))
        self.equivalent_file_keys: set[str] = set()
        self.current_file_equivalent = False
        self.active_file_key = ""

    def _extract_hunk_identity(
        self, patch_chunk: str
    ) -> tuple[str, int, int] | None:
        """
        Build a stable identity for a patch chunk:
        (file_path, old_start, old_count).

        Why not include new_start/new_count?
        During iterative revision, the same logical hunk may be regenerated with
        slightly different `+` line ranges while still targeting the same old
        location. If we include new ranges in identity, stale and latest variants
        can coexist and produce duplicate/conflicting hunks in exported patches.

        For new-file hunks (`--- /dev/null`), use the `+++ b/...` path as identity
        so multiple new files do not overwrite each other.
        """
        if not patch_chunk:
            return None
        old_file_path = None
        new_file_path = None
        old_start = None
        old_count = None
        new_start = None
        new_count = None
        for line in patch_chunk.splitlines():
            if line.startswith("--- "):
                # e.g. --- a/path/to/file
                old_file_path = line[4:].strip()
                if old_file_path.startswith("a/"):
                    old_file_path = old_file_path[2:]
            elif line.startswith("+++ "):
                # e.g. +++ b/path/to/file
                new_file_path = line[4:].strip()
                if new_file_path.startswith("b/"):
                    new_file_path = new_file_path[2:]
            elif line.startswith("@@"):
                m = re.search(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
                if m:
                    old_start = int(m.group(1))
                    old_count = int(m.group(2) or "1")
                    new_start = int(m.group(3))
                    new_count = int(m.group(4) or "1")
                    break
        file_path = old_file_path
        if old_file_path in (None, "/dev/null"):
            file_path = new_file_path

        if (
            file_path is None
            or old_start is None
            or old_count is None
            or new_start is None
            or new_count is None
        ):
            return None
        return (file_path, old_start, old_count)

    def _sync_succeeded_patches_from_map(self) -> None:
        self.succeeded_patches = list(self.succeeded_patch_map.values())

    def _upsert_succeeded_patch(self, revised_patch: str) -> None:
        """
        Upsert successful patch chunks by identity instead of blindly appending.
        """
        identities = list(utils.split_patch(revised_patch, False))
        if not identities:
            # Non-standard patch text fallback
            key = (f"raw:{hash(revised_patch)}", 0, 0)
            self.succeeded_patch_map[key] = revised_patch
            self._sync_succeeded_patches_from_map()
            return

        for chunk in identities:
            identity = self._extract_hunk_identity(chunk)
            if identity is None:
                identity = (f"raw:{hash(chunk)}", 0, 0)
            self.succeeded_patch_map[identity] = chunk
        self._sync_succeeded_patches_from_map()

    def rebuild_complete_patch(self) -> str:
        """
        Build complete patch from deduplicated successful chunks.
        """
        if self.succeeded_patch_map:
            # Secondary de-dup guard: if historical data contains mixed key shapes
            # (from older runtime states), normalize again by current identity.
            normalized = OrderedDict()
            for chunk in self.succeeded_patch_map.values():
                identity = self._extract_hunk_identity(chunk)
                if identity is None:
                    identity = (f"raw:{hash(chunk)}", 0, 0)
                normalized[identity] = chunk
            return "\n".join(normalized.values())
        return "\n".join(self.succeeded_patches)

    def _set_complete_patch_as_single_result(self, complete_patch: str) -> None:
        """
        Replace all staged successful chunks with final validated complete patch.
        """
        self.succeeded_patch_map.clear()
        if complete_patch:
            self.succeeded_patch_map[("__complete_patch__", 0, 0)] = complete_patch
        self._sync_succeeded_patches_from_map()

    def set_succeeded_patches(self, patches: list[str]) -> None:
        """
        Replace current successful patch set with ordered patch chunks.

        Used by higher-level file-freeze flow to keep only validated file patches.
        """
        self.succeeded_patch_map.clear()
        for patch in patches or []:
            if not patch:
                continue
            self._upsert_succeeded_patch(patch)
        self._sync_succeeded_patches_from_map()

    def build_succeeded_patch_for_file(self, file_path: str) -> str:
        """
        Build a normalized patch that contains all successful hunks of one file.
        """
        if not file_path:
            return ""

        file_chunks = []
        for chunk in self.succeeded_patch_map.values():
            chunk_path = self._extract_patch_target_path(chunk)
            if chunk_path == file_path:
                file_chunks.append(chunk)

        if not file_chunks:
            return ""

        header_a = ""
        header_b = ""
        hunk_bodies = []
        for chunk in file_chunks:
            lines = chunk.splitlines()
            if len(lines) < 3:
                continue
            if not header_a:
                header_a = lines[0]
                header_b = lines[1]
            hunk_start = -1
            for idx, line in enumerate(lines):
                if line.startswith("@@"):
                    hunk_start = idx
                    break
            if hunk_start >= 0:
                hunk_bodies.append("\n".join(lines[hunk_start:]))

        if not header_a or not header_b or not hunk_bodies:
            return ""
        return f"{header_a}\n{header_b}\n" + "\n".join(hunk_bodies) + "\n"

    def normalize_patch(self, patch_text: str) -> str:
        """
        Trim non-diff metadata and keep unified diff body from file headers.
        """
        if not patch_text:
            return ""
        lines = patch_text.splitlines()
        start_idx = -1
        for idx, line in enumerate(lines):
            if line.startswith("--- a/") or line.startswith("--- /dev/null"):
                start_idx = idx
                break
        if start_idx < 0:
            return ""
        normalized = "\n".join(lines[start_idx:])
        if normalized and not normalized.endswith("\n"):
            normalized += "\n"
        return normalized

    def extract_grouped_file_patches(self, patch_text: str) -> list[tuple[str, str]]:
        """
        Extract and group patch content by file path, then merge hunks per file.
        """
        normalized = self.normalize_patch(patch_text)
        if not normalized:
            return []

        def _sanitize_block(raw_lines: list[str]) -> str:
            """
            Remove trailing next-file metadata accidentally attached to current block.
            """
            if not raw_lines:
                return ""
            cut = len(raw_lines)
            for i, line in enumerate(raw_lines):
                if line.startswith("diff --git "):
                    cut = i
                    break
                # Fallback: some malformed outputs may only leak `index ...`.
                if line.startswith("index "):
                    cut = i
                    break
            block = "\n".join(raw_lines[:cut]).strip()
            return (block + "\n") if block else ""

        lines = normalized.splitlines()
        file_blocks: list[str] = []
        start = -1
        for idx, line in enumerate(lines):
            if line.startswith("diff --git "):
                if start >= 0:
                    block = _sanitize_block(lines[start:idx])
                    if block:
                        file_blocks.append(block)
                start = -1
                continue
            if line.startswith("--- a/") or line.startswith("--- /dev/null"):
                if start >= 0:
                    block = _sanitize_block(lines[start:idx])
                    if block:
                        file_blocks.append(block)
                start = idx
        if start >= 0:
            block = _sanitize_block(lines[start:])
            if block:
                file_blocks.append(block)

        grouped_files: list[list[Any]] = []
        grouped_index: dict[str, int] = {}
        for raw_idx, block in enumerate(file_blocks):
            key = self._extract_patch_target_path(block) or f"__raw_block_{raw_idx}__"
            if key.startswith("__raw_block_"):
                logger.warning(
                    "[Project.extract_grouped_file_patches] 文件路径解析失败，使用占位 key 保留该块: %s",
                    key,
                )
            if key not in grouped_index:
                grouped_index[key] = len(grouped_files)
                grouped_files.append([key, []])
            grouped_files[grouped_index[key]][1].append(block)

        file_patches: list[tuple[str, str]] = []
        for key, blocks in grouped_files:
            header_a = ""
            header_b = ""
            body_parts = []
            header_written = False
            for block in blocks:
                b_lines = block.splitlines()
                if len(b_lines) < 3:
                    continue
                if not header_written:
                    header_a = b_lines[0]
                    header_b = b_lines[1]
                    header_written = True
                hunk_start = -1
                for idx, line in enumerate(b_lines):
                    if line.startswith("@@"):
                        hunk_start = idx
                        break
                if hunk_start >= 0:
                    body_parts.append("\n".join(b_lines[hunk_start:]))
            if header_written and body_parts:
                file_patch = f"{header_a}\n{header_b}\n" + "\n".join(body_parts) + "\n"
                file_patches.append((key, file_patch))
        return file_patches

    def check_patch_chunks_accumulate(
        self, patch_chunks: list[str], target_release: str
    ) -> tuple[bool, str]:
        """
        Apply patch chunks cumulatively in a temp worktree to catch combo conflicts.
        """
        if not patch_chunks:
            return True, ""

        try:
            resolved_ref = self._resolve_target_ref(target_release)
            wt_dir = tempfile.mkdtemp(prefix="cvekit-wt-")
            try:
                self.target_repo.git.worktree("add", "--detach", wt_dir, resolved_ref)
                for idx, chunk in enumerate(patch_chunks):
                    with tempfile.NamedTemporaryFile(mode="w", delete=False) as pf:
                        pf.write(chunk if chunk.endswith("\n") else chunk + "\n")
                        patch_file = pf.name
                    try:
                        self.target_repo.git.execute(
                            ["git", "-C", wt_dir, "apply", "--check", patch_file]
                        )
                        self.target_repo.git.execute(
                            ["git", "-C", wt_dir, "apply", patch_file]
                        )
                    except Exception as e:
                        return False, f"accumulate_apply_failed_at_chunk={idx}, err={e}"
                    finally:
                        try:
                            os.remove(patch_file)
                        except Exception:
                            pass
                return True, ""
            finally:
                try:
                    self.target_repo.git.worktree("remove", "--force", wt_dir)
                except Exception:
                    pass
                try:
                    self.target_repo.git.worktree("prune")
                except Exception:
                    pass
                try:
                    shutil.rmtree(wt_dir, ignore_errors=True)
                except Exception:
                    pass
        except Exception as e:
            return False, f"temp_worktree_check_failed: {e}"

    def apply_file_patches_with_freeze(
        self,
        target_release: str,
        project_url: str,
        new_patch_parent: str,
        file_patches: list[tuple[str, str]],
        agent_executor: Any,
        log_handler: Any,
        patch_dataset_dir: str | None = None,
    ) -> tuple[bool, str]:
        """
        Process file patches with freeze strategy and cumulative conflict checks.
        """
        logger.debug(
            "[Project.apply_file_patches_with_freeze] 开始文件级冻结流程, 文件数=%s",
            len(file_patches),
        )
        frozen_file_patches: list[str] = []
        expected_file_keys = [k for k, _ in file_patches]
        frozen_file_keys: list[str] = []
        retained_expected_file_keys: list[str] = []

        for file_idx, (file_key, file_patch) in enumerate(file_patches):
            logger.debug(
                "[Project.apply_file_patches_with_freeze] 处理文件补丁 %s/%s: %s",
                file_idx,
                max(len(file_patches) - 1, 0),
                file_key,
            )
            self.round_succeeded = False
            self.context_mismatch_times = 0
            self.current_file_equivalent = False
            self.active_file_key = file_key
            self.set_succeeded_patches(frozen_file_patches)

            ret = self._apply_hunk(target_release, file_patch, False)
            if not self.round_succeeded:
                block_list = re.findall(r"older version.\n(.*?)\nBesides,", ret, re.DOTALL)
                similar_block = "\n".join(block_list)
                self.now_hunk = file_patch
                self.now_hunk_num = file_idx
                invoke_input = {
                    "project_url": project_url,
                    "new_patch_parent": new_patch_parent,
                    "new_patch": file_patch,
                    "target_release": target_release,
                    "similar_block": similar_block,
                }
                agent_executor.invoke(invoke_input, {"callbacks": [log_handler]})

            if not self.round_succeeded:
                logger.error(
                    "[Project.apply_file_patches_with_freeze] 文件补丁 %s 达到最大迭代次数",
                    file_key,
                )
                return False, ""

            if self.current_file_equivalent:
                frozen_file_keys.append(file_key)
                logger.info(
                    "[Project.apply_file_patches_with_freeze] 文件补丁 %s 判定为等效存在，跳过导出该文件补丁",
                    file_key,
                )
                self.active_file_key = ""
                continue

            # 优先冻结“本轮真正成功 apply 的 revised_patch”（包含可能的重命名路径修复结果）。
            frozen_patch = self.last_success_revised_patch or self.build_succeeded_patch_for_file(file_key) or file_patch
            # 关闭文件级“累积预检查”。
            # 该检查在多场景下会误判失败，统一由末尾全量 _check_patch 作为唯一 gate。

            frozen_file_patches.append(frozen_patch)
            frozen_file_keys.append(file_key)
            retained_expected_file_keys.append(file_key)
            self.set_succeeded_patches(frozen_file_patches)
            self.active_file_key = ""

        missing_keys = sorted(set(expected_file_keys) - set(frozen_file_keys))
        if missing_keys:
            logger.error(
                "[Project.apply_file_patches_with_freeze] 文件级处理存在缺失文件，缺失 keys=%s",
                missing_keys,
            )
            self.set_succeeded_patches([])
            self.validated_patch = ""
            return False, ""

        complete_patch = ""
        while frozen_file_patches:
            candidate_patch = "\n".join(frozen_file_patches)
            try:
                self._check_patch(candidate_patch, target_release)
                complete_patch = candidate_patch
                break
            except Exception as e:
                removed = frozen_file_patches.pop()
                if retained_expected_file_keys:
                    retained_expected_file_keys.pop()
                logger.warning(
                    "[Project.apply_file_patches_with_freeze] 全量 git apply --check 失败，回滚最后新增文件。"
                    " 剩余冻结数=%s; error=%s",
                    len(frozen_file_patches),
                    e,
                )
                logger.debug(
                    "[Project.apply_file_patches_with_freeze] 已回滚补丁长度: %s",
                    len(removed),
                )

        if not frozen_file_patches:
            if set(expected_file_keys).issubset(self.equivalent_file_keys):
                self.set_succeeded_patches([])
                self.validated_patch = ""
                self.equivalent_exists = True
                self.all_hunks_applied_succeeded = True
                self.now_hunk = "completed"
                self.active_file_key = ""
                self.current_file_equivalent = False
                logger.info(
                    "[Project.apply_file_patches_with_freeze] 所有文件均判定为等效存在，无需导出补丁"
                )
                return True, "need not ported"
            self.set_succeeded_patches([])
            self.validated_patch = ""
            logger.error("[Project.apply_file_patches_with_freeze] 全量检查后无可用冻结补丁")
            return False, ""

        missing_after_full_check = sorted(
            set(expected_file_keys)
            - (set(retained_expected_file_keys) | set(self.equivalent_file_keys))
        )
        if missing_after_full_check:
            logger.error(
                "[Project.apply_file_patches_with_freeze] 全量检查通过前丢失文件，拒绝返回不完整补丁。"
                " 缺失 keys=%s",
                missing_after_full_check,
            )
            self.set_succeeded_patches([])
            self.validated_patch = ""
            return False, ""

        self.set_succeeded_patches(frozen_file_patches)
        self.all_hunks_applied_succeeded = True
        self.now_hunk = "completed"
        self.active_file_key = ""
        self.current_file_equivalent = False
        logger.info("[Project.apply_file_patches_with_freeze] 文件级冻结流程完成")
        return True, complete_patch

    def _is_unified_diff_patch(self, patch: str) -> bool:
        """
        Check whether text looks like a unified diff patch.
        """
        if not patch or not patch.strip():
            return False
        return (
            any(marker in patch for marker in ("diff --git ", "\n--- ", "\n+++ ", "\n@@ "))
            or patch.startswith(("diff --git ", "--- ", "+++ ", "@@ "))
        )

    def _extract_patch_target_path(self, patch_text: str) -> str:
        """
        Extract target path from unified diff.
        For new-file patches (`--- /dev/null`), fallback to `+++ b/...`.
        """
        old_paths = re.findall(r"^--- a/(.*)$", patch_text, flags=re.MULTILINE)
        if old_paths:
            return old_paths[0]
        new_paths = re.findall(r"^\+\+\+ b/(.*)$", patch_text, flags=re.MULTILINE)
        if new_paths:
            return new_paths[0]
        return ""

    def _resolve_target_ref(self, ref: str, strict: bool = False) -> str:
        """
        Resolve a ref to a valid commit in the target repository.

        In cross-repo scenarios, the provided ref may belong to the source repo
        (e.g., new_patch_parent). If the ref does not exist in target repo,
        fallback to target_release, then HEAD.

        Args:
            ref (str): ref to resolve.
            strict (bool): if True, do not fallback when ref is unknown in
                target repo; raise ValueError with guidance instead.
        """
        if not ref:
            return self.target_repo.head.commit.hexsha
        try:
            self.target_repo.commit(ref)
            return ref
        except Exception:
            in_source_repo = False
            if hasattr(self, "repo") and self.repo is not self.target_repo:
                try:
                    self.repo.commit(ref)
                    in_source_repo = True
                except Exception:
                    in_source_repo = False

            if strict:
                if in_source_repo:
                    raise ValueError(
                        f"ref {ref} exists in source repo but not in target repo; "
                        f"use target_release {getattr(self, 'target_release', 'HEAD')} "
                        "for viewcode/locate_symbol/validate in cross-repo backport."
                    )
                raise ValueError(
                    f"ref {ref} not found in target repo; "
                    f"use target_release {getattr(self, 'target_release', 'HEAD')}."
                )

            # Fallback to target_release if it exists in target repo
            if getattr(self, "target_release", None):
                try:
                    self.target_repo.commit(self.target_release)
                    logger.debug(
                        f"[_resolve_target_ref] ref {ref} not in target repo, "
                        f"fallback to target_release {self.target_release}"
                    )
                    return self.target_release
                except Exception:
                    pass
            # Final fallback to HEAD
            head_ref = self.target_repo.head.commit.hexsha
            logger.debug(
                f"[_resolve_target_ref] ref {ref} not in target repo, "
                f"fallback to HEAD {head_ref[:8]}"
            )
            return head_ref

    def _resolve_source_ref(self, ref: str, strict: bool = False) -> str:
        """
        Resolve a ref to a valid commit in the source repository.
        """
        if not ref:
            return self.repo.head.commit.hexsha
        try:
            self.repo.commit(ref)
            return ref
        except Exception:
            if strict:
                raise ValueError(f"ref {ref} not found in source repo.")
            head_ref = self.repo.head.commit.hexsha
            logger.debug(
                f"[_resolve_source_ref] ref {ref} not in source repo, "
                f"fallback to HEAD {head_ref[:8]}"
            )
            return head_ref

    def _checkout(self, ref: str, use_target_repo: bool = False) -> None:
        """
        切换到指定的引用（commit 或分支）。
        
        Args:
            ref (str): 要切换到的引用（commit ID 或分支名）
            use_target_repo (bool): 如果为 True，操作目标仓库；否则操作源仓库
        """
        repo = self.target_repo if use_target_repo else self.repo
        safe_git_reset_hard(repo)
        repo.git.checkout(ref)

    def _get_patch(self, ref: str) -> str:
        try:
            return self.repo.git.show(f"{ref}^..{ref}")
        except:
            return "Error commit id, please check if the commit id is correct."

    def _prepare(self, ref: str, use_target_repo: bool = True) -> None:
        """
        Prepares the project by generating a symbol map using ctags.
        
        优化：只扫描 C/C++ 源文件，大幅减少扫描时间。

        Raises:
            subprocess.CalledProcessError: If the ctags command fails.
        """
        symbol_map = self.symbol_map if use_target_repo else self.source_symbol_map
        repo_dir = self.target_dir if use_target_repo else self.dir

        # 优化：只扫描 C/C++ 源文件，避免扫描文档、配置文件等
        # 对于 Linux 内核等大型项目，这可以节省大量时间
        with tempfile.NamedTemporaryFile(prefix="ctags-", suffix=".tags", delete=False) as f:
            tags_path = f.name
        try:
            ctags = subprocess.run(
                [
                    "ctags",
                    "--excmd=number",
                    "-R",
                    "--languages=C,C++",
                    "--c-kinds=+p",  # 包含函数原型
                    "--c++-kinds=+p",
                    "--extras=+q",  # 包含限定符
                    "-f",
                    tags_path,
                    ".",
                ],
                stdout=subprocess.PIPE,
                cwd=repo_dir,
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if ctags.returncode != 0:
                stderr = (ctags.stderr or "").strip()
                if stderr:
                    logger.warning(f"[_prepare] ctags 退出码 {ctags.returncode}: {stderr[:500]}")
                # 若 tags 文件不可用，仍然视为失败
                if not os.path.exists(tags_path) or os.path.getsize(tags_path) == 0:
                    raise subprocess.CalledProcessError(
                        ctags.returncode, ctags.args, output=ctags.stdout, stderr=ctags.stderr
                    )

            if not os.path.exists(tags_path) or os.path.getsize(tags_path) == 0:
                raise subprocess.CalledProcessError(
                    ctags.returncode, ctags.args, output=ctags.stdout, stderr=ctags.stderr
                )

            symbol_map[ref] = {}
            with open(tags_path, "rb") as f:
                for line in f.readlines():
                    if text := line.decode("utf-8", errors="ignore"):
                        if text.startswith("!_TAG_"):
                            continue
                        try:
                            symbol, file, lineno = text.strip().split(';"')[0].split("\t")
                            lineno = int(lineno)
                            if symbol not in symbol_map[ref]:
                                symbol_map[ref][symbol] = []
                            symbol_map[ref][symbol].append((file, lineno))
                        except:
                            continue
        finally:
            try:
                if os.path.exists(tags_path):
                    os.unlink(tags_path)
            except Exception:
                pass

    def _viewcode(
        self, ref: str, path: str, startline: int, endline: int, strict_ref: bool = False
    ) -> str:
        """
        View a file from a specific ref of the target repository. Lines between startline and endline are shown.

        Args:
            ref (str): The specific ref of the target repository.
            path (str): The path of the file to view.
            startline (int): The starting line number to display.
            endline (int): The ending line number to display.

        Returns:
            str: The content of the file between the specified startline and endline.
                 If the file doesn't exist in the commit, a message indicating that is returned.
        """
        ref = self._resolve_target_ref(ref, strict=strict_ref)
        content = self._read_target_file_content(ref, path)
        if content is None:
            return "This file doesn't exist in this commit or target source directory."
        lines = content.split("\n")
        if not lines:
            return "This file is empty in this commit."
        total = len(lines)
        # 保护性修正行号，避免越界
        startline = max(1, min(startline, total))
        endline = max(startline, min(endline, total))
        ret = []
        if endline > total:
            ret.append(
                f"This file only has {total} lines. Here are lines {startline} through {endline}.\n"
            )
        else:
            ret.append(f"Here are lines {startline} through {endline}.\n")
        for i in range(startline - 1, endline):
            ret.append(lines[i])
        return (
            "\n".join(ret)
            + "\nBased on the previous information, think carefully do you see the target code? You may want to keep checking if you don't.\n"
        )

    def _read_target_file_content(self, ref: str, path: str) -> str | None:
        """
        Read file content strictly from the target git tree at the given ref.
        Do not fallback to workspace files to avoid leaking untracked/local-only content
        into ref-based lookup decisions.
        """
        try:
            file_obj = self.target_repo.tree(ref) / path
            if hasattr(file_obj, "type") and file_obj.type != "blob":
                return None
            return file_obj.data_stream.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        return None

    def _read_source_file_content(self, ref: str, path: str) -> str | None:
        """
        Read file content strictly from the source git tree at the given ref.
        """
        try:
            file_obj = self.repo.tree(ref) / path
            if hasattr(file_obj, "type") and file_obj.type != "blob":
                return None
            return file_obj.data_stream.read().decode("utf-8", errors="ignore")
        except Exception:
            pass
        return None

    def _locate_symbol(
        self,
        ref: str,
        symbol: str,
        strict_ref: bool = False,
        use_target_repo: bool = True,
    ) -> List[Tuple[str, int]] | None:
        """
        Locate a symbol in a specific ref of the target repository.

        Args:
            ref (str): The reference of the target repository.
            symbol (str): The symbol to locate.

        Returns:
            List[Tuple[str, int]] | None: File path and code lines.
        """
        # XXX: Analyzing ctags file everytime locate symbol is time-consuming.
        if use_target_repo:
            ref = self._resolve_target_ref(ref, strict=strict_ref)
            symbol_map = self.symbol_map
        else:
            ref = self._resolve_source_ref(ref, strict=strict_ref)
            symbol_map = self.source_symbol_map

        if ref not in symbol_map:
            self._checkout(ref, use_target_repo=use_target_repo)
            self._prepare(ref, use_target_repo=use_target_repo)

        if symbol in symbol_map[ref]:
            return symbol_map[ref][symbol]
        else:
            return None

    def _viewcode_source(
        self, ref: str, path: str, startline: int, endline: int, strict_ref: bool = False
    ) -> str:
        """
        View a file from a specific ref of the source repository.
        """
        ref = self._resolve_source_ref(ref, strict=strict_ref)
        content = self._read_source_file_content(ref, path)
        if content is None:
            return "This file doesn't exist in this commit or source directory."
        lines = content.split("\n")
        if not lines:
            return "This file is empty in this commit."
        total = len(lines)
        startline = max(1, min(startline, total))
        endline = max(startline, min(endline, total))
        ret = []
        if endline > total:
            ret.append(
                f"This file only has {total} lines. Here are lines {startline} through {endline}.\n"
            )
        else:
            ret.append(f"Here are lines {startline} through {endline}.\n")
        for i in range(startline - 1, endline):
            ret.append(lines[i])
        return (
            "\n".join(ret)
            + "\nThis is source-repo context for understanding original patch intent; "
              "generate/apply patch based on target-repo code context.\n"
        )

    def _locate_similar_symbol(
        self, ref: str, symbol: str
    ) -> List[Tuple[str, int]] | None:
        """
        Locate the most similar symbol with llm need in a specific ref of the target repository.

        Args:
            ref (str): The reference of the target repository.
            symbol (str): The symbol to locates.

        Returns:
            List[Tuple[str, int]] : File path and code lines for the most similar symbol.
        """
        # XXX: Analyzing ctags file everytime locate symbol is time-consuming.
        symbols = self.symbol_map.get(ref, {})
        most_similar = None
        smallest_distance = float("inf")

        for symbol_i in symbols.keys():
            # 计算 Levenshtein 距离
            distance = Levenshtein.distance(symbol, symbol_i)
            if distance < smallest_distance:
                smallest_distance = distance
                most_similar = symbol_i

        return symbols.get(most_similar), most_similar

    def _git_history(self) -> str:
        """
        XXX: TBD

        Args:
            XXX

        Returns:
            XXX(str):
        """
        if self.now_hunk != "completed":
            hunk = self.now_hunk

            # Prefer new-path (`+++ b/...`) so new-file hunks (`--- /dev/null`)
            # still map to a real file path.
            filepath = None
            plus_match = re.search(r"^\+\+\+ b/(.+)$", hunk, re.MULTILINE)
            minus_match = re.search(r"^--- a/(.+)$", hunk, re.MULTILINE)
            if plus_match and plus_match.group(1).strip() != "/dev/null":
                filepath = plus_match.group(1).strip()
            elif minus_match and minus_match.group(1).strip() != "/dev/null":
                filepath = minus_match.group(1).strip()
            if not filepath:
                logger.debug("[_git_history] 无法从 hunk 解析文件路径")
                return (
                    "Can not parse file path from current hunk. "
                    "Please provide a standard unified diff with `---/+++` headers.\n"
                )

            # Support both `@@ -a,b +c,d @@` and `@@ -a +c @@` forms.
            chunk_match = re.search(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@",
                hunk,
            )
            if not chunk_match:
                logger.debug("[_git_history] 无法从 hunk 解析 @@ 行号信息")
                return (
                    "Can not parse hunk range from current patch. "
                    "Please ensure the patch contains valid `@@ ... @@` headers.\n"
                )

            old_start = int(chunk_match.group(1))
            old_count = int(chunk_match.group(2) or "1")
            if old_count <= 0 or old_start <= 0:
                logger.debug(
                    "[_git_history] 新增文件或无旧上下文场景，跳过 git log -L 查询"
                )
                return (
                    "Current hunk is a pure new-file/addition context (no old lines), "
                    "so `git_history` cannot use `git log -L`. "
                    "Please use `git_show`/`viewcode` for related commit context.\n"
                )

            start_line = old_start
            end_line = old_start + old_count - 1

            # Keep history lookup bounded by default to avoid flooding model context
            # with distant/weakly related commits. Deep mode is only used as fallback.
            history_max_count = int(os.getenv("CVEKIT_GIT_HISTORY_MAX_COUNT", "12"))
            history_since = os.getenv("CVEKIT_GIT_HISTORY_SINCE", "5 years ago")
            deep_max_count = int(os.getenv("CVEKIT_GIT_HISTORY_DEEP_MAX_COUNT", "80"))

            def _build_log_args(limited: bool = True) -> list[str]:
                args = ["--oneline", "--no-merges", f"-L {start_line},{end_line}:{filepath}"]
                if limited:
                    if history_max_count > 0:
                        args.append(f"--max-count={history_max_count}")
                    if history_since:
                        args.append(f"--since={history_since}")
                else:
                    if deep_max_count > 0:
                        args.append(f"--max-count={deep_max_count}")
                return args

            def _looks_usable_history(log_text: str) -> bool:
                if not log_text:
                    return False
                if "diff --git" not in log_text:
                    return False
                try:
                    chunks = list(utils.split_patch(log_text, False))
                except Exception:
                    return False
                return len(chunks) > 0
            
            # 判断是否跨仓库（target_path 和 project_dir 是不同的仓库）
            is_cross_repo = (hasattr(self, 'target_dir') and 
                           self.target_dir != self.dir)
            
            if is_cross_repo:
                # 跨仓库场景：target_release 在目标仓库中，new_patch_parent 在源仓库中
                # 它们没有共同祖先，不能使用 merge_base
                # 只查询源仓库中从 new_patch_parent 往前的历史
                logger.debug(f"[_git_history] 跨仓库场景，只查询源仓库历史: {self.dir}")
                # NOTE:
                # `git log ..<rev>` is invalid when left side is empty and can
                # trigger "fatal: No commit specified?".
                # For cross-repo history lookup, use a single tip rev.
                try:
                    log_message = self.repo.git.log(
                        *_build_log_args(limited=True),
                        self.new_patch_parent,
                    )
                except Exception as e:
                    logger.debug(f"[_git_history] 跨仓库 git log -L 失败: {e}")
                    return (
                        "git_history failed to query source-repo line history. "
                        "Please continue with `viewcode_source`/`locate_symbol_source` "
                        "and use `viewcode` on target for patch crafting.\n"
                    )
            else:
                # 同一仓库场景：可以使用 merge_base 找到共同祖先
                merge_base = self.repo.merge_base(
                    self.target_release, self.new_patch_parent
                )
                start_commit = merge_base[0].hexsha if merge_base else None
                range_spec = (
                    f"{start_commit}..{self.new_patch_parent}"
                    if start_commit
                    else self.new_patch_parent
                )
                log_message = self.repo.git.log(
                    *_build_log_args(limited=True),
                    range_spec,
                )

            # Fallback to deep history only when current hunk can not be located.
            used_deep_history = False
            if not _looks_usable_history(log_message):
                logger.debug(
                    "[_git_history] 受限历史无法定位当前 hunk，升级为深历史检索: file=%s, range=%s-%s",
                    filepath,
                    start_line,
                    end_line,
                )
                used_deep_history = True
                try:
                    if is_cross_repo:
                        log_message = self.repo.git.log(
                            *_build_log_args(limited=False),
                            self.new_patch_parent,
                        )
                    else:
                        merge_base = self.repo.merge_base(
                            self.target_release, self.new_patch_parent
                        )
                        start_commit = merge_base[0].hexsha if merge_base else None
                        range_spec = (
                            f"{start_commit}..{self.new_patch_parent}"
                            if start_commit
                            else self.new_patch_parent
                        )
                        log_message = self.repo.git.log(
                            *_build_log_args(limited=False),
                            range_spec,
                        )
                except Exception as e:
                    logger.debug(f"[_git_history] 深历史检索失败: {e}")
                    return (
                        "git_history failed to query line history with bounded and deep modes. "
                        "Please continue with `viewcode`/`viewcode_source` for direct context.\n"
                    )
            # save each hunk related refs
            if self.now_hunk_num not in self.hunk_log_info and log_message:
                patch_chunks = list(utils.split_patch(log_message, False))
                if not patch_chunks:
                    return (
                        "git_history found no parseable patch chunks for current hunk. "
                        "Please continue with `viewcode`/`locate_symbol`.\n"
                    )
                last_context = patch_chunks[-1]
                (
                    _,
                    context_line_num,
                    self.last_context,
                    add_line_num,
                ) = utils.extract_context(last_context.split("\n")[3:])
                self.add_percent = add_line_num / (add_line_num + context_line_num)

                self.hunk_log_info[self.now_hunk_num] = []
                patch_list = log_message.split("\n")
                current_sha = None
                for idx, line in enumerate(patch_list):
                    commit_match = re.match(r"^([0-9a-f]{7,40})\s+", line)
                    if commit_match:
                        current_sha = commit_match.group(1)
                    if line.startswith("diff --git"):
                        if current_sha:
                            self.hunk_log_info[self.now_hunk_num].append(current_sha)

            # Return structured summary instead of raw long history text.
            commit_lines = []
            for line in log_message.splitlines():
                if re.match(r"^[0-9a-f]{7,40}\s+", line):
                    commit_lines.append(line.strip())
            summary_top_n = int(os.getenv("CVEKIT_GIT_HISTORY_SUMMARY_TOP_N", "8"))
            top_commit_lines = commit_lines[: max(summary_top_n, 1)]

            mode = "deep" if used_deep_history else "limited"
            ret = (
                "git_history summary\n"
                f"- file: {filepath}\n"
                f"- old_range: {start_line}-{end_line}\n"
                f"- mode: {mode}\n"
                f"- commits_found: {len(commit_lines)}\n"
            )
            if top_commit_lines:
                ret += "- top_commits:\n"
                for item in top_commit_lines:
                    ret += f"  - {item}\n"
            else:
                ret += "- top_commits: none\n"

            related_refs = self.hunk_log_info.get(self.now_hunk_num, [])
            if related_refs:
                ret += f"- related_refs_for_git_show: {', '.join(related_refs[:5])}\n"
            else:
                ret += "- related_refs_for_git_show: none\n"

            ret += (
                "\nUse this summary to reason about lineage. "
                "If needed, call `git_show` for the last related ref, "
                "then use `viewcode`/`locate_symbol` to verify exact target context.\n"
            )
            return ret

        else:
            # XXX TBD
            # JUST return each hunk related refs
            return "No active hunk for git_history.\n"

    def _git_show(self) -> str:
        """
        Show commit message for a specific ref when LLM need.

        Args:
            ref (str): The reference of the target repository.

        Returns:
            message(str): The commit message of ref
        """
        try:
            # XXX maybe too much context will confuse LLM, how could we refine it.
            ref_line = self.hunk_log_info[self.now_hunk_num][-1]
            ref = ref_line.split(" ")[0].strip()
            log = self.repo.git.show(f"{ref}")
            pps = utils.split_patch(log, False)
            dist = float("inf")
            last_context_len = len(self.last_context)
            best_context = []
            file_path = ""
            file_no = 0

            for idx, pp in enumerate(pps):
                try:
                    file_path_i = re.findall(r"--- a/(.*)", pp)[0]
                    chunks = re.findall(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)", pp)[0]
                    contexts, _, _, _ = utils.extract_context(pp.split("\n")[3:])
                    if (int(chunks[1]) - int(chunks[3])) < last_context_len:
                        continue
                    lineno, dist_i = utils.find_most_similar_block(
                        self.last_context, contexts, last_context_len, False
                    )
                    if dist_i < dist:
                        best_context = contexts[
                            lineno - 1 : lineno - 1 + last_context_len
                        ]
                        dist = dist_i
                        file_path = file_path_i
                        file_no = int(chunks[0]) + lineno - 1
                except:
                    continue

            ret = ""
            stat = self.repo.git.show("--stat", f"{ref}")
            ret += stat[0 : min(len(stat), 3000)]
            ret += "\n"
            if self.add_percent < 0.6:
                ret += f"[IMPORTANT] The relevant code shown by `git_history` is not fully `+` lines.\n"
                ret += f"[IMPORTANT] This means that the code in question was not added or migrated in this commit.\n"
                ret += f"[IMPORTANT] Please think step by step and check the abstract below carefully. If error exists in abstract, please ignore the info below.\n"
            elif best_context:
                ret += f"Because the commit's code change maybe too long, so I generate the abstract of the code change to show you how code changed in this commit.\n"
                ret += f"Commit shows that the patch code in old version maybe in the file {file_path} around line number {file_no} to {file_no + last_context_len}. The code is below\n"
                code_snippets = "\n".join(best_context)
                ret += f"{code_snippets}"
                ret += f"\nYou can call `viewcode` and `locate_symbol` to find the relevant code based on this information step by step."
            else:
                ret += f"This commit shows that there is a high probability that this code is new, so the corresponding code segment cannot be found in the old version.\n"
                ret += f"You can call `viewcode` and `locate_symbol` to further check the results step by step. For newly introduced code, we consider that this hunk `need not ported`.\n"
            return ret
        except:
            return "Something error, maybe you don't use git_history before or git_history is empty."

    def _apply_error_handling(self, ref: str, revised_patch: str) -> Tuple[str, str]:
        """
        Generate feedback to llm when an error patch is applied.
        When a file is not found, it is looked for in the five most similar files.

        Args:
            ref (str): The reference of the target repository.
            revised_patch (str): The patch to be applied.

        Returns:
            Tuple[str, str]: Bug patch similar code block information and difference between patch context and original code context.

        """
        path = self._extract_patch_target_path(revised_patch)
        revised_patch_line = revised_patch.split("\n")[3:]
        contexts, num_context, _, _ = utils.extract_context(revised_patch_line)
        lineno = -1
        lines = []
        min_distance = float("inf")

        ref = self._resolve_target_ref(ref)
        content = self._read_target_file_content(ref, path)
        if content is not None:
            lines = content.split("\n")
            lineno, dist = utils.find_most_similar_block(
                contexts, lines, num_context, False
            )
        else:
            # 在目标仓库目录中查找相似文件
            filename = path.split("/")[-1] if path else ""
            similar_files = utils.find_most_similar_files(filename, self.target_dir)
            for similar_file in similar_files:
                content = self._read_target_file_content(ref, similar_file)
                if content is None:
                    continue
                similar_lines = content.split("\n")
                current_line, current_dist = utils.find_most_similar_block(
                    contexts, similar_lines, num_context, False
                )

                if current_dist < min_distance:
                    min_distance = current_dist
                    lineno = current_line
                    path = similar_file
                    lines = similar_lines

        if not lines:
            block = (
                "I cannot locate the target file from git tree or target source directory. "
                "Please check your patch path and try a nearby file path.\n"
            )
            differ = (
                "Cannot generate context diff because source file content is unavailable.\n"
            )
            return block, differ

        startline = max(lineno - 1, 0)
        endline = min(max(lineno, 1) + num_context, len(lines))
        if endline < startline:
            endline = startline
        block = "Here are lines {} through {} of file {} for commit {}.\n".format(
            startline, endline, path, ref
        )
        block += "```code snippet\n"
        for i in range(startline, endline):
            block = block + lines[i] + "\n"
        block += "```\n"

        differ = "```context diff\n"
        contexts = contexts[: min(len(lines), len(contexts))]
        j = 0
        base_index = lineno - 1
        for i, context in enumerate(revised_patch_line):
            if context.startswith(" ") or context.startswith("-"):
                idx = base_index + j
                if idx < 0 or idx >= len(lines):
                    differ += f"On the line {i + 4} of your patch.\n"
                    differ += f"          Your patch:{context[1:]}\n"
                    differ += "Original source code:<out of range>\n"
                    j += 1
                    continue
                if context[1:] != lines[idx]:
                    differ += f"On the line {i + 4} of your patch.\n"
                    differ += f"          Your patch:{context[1:]}\n"
                    differ += f"Original source code:{lines[idx]}\n"
                j += 1

        if differ == "```context diff\n":
            differ = "Here it shows that there is no difference between your context and the original code, the reason for the failure is that you didn't keep at least three lines of source code at the beginning and end of the patch, please follow this to fix it.\n"
        else:
            differ += "```\nPlease eliminate these diffs step by step. Be sure to eliminate these diffs the next time you generate a patch!\n"
        return block, differ

    def _apply_file_move_handling(self, ref: str, old_patch: str) -> str:
        """
        If a patch cannot apply for "No such file", try to find the symbol and apply the patch to the correct file.

        Args:
            ref (str): The reference string.
            old_patch (str): The patch that raises "No such file" when apply.

        Returns:
            str: If the file is found, return the current file path. Else, return all possible file paths.
        """
        ret = ""
        file_paths = []
        missing_file_path = re.findall(r"--- a/(.*)", old_patch)[0]

        # 判断是否跨仓库（target_path 和 project_dir 是不同的仓库）
        is_cross_repo = (hasattr(self, 'target_dir') and 
                       self.target_dir != self.dir)

        # locate file by git diff (在目标仓库中查找)
        if is_cross_repo:
            # 跨仓库场景：不能在目标仓库中比较源仓库的 commit
            # 只在目标仓库中查找文件重命名历史（从 target_release 往回查找，限制为最近1年）
            logger.debug(f"[_apply_file_move_handling] 跨仓库场景，在目标仓库中查找文件重命名: {self.target_dir}")
            try:
                # 在目标仓库中使用 git log 查找文件重命名历史
                # 优化：限制查询范围为最近1年，并限制提交数量，找到第一个匹配就停止
                # 参数顺序：选项 -> commit范围 -> 路径限制
                # 从 target_release 往回查找，但限制为最近1年和最多500个提交
                log_args = [
                    "--oneline",
                    "--follow",
                    "--diff-filter=R",
                    "--name-status",
                    "--since=1 year ago",  # 只查询最近1年的历史
                    "-n", "500",  # 最多查询500个提交，避免查询过多历史
                    f"{self.target_release}",  # 从 target_release 往回查找历史
                    "--",
                    missing_file_path,
                ]
                rename_log = self.target_repo.git.log(log_args)
                if rename_log:
                    # git log --name-status 的输出格式可能是：
                    # commit_hash
                    # R100    old_path    new_path
                    # 或者
                    # commit_hash\tR100\told_path\tnew_path
                    lines = rename_log.strip().split('\n')
                    if lines:
                        # 查找包含 R (重命名) 的行
                        for line in lines:
                            if line.startswith('R') or '\tR' in line:
                                # 解析重命名行
                                parts = line.split('\t')
                                if 'R' in parts:
                                    # 找到 R 的位置
                                    r_index = parts.index('R') if 'R' in parts else None
                                    if r_index is not None and len(parts) > r_index + 2:
                                        # 格式可能是: "R100\told_path\tnew_path" 或 "R\told_path\tnew_path"
                                        old_path_idx = r_index + 1
                                        new_path_idx = r_index + 2
                                        if len(parts) > new_path_idx:
                                            old_path = parts[old_path_idx].strip()
                                            new_path = parts[new_path_idx].strip()
                                            # 检查是否匹配我们要查找的文件
                                            if old_path == missing_file_path or missing_file_path in old_path:
                                                file_paths.append(new_path)
                                                logger.debug(
                                                    f"在目标仓库中找到文件重命名: {missing_file_path} -> {new_path}"
                                                )
                                                file_diff = f"R100\t{old_path}\t{new_path}"  # 模拟 diff 格式
                                                break
                        if not file_paths:
                            file_diff = None
                    else:
                        file_diff = None
                else:
                    file_diff = None
            except Exception as e:
                logger.debug(f"[_apply_file_move_handling] 在目标仓库中查找文件重命名失败: {e}")
                file_diff = None
        else:
            # 同一仓库场景：可以在目标仓库中比较两个 commit
            diff_args = [
                "--diff-filter=R",
                "--name-status",
                "--follow",
                self.target_release,
                self.new_patch_parent,
                "--",
                missing_file_path,
            ]
            file_diff = self.target_repo.git.diff(diff_args)
        
        if file_diff:
            # 解析 file_diff 获取新路径
            # 格式: "R100\told_path\tnew_path"
            parts = file_diff.strip().split("\t")
            if len(parts) >= 3:
                file_path = parts[2]  # 新路径在第3个位置
                logger.debug(
                    f"We have found the patch's file path is {file_path} at target release by git diff."
                )
                if file_path not in file_paths:
                    file_paths.append(file_path)

        # locate target file by symbol or utils.find_most_similar_files
        if not file_paths:
            try:
                # XXX: find symbol: the word before the first '{' or '('
                # @@ -135,7 +135,6 @@ struct ksmbd_transport_ops {
                # @@ -416,13 +416,7 @@ static void stop_sessions(void)
                at_line = old_patch.split("\n")[2]
                symbol_name = re.findall(r"\b\w+(?=\s*[{\(])", at_line)[0]
                symbol_locations = self._locate_symbol(ref, symbol_name)
                if not symbol_locations:
                    logger.debug(
                        f"No {missing_file_path} and no {symbol_name} in the repo."
                    )
                    file_paths = utils.find_most_similar_files(
                        missing_file_path.split("/")[-1], self.target_dir
                    )
                else:
                    logger.debug(f"Find {symbol_name} in {symbol_locations}.")
                    file_paths = [item[0] for item in symbol_locations]
            except:
                logger.debug("Can not find a symbol in given patch.")
                file_paths = utils.find_most_similar_files(
                    missing_file_path.split("/")[-1], self.target_dir
                )

        # try to apply patch to the target files
        for file_path in file_paths:
            new_patch = old_patch.replace(missing_file_path, file_path)
            logger.debug(f"Try to apply patch to {file_path}.")
            apply_ret = self._apply_hunk(ref, new_patch, False)
            if "successfully" in apply_ret:
                logger.debug(f"{missing_file_path} has been moved to {file_path}.")
                return f"{missing_file_path} has been moved to {file_path}. Please use --- a/{file_path} in your patch.\n"
            else:
                ret += apply_ret

        # patch can not apply directly
        logger.debug(f"Patch can not be applied to {file_paths}.")
        return f"The target file has been moved, here is possible file paths:{file_paths}\n{ret}"

    def _apply_hunk(self, ref: str, patch: str, revise_context: bool = False) -> str:
        """
        将 hunk 应用到目标仓库的特定引用（commit/分支）。
        
        这个函数会：
        1. 切换到目标引用并重置工作区
        2. 先直接尝试应用原始补丁
        3. 若失败再修正补丁（修复行号、格式等）并重试
        4. 处理各种错误情况：
           - 文件不存在：尝试查找文件移动后的位置
           - 补丁损坏：返回错误信息
           - 上下文不匹配：返回相似代码块和差异信息

        Args:
            ref (str): 目标仓库的引用（commit ID 或分支名）
            patch (str): 要应用的补丁内容
            revise_context (bool, optional): 是否强制修正所有上下文行。默认为 False

        Returns:
            str: 补丁应用结果的字符串描述
            
            可能的结果：
            - "Patch applied successfully\n": 补丁应用成功
            - 文件不存在时的查找结果
            - "Unexpected corrupt patch...": 补丁损坏
            - 上下文不匹配时的详细错误信息

        Raises:
            Exception: 如果补丁应用失败（某些情况下）
        """
        logger.debug("=" * 80)
        logger.debug("[_apply_hunk] 开始应用 hunk")
        logger.debug("=" * 80)
        logger.debug(f"[_apply_hunk] 输入参数:")
        logger.debug(f"  - ref={ref}")
        logger.debug(f"  - patch 长度: {len(patch)} 字符")
        logger.debug(f"  - revise_context={revise_context}")
        logger.debug(
            "  - patch 结构: has_diff=%s, has_hunk=%s",
            "diff --git " in patch or "\n--- " in patch,
            "@@" in patch,
        )
        
        ret = ""
        self.last_success_revised_patch = ""
        
        # 切换到目标引用（在目标仓库中）
        logger.debug(f"[_apply_hunk] 切换到目标引用: ref={ref}")
        logger.debug(f"[_apply_hunk] 使用目标仓库: {self.target_dir}")
        self._checkout(ref, use_target_repo=True)
        logger.debug(f"[_apply_hunk] 切换完成，当前 HEAD: {self.target_repo.head.commit.hexsha[:8]}")
        
        # 重置工作区（丢弃所有未提交的更改）
        logger.debug("[_apply_hunk] 重置工作区（git reset --hard）...")
        safe_git_reset_hard(self.target_repo)
        logger.debug("[_apply_hunk] 工作区重置完成")

        # 单一入口：统一由工具函数完成前导噪音裁剪 + unified diff 校验。
        valid_diff, invalid_reason, normalized_patch = utils.validate_unified_diff_patch(patch)
        if not valid_diff:
            self.round_succeeded = False
            ret = (
                "Rejected invalid patch before revise/apply: "
                f"{invalid_reason}. Please provide a standard unified diff.\n"
            )
            logger.debug(f"[_apply_hunk] unified diff 预检失败: {invalid_reason}")
            logger.debug(f"[_apply_hunk] 返回结果: {ret}")
            return ret
        patch = normalized_patch
        
        if revise_context:
            logger.debug("[_apply_hunk] revise_context=True")

        apply_failed_exc = None
        apply_failed_stderr = ""
        diagnose_patch = patch

        # Phase-1: try original normalized patch first.
        logger.debug("[_apply_hunk] Phase-1: 直接尝试原始补丁（不 revise）...")
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write(patch)
                temp_file_path = f.name
            logger.debug("  执行: git apply %s -v", temp_file_path)
            self.target_repo.git.apply([temp_file_path], v=True)
            logger.debug("[_apply_hunk] Phase-1 成功：原始补丁可直接应用")
            ret += "Patch applied successfully\n"
            self.last_success_revised_patch = patch
            self._upsert_succeeded_patch(patch)
            self.round_succeeded = True
            logger.debug(f"[_apply_hunk] round_succeeded={self.round_succeeded}")
        except Exception as e_raw:
            apply_failed_exc = e_raw
            if hasattr(e_raw, "stderr") and e_raw.stderr:
                apply_failed_stderr = str(e_raw.stderr)
            logger.debug(
                "[_apply_hunk] Phase-1 失败，进入 Phase-2 revise 重试: %s",
                type(e_raw).__name__,
            )

            # Phase-2: revise patch only after direct apply failed.
            logger.debug("[_apply_hunk] Phase-2: 开始修正补丁并重试应用...")
            logger.debug(
                "  参数: patch 长度=%s, target_dir=%s, revise_context=%s",
                len(patch),
                self.target_dir,
                revise_context,
            )
            revised_patch, fixed = utils.revise_patch(patch, self.target_dir, revise_context)
            logger.debug(
                "[_apply_hunk] Phase-2 revise 完成: fixed=%s, revised_patch长度=%s",
                fixed,
                len(revised_patch),
            )

            valid_revised, revised_invalid_reason, normalized_revised_patch = (
                utils.validate_unified_diff_patch(revised_patch)
            )
            if valid_revised:
                revised_patch = normalized_revised_patch
                diagnose_patch = revised_patch
                try:
                    with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                        f.write(revised_patch)
                        temp_file_path = f.name
                    logger.debug("  执行: git apply %s -v", temp_file_path)
                    self.target_repo.git.apply([temp_file_path], v=True)
                    logger.debug("[_apply_hunk] Phase-2 成功：revised 补丁可应用")
                    ret += "Patch applied successfully\n"
                    self.last_success_revised_patch = revised_patch
                    self._upsert_succeeded_patch(revised_patch)
                    self.round_succeeded = True
                    logger.debug(f"[_apply_hunk] round_succeeded={self.round_succeeded}")
                except Exception as e_revised:
                    apply_failed_exc = e_revised
                    if hasattr(e_revised, "stderr") and e_revised.stderr:
                        apply_failed_stderr = str(e_revised.stderr)
                    logger.debug(
                        "[_apply_hunk] Phase-2 失败: %s", type(e_revised).__name__
                    )
            else:
                logger.debug(
                    "[_apply_hunk] Phase-2 revise 产物结构无效，保留 Phase-1 失败信息用于诊断: %s",
                    revised_invalid_reason,
                )

        # 两阶段都失败时，按原有分支返回可操作反馈。
        if not self.round_succeeded and apply_failed_exc is not None:
            e = apply_failed_exc
            error_stderr = apply_failed_stderr or ""
            logger.debug(f"[_apply_hunk] 补丁应用失败，捕获异常: {type(e).__name__}")
            logger.debug(f"  - 异常对象: {e}")
            logger.debug(f"  - 异常类型: {type(e)}")
            if error_stderr:
                logger.debug(
                    "  - stderr 摘要: %s",
                    (error_stderr[:200] + "...") if len(error_stderr) > 200 else error_stderr,
                )

            if "No such file" in error_stderr:
                logger.debug("[_apply_hunk] 错误类型: 文件不存在（No such file）")
                logger.debug("[_apply_hunk] 尝试查找文件移动后的位置...")
                find_ret = self._apply_file_move_handling(ref, diagnose_patch)
                logger.debug(
                    f"[_apply_hunk] 文件查找结果: {find_ret[:200]}..."
                    if len(find_ret) > 200
                    else f"[_apply_hunk] 文件查找结果: {find_ret}"
                )
                ret += find_ret
                logger.debug(f"[_apply_hunk] 返回结果已更新，当前长度: {len(ret)} 字符")
            elif "corrupt patch" in error_stderr:
                logger.debug("[_apply_hunk] 错误类型: 补丁损坏（corrupt patch）")
                ret = "Unexpected corrupt patch, Please carefully check your answer, especially in your call tools arguments.\n"
                logger.debug(f"[_apply_hunk] 返回结果: {ret}")
            else:
                logger.debug("[_apply_hunk] 错误类型: 上下文不匹配（Context mismatch）")
                context_error_msg = (
                    "This patch does not apply because of CONTEXT MISMATCH. Context are patch "
                    "lines that already exist in the file, that is, lines starting with ` ` and "
                    "`-`. You should modify the error patch according to the context of older version.\n"
                )
                ret += context_error_msg
                logger.debug("[_apply_hunk] 调用 _apply_error_handling 获取详细错误信息...")
                block, differ = self._apply_error_handling(ref, diagnose_patch)
                ret += block
                ret += "Besides, here is detailed info about how the context differs between the patch and the old version.\n"
                ret += differ
                logger.debug(f"[_apply_hunk] 返回结果已更新，当前长度: {len(ret)} 字符")

        # 重置工作区（清理应用失败的补丁）
        logger.debug("[_apply_hunk] 重置工作区（清理状态）...")
        safe_git_reset_hard(self.target_repo)
        logger.debug("[_apply_hunk] 工作区重置完成")
        
        logger.debug("=" * 80)
        logger.debug(f"[_apply_hunk] hunk 应用完成，返回结果长度: {len(ret)} 字符")
        logger.debug(f"[_apply_hunk] round_succeeded={self.round_succeeded}")
        logger.debug(f"[_apply_hunk] succeeded_patches 数量: {len(self.succeeded_patches)}")
        logger.debug("=" * 80)
        
        return ret

    def _compile_patch(
        self, ref: str, complete_patch: str, revise_context: bool = False
    ) -> str:
        """
        If all hunks could be applied successfully, compiles the patched source code after applying the joined patch.

        Args:
            ref (str): The reference to checkout before applying the patch.
            complete_patch (str): The complete patch to be applied.

        Returns:
            str: A message indicating the result of the compilation process.

        Raises:
            subprocess.TimeoutExpired: If the compilation process times out.

        """
        # apply joined patch (在目标仓库中应用)
        self._checkout(ref, use_target_repo=True)
        ret = ""
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(complete_patch)
            logger.debug(f"The completed patch file {f.name}")
        pps = utils.split_patch(complete_patch, False)
        revised_hunks = []
        for idx, pp in enumerate(pps):
            revised_patch, fixed = utils.revise_patch(pp, self.target_dir, revise_context)
            revised_hunks.append(revised_patch)
            with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
                f.write(revised_patch)
            try:
                # XXX 这里应该把修正后的patch加到结果里面
                self.target_repo.git.apply([f.name], v=True)
                logger.debug(
                    f"The joined patch hunk {idx} could be applied successfully, file {f.name}"
                )
            except Exception as e:
                logger.debug(
                    f"Failed to apply Complete patch hunk {idx}, file {f.name}"
                )
                err_detail = ""
                if hasattr(e, "stderr") and e.stderr:
                    err_detail = str(e.stderr).strip()
                    logger.debug(
                        f"[_compile_patch] joined hunk {idx} git apply stderr: {err_detail[:1000]}"
                    )
                # TODO: give feedback to LLM about which line can not be applied
                ret = f"For the patch you just generated, there was an APPLY failure during testing. Specifically there was a context mismatch in hunk {idx} across the patch, below is part of the feedback I found for you.\n"
                if err_detail:
                    ret += f"Raw git apply error for hunk {idx}:\n{err_detail}\n"
                block, differ = self._apply_error_handling(ref, revised_patch)
                ret += block
                ret += f"Here is the source code near the hunk context for your reference, a good patch context should look exactly like the source code.\n"
                ret += f"In addition to that, I've got more detailed error messages for you below where the context of your generated patch differs specifically from the source code context.(The line numbers below are all line numbers in the hunk, not the entire patch.)\n"
                ret += differ
                ret += f"Based on the above feedback, MUST you please modify only hunk {idx} in the patch and leave the other hunks untouched so that the context present in hunk {idx} is exactly the same as the source code to guarantee that git apply can be executed normally.\n"
                safe_git_reset_hard(self.target_repo)
                return ret

        # 保存最终用于验证的补丁版本
        self.validated_patch = "\n".join(revised_hunks)

        # compile the patch (在目标仓库中编译)
        logger.debug("Start compile the patched source code")
        logger.debug(f"[_compile_patch] 在目标仓库中编译: {self.target_dir}")
        if not os.path.exists(os.path.join(self.target_dir, "build.sh")):
            logger.debug("No build.sh file found.")
            ret += "The patched source code could be COMPILED successfully! I really thank you for your great efforts.\n"
            self.compile_succeeded = True
            return ret

        # build_process = subprocess.Popen(
        #     ["/bin/bash", "build.sh"],
        #     stdin=subprocess.DEVNULL,
        #     stdout=subprocess.PIPE,
        #     stderr=subprocess.PIPE,
        #     cwd=self.dir,
        #     text=True,
        # )
        docker_command = [
            "docker",
            "run",
            "-v",
            f"{self.target_dir}:{self.target_dir}",
            "--rm",
            "build-kernel-ubuntu-16.04",
            "/bin/bash",
            "-c",
            f"cd {self.target_dir}; bash build.sh",
        ]
        build_process = subprocess.Popen(
            docker_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.target_dir,
            text=True,
        )
        try:
            _, compile_result = build_process.communicate(timeout=60 * 60)
        except subprocess.TimeoutExpired:
            build_process.kill()
            ret += f"The compilation process of the patched source code is timeout. "
            safe_git_reset_hard(self.target_repo)
            logger.warning(
                "Timeout in project compilation. Please check patch manually!"
            )
            for patch in self.succeeded_patches:
                logger.info(patch)
            exit(0)
            return ret

        if build_process.returncode != 0:
            logger.info(f"Compilation                       FAILED")
            error_lines = "\n".join(
                [
                    line
                    for line in compile_result.splitlines()
                    if "error:" in line.lower()
                ]
            )
            logger.debug(error_lines)
            ret += "The source code could not be COMPILED successfully after applying the patch. "
            ret += "Next I'll give you the error message during compiling, and you should modify the error patch. "
            ret += f"Here is the error message:\n{error_lines}\n"
            ret += "Please revise the patch with above error message. "
            ret += "Or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. "
            ret += "Please DO NOT send the same patch to me, repeated patches will harm the lives of others.\n"
            safe_git_reset_hard(self.target_repo)
        else:
            logger.info(f"Compilation                       PASS")
            ret += "The patched source code could be COMPILED successfully! I really thank you for your great efforts.\n"
            self.compile_succeeded = True
        # self.repo.git.reset("--hard")
        return ret

    def _run_testcase(self) -> str:
        """
        Runs the testcase after compiling a patch.

        Returns:
            str: A message indicating the result of the testcase process.
        """
        ret = ""
        logger.debug("Run testcase after compile")
        logger.debug(f"[_run_testcase] 在目标仓库中运行测试: {self.target_dir}")

        if not os.path.exists(os.path.join(self.target_dir, "test.sh")):
            logger.debug("No test.sh file found, considered as test passed.")
            self.testcase_succeeded = True
            ret += "The patched source code could pass TESTCASE! I really thank you for your great efforts.\n"
            return ret
        testcase_process = subprocess.Popen(
            ["/bin/bash", "test.sh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.target_dir,
            text=True,
        )

        try:
            _, testcase_result = testcase_process.communicate(timeout=60 * 30)
        except subprocess.TimeoutExpired:
            testcase_process.kill()
            ret += "The TESTCASE process of the patched source code is timeout. "
            return ret

        if testcase_process.returncode != 0:
            logger.info(f"Testsuite                         FAILED")
            logger.debug(f"{testcase_result}")
            ret = "The patched program could not pass the testcase. "
            ret += "Next I'll give you the error message during running the testcase, and you should modify the previous error patch according to this section. "
            ret += f"Here is the error message:\n{testcase_result}\n"
            ret += "Please revise the patch with above error message. "
            ret += "Or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. "
            ret += "Please DO NOT send the same patch to me, repeated patches will harm the lives of others.\n"
            self.compile_succeeded = False
        else:
            logger.info(f"Testsuite                         PASS")
            ret += "The patched source code could pass TESTCASE! I really thank you for your great efforts.\n"
            self.testcase_succeeded = True
        return ret

    def _run_poc(self, complete_patch) -> str:
        """
        Runs the Proof of Concept (PoC) after running the testcase.

        Returns:
            str: A message indicating the result of the PoC process.
        """
        ret = ""
        logger.debug("Run PoC after compile and run testcase")

        if not os.path.exists(os.path.join(self.target_dir, "poc.sh")):
            logger.debug("No poc.sh file found, considered as PoC passed.")
            self.poc_succeeded = True
            self._set_complete_patch_as_single_result(complete_patch)
            ret += "Existing PoC could NOT TRIGGER the bug, which means your patch successfully fix the bug! I really thank you for your great efforts.\n"
            return ret
        poc_process = subprocess.Popen(
            ["/bin/bash", "poc.sh"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self.target_dir,
            text=True,
        )

        try:
            _, poc_result = poc_process.communicate(timeout=60 * 10)
        except subprocess.TimeoutExpired:
            poc_process.kill()
            ret += "The TESTCASE process of the patched source code is timeout. "
            return ret

        if self.err_msg in poc_result:
            logger.info(f"PoC test                          FAILED")
            logger.debug(f"returncode = {poc_process.returncode}")
            logger.debug(f"stderr: {poc_result}")
            ret += "Existing PoC could still trigger the bug, which means your patch fail to fix the bug. "
            ret += "Next I'll give you the error message during running the PoC, and you should modify the previous error patch according to this section. "
            ret += f"Here is the error message:\n{poc_result}\n"
            ret += "Please revise the patch with above error message. "
            ret += "Or use tools `locate_symbol` and `viewcode` to re-check patch-related code snippet. "
            ret += "Please DO NOT send the same patch to me, repeated patches will harm the lives of others.\n"
            self.compile_succeeded = False
            self.testcase_succeeded = False
        else:
            logger.info(f"PoC test                          PASS")
            ret += "Existing PoC could NOT TRIGGER the bug, which means your patch successfully fix the bug! I really thank you for your great efforts.\n"
            self._set_complete_patch_as_single_result(complete_patch)
            self.poc_succeeded = True
        return ret

    def _validate(self, ref: str, patch: str, use_target_repo: bool = True) -> str:
        """
        Validates a patch by using the `_compile_patch`, `_run_testcase`, and `_run_poc` methods.

        Args:
            ref (str): The reference string.
            patch (str): The patch string.

        Returns:
            str: The validation result.

        """
        patch_text = (patch or "").strip()
        is_need_not_ported = patch_text.lower() == "need not ported"

        # Handle "need not ported" uniformly to avoid causal inversion:
        # a non-diff marker must never overwrite an already materialized patch result.
        # NOTE:
        # In conflict-driven backport flow, external precheck may already prove
        # insufficient. Here we allow the LLM to decide equivalence based on
        # tool evidence (viewcode/locate_symbol/git_history/git_show), while
        # still preventing overwrite of a concrete validated patch.
        if is_need_not_ported:
            current_file_key = getattr(self, "active_file_key", "") or self._extract_patch_target_path(self.now_hunk)
            if current_file_key:
                current_file_patch = self.last_success_revised_patch or self.build_succeeded_patch_for_file(current_file_key)
                validated_patch = self.validated_patch or ""
                validated_keys = [key for key, _ in self.extract_grouped_file_patches(validated_patch)] if validated_patch else []
                if self._is_unified_diff_patch(current_file_patch) or current_file_key in validated_keys:
                    self.round_succeeded = False
                    self.current_file_equivalent = False
                    return (
                        "Rejected: concrete patch has been materialized and validated for the current file; "
                        "'need not ported' cannot overwrite it.\n"
                    )

                self.equivalent_file_keys.add(current_file_key)
                self.current_file_equivalent = True
                self.round_succeeded = True
                self.last_success_revised_patch = ""
                return (
                    "Patch is equivalent in target branch for current file; "
                    "need not ported.\n"
                )

            existing_patch = self.validated_patch or self.rebuild_complete_patch()
            if self._is_unified_diff_patch(existing_patch):
                self.round_succeeded = False
                self.current_file_equivalent = False
                return (
                    "Rejected: concrete patch has been materialized and validated; "
                    "'need not ported' cannot overwrite it.\n"
                )

            # Explicitly record equivalence mode as final result: no exported patch.
            self.equivalent_exists = True
            self.current_file_equivalent = False
            self.round_succeeded = True
            self.compile_succeeded = True
            self.testcase_succeeded = True
            self.poc_succeeded = True
            self.validated_patch = ""
            self._set_complete_patch_as_single_result("")
            return "Patch is equivalent in target branch; need not ported.\n"

        if self.all_hunks_applied_succeeded:
            if not self._is_unified_diff_patch(patch):
                self.round_succeeded = False
                return (
                    "Rejected: final validation expects a unified diff patch, got non-diff text.\n"
                )
            patch = self.normalize_patch(patch)
            baseline_patch = self.validated_patch or self.rebuild_complete_patch()
            baseline_keys = [key for key, _ in self.extract_grouped_file_patches(baseline_patch)]
            if baseline_keys:
                candidate_key_set = {key for key, _ in self.extract_grouped_file_patches(patch)}
                missing_file_keys = [key for key in baseline_keys if key not in candidate_key_set]
                if missing_file_keys:
                    self.round_succeeded = False
                    missing_files = ", ".join(missing_file_keys)
                    return (
                        "Rejected: final validation patch dropped file(s) from the existing "
                        f"complete_patch: {missing_files}. Return the FULL multi-file patch "
                        "and keep untouched file blocks unchanged.\n"
                    )
            ret = ""
            if not self.compile_succeeded:
                ret += self._compile_patch(
                    ref, patch, False
                )
                self.context_mismatch_times += 1
            if self.compile_succeeded and not self.testcase_succeeded:
                ret += self._run_testcase()
            if (
                self.compile_succeeded
                and self.testcase_succeeded
                and not self.poc_succeeded
            ):
                patch_to_run = self.validated_patch or patch
                ret += self._run_poc(patch_to_run)
            return ret
        else:
            ret = self._apply_hunk(
                ref, patch, False
            )
            if "CONTEXT MISMATCH" in ret:
                self.context_mismatch_times += 1
            return ret

    def _check_patch(self, patch: str, ref: str | None = None) -> None:
        """
        Run `git apply --check` on the target repo for safety.
        """
        # Ensure we check against the correct target ref (e.g., target_release)
        target_ref = ref or getattr(self, "target_release", None)
        try:
            repo_path = self.target_repo.working_dir
        except Exception:
            repo_path = "unknown"
        try:
            head_sha = self.target_repo.head.commit.hexsha
        except Exception:
            head_sha = "unknown"
        logger.debug(f"[_check_patch] target_repo={repo_path}, HEAD={head_sha}")
        # Ensure a clean worktree before checkout to avoid checkout failures
        safe_git_reset_hard(self.target_repo)
        try:
            self.target_repo.git.clean("-fdx")
        except Exception as e:
            logger.warning(f"[_check_patch] git clean -fdx failed: {e}")
        if target_ref:
            resolved_ref = self._resolve_target_ref(target_ref)
            self._checkout(resolved_ref, use_target_repo=True)
            logger.debug(f"[_check_patch] checkout target ref {resolved_ref}")
            # Ensure clean state after checkout as well
            safe_git_reset_hard(self.target_repo)
            try:
                self.target_repo.git.clean("-fdx")
            except Exception as e:
                logger.warning(f"[_check_patch] git clean -fdx failed: {e}")
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(patch)
            temp_file_path = f.name
        logger.debug(f"[_check_patch] git apply --check {temp_file_path}")
        self.target_repo.git.apply([temp_file_path, "--check"])

    def get_tools(self):
        return (
            creat_viewcode_tool(self),
            creat_locate_symbol_tool(self),
            creat_viewcode_source_tool(self),
            creat_locate_symbol_source_tool(self),
            create_validate_tool(self),
            create_git_history_tool(self),
            create_git_show_tool(self),
        )


def creat_locate_symbol_tool(project: Project):
    @tool
    def locate_symbol(ref: str, symbol: str) -> str:
        """
        Locate a symbol in a specific ref of the target repository.
        """
        is_cross_repo = hasattr(project, "target_dir") and project.target_dir != project.dir
        target_ref = getattr(project, "target_release", None)
        source_ref = getattr(project, "new_patch_parent", None)
        if is_cross_repo and target_ref and ref != target_ref:
            # If caller passed a source ref (e.g., new_patch_parent), auto route
            # to source repo symbol lookup for source-context understanding.
            is_source_ref = False
            if source_ref and ref == source_ref:
                is_source_ref = True
            else:
                try:
                    project.repo.commit(ref)
                    project.target_repo.commit(ref)
                    is_source_ref = False
                except Exception:
                    try:
                        project.repo.commit(ref)
                        is_source_ref = True
                    except Exception:
                        is_source_ref = False

            if is_source_ref:
                try:
                    res = project._locate_symbol(
                        ref, symbol, strict_ref=True, use_target_repo=False
                    )
                except ValueError as e:
                    return f"{e}\nTip: use source refs (e.g., new_patch_parent) with source lookup."
                if res is not None:
                    return (
                        "[AUTO-ROUTED to source repo]\n"
                        + "\n".join([f"{file}:{line}" for file, line in res])
                    )
                return (
                    "[AUTO-ROUTED to source repo]\n"
                    f"The symbol {symbol} you are looking for does not exist in the current source ref.\n"
                )

            return (
                f"Cross-repo mode detected. locate_symbol expects target ref {target_ref} "
                f"for target context, or a valid source ref for source context, but got {ref}."
            )
        try:
            res = project._locate_symbol(ref, symbol, strict_ref=True)
        except ValueError as e:
            return (
                f"{e}\n"
                "Tip: in cross-repo mode, pass target_release as ref for "
                "locate_symbol/viewcode/validate."
            )
        if res is not None:
            return "\n".join([f"{file}:{line}" for file, line in res])
        else:
            res, most_similar = project._locate_similar_symbol(ref, symbol)
            ret = f"The symbol {symbol} you are looking for does not exist in the current ref.\n"
            if most_similar:
                ret += f"But here is a symbol similar to it. It's `{most_similar}`.\n"
            if not res:
                ret += "No similar symbol locations found.\n"
                return ret
            ret += f"The file where this symbol is located is: \n"
            ret += "\n".join([f"{file}:{line}" for file, line in res])
            ret += f"\nPlease be careful to check that this symbol indicates the same thing as the previous symbol.\n"
            return ret

    return locate_symbol


def creat_viewcode_tool(project: Project):
    @tool
    def viewcode(ref: str, path: str, startline: int, endline: int) -> str:
        """
        View a file from a specific ref of the target repository. Lines between startline and endline are shown.
        """
        is_cross_repo = hasattr(project, "target_dir") and project.target_dir != project.dir
        target_ref = getattr(project, "target_release", None)
        source_ref = getattr(project, "new_patch_parent", None)
        if is_cross_repo and target_ref and ref != target_ref:
            # If caller passed a source ref (e.g., new_patch_parent), auto route
            # to source repo file view for source-context understanding.
            is_source_ref = False
            if source_ref and ref == source_ref:
                is_source_ref = True
            else:
                try:
                    project.repo.commit(ref)
                    project.target_repo.commit(ref)
                    is_source_ref = False
                except Exception:
                    try:
                        project.repo.commit(ref)
                        is_source_ref = True
                    except Exception:
                        is_source_ref = False

            if is_source_ref:
                source_text = project._viewcode_source(
                    ref, path, startline, endline, strict_ref=True
                )
                return "[AUTO-ROUTED to source repo]\n" + source_text

            return (
                f"Cross-repo mode detected. viewcode expects target ref {target_ref} "
                f"for target context, or a valid source ref for source context, but got {ref}."
            )
        # Pre-check: if path is a directory in target repo, fail fast with guidance
        try:
            resolved_ref = project._resolve_target_ref(ref, strict=True)
        except ValueError as e:
            return (
                f"{e}\n"
                "Tip: in cross-repo mode, pass target_release as ref for "
                "locate_symbol/viewcode/validate."
            )
        try:
            entry = project.target_repo.tree(resolved_ref) / path
            if hasattr(entry, "type") and entry.type != "blob":
                return (
                    "The given path is a directory, not a file. "
                    "Please provide a file path (e.g., .../file.c) "
                    "instead of a folder path."
                )
        except Exception:
            # Fall through to _viewcode for standard error handling
            pass
        return project._viewcode(ref, path, startline, endline, strict_ref=True)

    return viewcode


def creat_locate_symbol_source_tool(project: Project):
    @tool
    def locate_symbol_source(ref: str, symbol: str) -> str:
        """
        Locate a symbol in a specific ref of the source repository.
        """
        try:
            res = project._locate_symbol(
                ref, symbol, strict_ref=True, use_target_repo=False
            )
        except ValueError as e:
            return f"{e}\nTip: use source refs (e.g., new_patch_parent) with locate_symbol_source."
        if res is not None:
            return "\n".join([f"{file}:{line}" for file, line in res])
        return f"The symbol {symbol} you are looking for does not exist in the current source ref.\n"

    return locate_symbol_source


def creat_viewcode_source_tool(project: Project):
    @tool
    def viewcode_source(ref: str, path: str, startline: int, endline: int) -> str:
        """
        View a file from a specific ref of the source repository.
        """
        try:
            resolved_ref = project._resolve_source_ref(ref, strict=True)
        except ValueError as e:
            return f"{e}\nTip: use source refs (e.g., new_patch_parent) with viewcode_source."
        try:
            entry = project.repo.tree(resolved_ref) / path
            if hasattr(entry, "type") and entry.type != "blob":
                return (
                    "The given path is a directory, not a file. "
                    "Please provide a file path (e.g., .../file.c) "
                    "instead of a folder path."
                )
        except Exception:
            pass
        return project._viewcode_source(ref, path, startline, endline, strict_ref=True)

    return viewcode_source


def create_validate_tool(project: Project):
    def validate(ref: str, patch: str) -> str:
        """
        validate a patch on a specific ref of the target repository.
        """
        validate_tool.return_direct = False
        is_cross_repo = hasattr(project, "target_dir") and project.target_dir != project.dir
        target_ref = getattr(project, "target_release", None)
        if is_cross_repo and target_ref and ref != target_ref:
            logger.warning(
                "[validate] cross-repo mode: force ref from %s to target_release=%s",
                ref,
                target_ref,
            )
            ref = target_ref

        validated_ref = ref
        fallback_ref = getattr(project, "target_release", None)

        should_fallback = False
        if not validated_ref or len(validated_ref) != 40:
            should_fallback = True
            logger.warning(
                "[validate] LLM provided invalid ref format: %s (len=%s), "
                "fallback to target_release=%s",
                validated_ref,
                len(validated_ref) if validated_ref else 0,
                fallback_ref,
            )
        else:
            try:
                project.target_repo.commit(validated_ref)
            except Exception:
                should_fallback = True
                logger.warning(
                    "[validate] LLM provided unknown ref in target repo: %s, "
                    "fallback to target_release=%s",
                    validated_ref,
                    fallback_ref,
                )

        if should_fallback and fallback_ref:
            validated_ref = fallback_ref
        elif should_fallback and not fallback_ref:
            logger.warning(
                "[validate] target_release is empty, keep original ref=%s",
                ref,
            )

        result = project._validate(validated_ref, patch)
        validate_tool.return_direct = bool(
            getattr(project, "current_file_equivalent", False)
            or (
                getattr(project, "round_succeeded", False)
                and getattr(project, "poc_succeeded", False)
            )
        )
        return result

    validate_tool = StructuredTool.from_function(
        func=validate,
        name="validate",
        description="validate a patch on a specific ref of the target repository.",
        return_direct=False,
    )
    return validate_tool


def create_git_history_tool(project: Project):
    @tool
    def git_history() -> str:
        """
        get history for lines which relate to patch hunk.
        """
        return project._git_history()

    return git_history


def create_git_show_tool(project: Project):
    @tool
    def git_show() -> str:
        """
        show change log for a specific ref
        """
        return project._git_show()

    return git_show
