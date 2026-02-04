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
import subprocess
import tempfile
import time
import warnings
from types import SimpleNamespace
from typing import List, Tuple

import Levenshtein
from git import Repo
from git.exc import GitCommandError
from langchain_core.tools import tool

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


def safe_git_reset_hard(repo, max_retries=3, retry_delay=1):
    """
    安全地执行 git reset --hard，自动处理 index.lock 文件问题
    
    Args:
        repo: GitPython Repo 对象
        max_retries: 最大重试次数
        retry_delay: 重试延迟（秒）
    
    Raises:
        GitCommandError: 如果所有重试都失败
    """
    for attempt in range(max_retries):
        try:
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
        self.context_mismatch_times = 0
        self.round_succeeded = False
        self.all_hunks_applied_succeeded = False
        self.compile_succeeded = False
        self.testcase_succeeded = False
        self.poc_succeeded = False
        self.symbol_map = {}
        self.now_hunk = ""
        self.now_hunk_num = 0
        self.hunk_log_info = {}
        self.add_percent = 0
        self.last_context = []
        self.validated_patch = None

    def _resolve_target_ref(self, ref: str) -> str:
        """
        Resolve a ref to a valid commit in the target repository.

        In cross-repo scenarios, the provided ref may belong to the source repo
        (e.g., new_patch_parent). If the ref does not exist in target repo,
        fallback to target_release, then HEAD.
        """
        if not ref:
            return self.target_repo.head.commit.hexsha
        try:
            self.target_repo.commit(ref)
            return ref
        except Exception:
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

    def _prepare(self, ref: str) -> None:
        """
        Prepares the project by generating a symbol map using ctags.
        
        优化：只扫描 C/C++ 源文件，大幅减少扫描时间。

        Raises:
            subprocess.CalledProcessError: If the ctags command fails.
        """
        # 优化：只扫描 C/C++ 源文件，避免扫描文档、配置文件等
        # 对于 Linux 内核等大型项目，这可以节省大量时间
        ctags = subprocess.run(
            [
                "ctags",
                "--excmd=number",
                "-R",
                "--languages=C,C++",
                "--c-kinds=+p",  # 包含函数原型
                "--c++-kinds=+p",
                "--extras=+q",  # 包含限定符
                ".",
            ],
            stdout=subprocess.PIPE,
            cwd=self.target_dir,  # 在目标仓库中生成 ctags
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        ctags.check_returncode()

        self.symbol_map[ref] = {}
        # 在目标仓库中查找 tags 文件
        with open(os.path.join(self.target_dir, "tags"), "rb") as f:
            for line in f.readlines():
                if text := line.decode("utf-8", errors="ignore"):
                    if text.startswith("!_TAG_"):
                        continue
                    try:
                        symbol, file, lineno = text.strip().split(';"')[0].split("\t")
                        lineno = int(lineno)
                        if symbol not in self.symbol_map[ref]:
                            self.symbol_map[ref][symbol] = []
                        self.symbol_map[ref][symbol].append((file, lineno))
                    except:
                        continue

    def _viewcode(self, ref: str, path: str, startline: int, endline: int) -> str:
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
        try:
            ref = self._resolve_target_ref(ref)
            # 在目标仓库中查找文件
            file = self.target_repo.tree(ref) / path
            # 目录或非文件对象直接返回提示
            if hasattr(file, "type") and file.type != "blob":
                return "The given path is not a file in this commit."
        except:
            return "This file doesn't exist in this commit."
        content = file.data_stream.read().decode("utf-8", errors="ignore")
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

    def _locate_symbol(self, ref: str, symbol: str) -> List[Tuple[str, int]] | None:
        """
        Locate a symbol in a specific ref of the target repository.

        Args:
            ref (str): The reference of the target repository.
            symbol (str): The symbol to locate.

        Returns:
            List[Tuple[str, int]] | None: File path and code lines.
        """
        # XXX: Analyzing ctags file everytime locate symbol is time-consuming.
        ref = self._resolve_target_ref(ref)
        if ref not in self.symbol_map:
            self._checkout(ref, use_target_repo=True)  # 在目标仓库中 checkout
            self._prepare(ref)

        if symbol in self.symbol_map[ref]:
            return self.symbol_map[ref][symbol]
        else:
            return None

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
            filepath = re.findall(r"--- a/(.*)", hunk)[0]
            chunks = re.findall(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@(.*)", hunk)[0]
            start_line = chunks[0]
            end_line = int(chunks[0]) + int(chunks[1]) - 1
            
            # 判断是否跨仓库（target_path 和 project_dir 是不同的仓库）
            is_cross_repo = (hasattr(self, 'target_dir') and 
                           self.target_dir != self.dir)
            
            if is_cross_repo:
                # 跨仓库场景：target_release 在目标仓库中，new_patch_parent 在源仓库中
                # 它们没有共同祖先，不能使用 merge_base
                # 只查询源仓库中从 new_patch_parent 往前的历史
                logger.debug(f"[_git_history] 跨仓库场景，只查询源仓库历史: {self.dir}")
                log_message = self.repo.git.log(
                    "--oneline",
                    f"-L {start_line},{end_line}:{filepath}",
                    f"..{self.new_patch_parent}",
                )
            else:
                # 同一仓库场景：可以使用 merge_base 找到共同祖先
                merge_base = self.repo.merge_base(
                    self.target_release, self.new_patch_parent
                )
                start_commit = merge_base[0].hexsha if merge_base else None
                log_message = self.repo.git.log(
                    "--oneline",
                    f"-L {start_line},{end_line}:{filepath}",
                    f"{start_commit}..{self.new_patch_parent}",
                )
            # save each hunk related refs
            if self.now_hunk_num not in self.hunk_log_info and log_message:
                last_context = list(utils.split_patch(log_message, False))[-1]
                (
                    _,
                    context_line_num,
                    self.last_context,
                    add_line_num,
                ) = utils.extract_context(last_context.split("\n")[3:])
                self.add_percent = add_line_num / (add_line_num + context_line_num)

                self.hunk_log_info[self.now_hunk_num] = []
                patch_list = log_message.split("\n")
                for idx, line in enumerate(patch_list):
                    if line.startswith("diff --git"):
                        sha_num = patch_list[idx - 2].split(" ")[0]
                        self.hunk_log_info[self.now_hunk_num].append(sha_num)

            ret = log_message[len(log_message) - 5001 : -1]
            ret += "\nYou need to do the following analysis based on the information in the last commit:\n"
            ret += "Analyze the code logic of the context of the patch to be ported in this commit step by step.\n"
            ret += "If code logic already existed before this commit, the patch context can be assumed to remain in a similar location. Use `locate` and `viewcode` to check your results.\n"
            ret += "If code logic were added in this commit, then you need to `git_show` for further details.\n"
            return ret

        else:
            # XXX TBD
            # JUST return each hunk related refs
            pass

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
        path = re.findall(r"--- a/(.*)", revised_patch)[0]
        revised_patch_line = revised_patch.split("\n")[3:]
        contexts, num_context, _, _ = utils.extract_context(revised_patch_line)
        lineno = -1
        lines = []
        min_distance = float("inf")

        try:
            ref = self._resolve_target_ref(ref)
            # 在目标仓库中查找文件
            file = self.target_repo.tree(ref) / path
            content = file.data_stream.read().decode("utf-8", errors="ignore")
            lines = content.split("\n")
            lineno, dist = utils.find_most_similar_block(
                contexts, lines, num_context, False
            )
        except:
            # 在目标仓库目录中查找相似文件
            similar_files = utils.find_most_similar_files(path.split("/")[-1], self.target_dir)
            for similar_file in similar_files:
                file = self.target_repo.tree(ref) / similar_file
                content = file.data_stream.read().decode("utf-8", errors="ignore")
                similar_lines = content.split("\n")
                current_line, current_dist = utils.find_most_similar_block(
                    "\n".join(contexts), similar_lines, num_context, False
                )

                if current_dist < min_distance:
                    min_distance = current_dist
                    lineno = current_line
                    path = similar_file
                    lines = similar_lines

        startline = max(lineno - 1, 0)
        endline = min(lineno + num_context, len(lines))
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
        for i, context in enumerate(revised_patch_line):
            if context.startswith(" ") or context.startswith("-"):
                if context[1:] != lines[lineno - 1 + j]:
                    differ += f"On the line {i + 4} of your patch.\n"
                    differ += f"          Your patch:{context[1:]}\n"
                    differ += f"Original source code:{lines[lineno - 1 + j]}\n"
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
                    missing_file_path.split("/")[-1], self.dir
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
        2. 修正补丁（修复行号、格式等）
        3. 尝试应用补丁
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
        logger.debug(f"  - patch 内容预览: {patch[:300]}..." if len(patch) > 300 else f"  - patch 内容: {patch}")
        
        ret = ""
        
        # 切换到目标引用（在目标仓库中）
        logger.debug(f"[_apply_hunk] 切换到目标引用: ref={ref}")
        logger.debug(f"[_apply_hunk] 使用目标仓库: {self.target_dir}")
        self._checkout(ref, use_target_repo=True)
        logger.debug(f"[_apply_hunk] 切换完成，当前 HEAD: {self.target_repo.head.commit.hexsha[:8]}")
        
        # 重置工作区（丢弃所有未提交的更改）
        logger.debug("[_apply_hunk] 重置工作区（git reset --hard）...")
        safe_git_reset_hard(self.target_repo)
        logger.debug("[_apply_hunk] 工作区重置完成")
        
        # 修正补丁（使用目标仓库的路径）
        if revise_context:
            logger.debug("[_apply_hunk] revise_context=True，输出原始补丁:")
            logger.debug("original patch:\n" + patch)
        
        logger.debug("[_apply_hunk] 开始修正补丁...")
        logger.debug(f"  参数: patch 长度={len(patch)}, target_dir={self.target_dir}, revise_context={revise_context}")
        revised_patch, fixed = utils.revise_patch(patch, self.target_dir, revise_context)
        logger.debug(f"[_apply_hunk] 补丁修正完成:")
        logger.debug(f"  - fixed={fixed} (是否进行了修正)")
        logger.debug(f"  - revised_patch 长度: {len(revised_patch)} 字符")
        logger.debug("revised patch:\n" + revised_patch)
        
        if fixed:
            logger.debug("[_apply_hunk] 补丁已修正（行号、格式等）")
        else:
            logger.debug("[_apply_hunk] 补丁无需修正")
        
        # 将修正后的补丁写入临时文件
        logger.debug("[_apply_hunk] 创建临时文件保存补丁...")
        with tempfile.NamedTemporaryFile(mode="w", delete=False) as f:
            f.write(revised_patch)
            temp_file_path = f.name
        logger.debug(f"[_apply_hunk] 临时文件创建成功: {temp_file_path}")
        logger.debug(f"Applying patch {temp_file_path}")
        
        # 尝试应用补丁（在目标仓库中）
        logger.debug("[_apply_hunk] 尝试应用补丁（git apply）...")
        logger.debug(f"[_apply_hunk] 在目标仓库中应用补丁: {self.target_dir}")
        try:
            logger.debug(f"  执行: git apply {temp_file_path} -v")
            self.target_repo.git.apply([temp_file_path], v=True)
            logger.debug("[_apply_hunk] 补丁应用成功！")
            ret += "Patch applied successfully\n"
            logger.debug(f"[_apply_hunk] 返回结果: {ret}")
            
            # 记录成功的补丁
            self.succeeded_patches.append(revised_patch)
            logger.debug(f"[_apply_hunk] 成功补丁已添加到列表，当前成功补丁数: {len(self.succeeded_patches)}")
            
            # 标记本轮成功
            self.round_succeeded = True
            logger.debug(f"[_apply_hunk] round_succeeded={self.round_succeeded}")
            
        except Exception as e:
            logger.debug(f"[_apply_hunk] 补丁应用失败，捕获异常: {type(e).__name__}")
            logger.debug(f"  - 异常对象: {e}")
            logger.debug(f"  - 异常类型: {type(e)}")
            
            # 获取异常信息
            error_stderr = ""
            if hasattr(e, 'stderr'):
                error_stderr = e.stderr
                logger.debug(f"  - stderr: {error_stderr[:500]}..." if len(error_stderr) > 500 else f"  - stderr: {error_stderr}")
            
            # 处理文件不存在错误
            if "No such file" in error_stderr:
                logger.debug("[_apply_hunk] 错误类型: 文件不存在（No such file）")
                logger.debug("File not found")
                logger.debug("[_apply_hunk] 尝试查找文件移动后的位置...")
                find_ret = self._apply_file_move_handling(ref, revised_patch)
                logger.debug(f"[_apply_hunk] 文件查找结果: {find_ret[:200]}..." if len(find_ret) > 200 else f"[_apply_hunk] 文件查找结果: {find_ret}")
                ret += find_ret
                logger.debug(f"[_apply_hunk] 返回结果已更新，当前长度: {len(ret)} 字符")
            
            # 处理补丁损坏错误
            elif "corrupt patch" in error_stderr:
                logger.debug("[_apply_hunk] 错误类型: 补丁损坏（corrupt patch）")
                logger.debug(f"  - 错误详情: {error_stderr}")
                ret = "Unexpected corrupt patch, Please carefully check your answer, especially in your call tools arguments.\n"
                logger.debug(f"[_apply_hunk] 返回补丁损坏错误信息")
                logger.debug(f"[_apply_hunk] 返回结果: {ret}")
                # raise Exception("Unexpected corrupt patch")
            
            # 处理上下文不匹配错误（最常见的情况）
            else:
                logger.debug("[_apply_hunk] 错误类型: 上下文不匹配（Context mismatch）")
                logger.debug(f"Context mismatch")
                logger.debug(f"  - 错误详情: {error_stderr[:500]}..." if len(error_stderr) > 500 else f"  - 错误详情: {error_stderr}")
                
                # 添加上下文不匹配的错误信息
                context_error_msg = "This patch does not apply because of CONTEXT MISMATCH. Context are patch lines that already exist in the file, that is, lines starting with ` ` and `-`. You should modify the error patch according to the context of older version.\n"
                ret += context_error_msg
                logger.debug(f"[_apply_hunk] 已添加上下文不匹配说明")
                
                # 获取错误处理信息（相似代码块和差异）
                logger.debug("[_apply_hunk] 调用 _apply_error_handling 获取详细错误信息...")
                logger.debug(f"  参数: ref={ref}, revised_patch 长度={len(revised_patch)}")
                block, differ = self._apply_error_handling(ref, revised_patch)
                logger.debug(f"[_apply_hunk] 错误处理信息获取完成:")
                logger.debug(f"  - block 长度: {len(block)} 字符")
                logger.debug(f"  - block 内容预览: {block[:200]}..." if len(block) > 200 else f"  - block 内容: {block}")
                logger.debug(f"  - differ 长度: {len(differ)} 字符")
                logger.debug(f"  - differ 内容预览: {differ[:200]}..." if len(differ) > 200 else f"  - differ 内容: {differ}")
                
                ret += block
                ret += "Besides, here is detailed info about how the context differs between the patch and the old version.\n"
                ret += differ
                logger.debug(f"[_apply_hunk] 返回结果已更新，当前长度: {len(ret)} 字符")
                logger.debug(f"[_apply_hunk] 返回结果预览: {ret[:500]}..." if len(ret) > 500 else f"[_apply_hunk] 返回结果: {ret}")

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
                # TODO: give feedback to LLM about which line can not be applied
                ret = f"For the patch you just generated, there was an APPLY failure during testing. Specifically there was a context mismatch in hunk {idx} across the patch, below is part of the feedback I found for you.\n"
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
            self.succeeded_patches.clear()
            self.succeeded_patches.append(complete_patch)
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
            self.succeeded_patches.clear()
            self.succeeded_patches.append(complete_patch)
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
        if self.all_hunks_applied_succeeded:
            ret = ""
            if not self.compile_succeeded:
                ret += self._compile_patch(
                    ref, patch, True if self.context_mismatch_times >= 1 else False
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
            if "need not ported" in patch:
                self.round_succeeded = True
                return "Patch applied successfully\n"

            ret = self._apply_hunk(
                ref, patch, True if self.context_mismatch_times >= 2 else False
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
        res = project._locate_symbol(ref, symbol)
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
        # Pre-check: if path is a directory in target repo, fail fast with guidance
        resolved_ref = project._resolve_target_ref(ref)
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
        return project._viewcode(ref, path, startline, endline)

    return viewcode


def create_validate_tool(project: Project):
    @tool
    def validate(ref: str, patch: str) -> str:
        """
        validate a patch on a specific ref of the target repository.
        """
        return project._validate(ref, patch)

    return validate


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

