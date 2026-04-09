"""
LLM 冲突解决器 - 优雅复用 do_backport 的核心逻辑

将补丁冲突解决逻辑从 backport 场景抽象为通用能力，
支持 apply-patch 等场景复用。
"""

import os
import tempfile
import shutil
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Optional, Dict, Any

from .invoke_llm import initial_agent
from ..tools.logger import logger
from ..tools.project import Project, safe_git_reset_hard


@dataclass
class ConflictResolutionResult:
    """冲突解决结果"""
    success: bool
    patch_content: Optional[str] = None
    error_message: Optional[str] = None
    iterations_used: int = 0


class LLMConflictResolver:
    """
    LLM 冲突解决器

    优雅复用 do_backport 的核心逻辑，支持多种场景：
    - backport-batch: 跨版本补丁回移植
    - apply-patch: 同版本补丁应用冲突解决
    """

    def __init__(
        self,
        api_key: str,
        provider: str = "openai",
        custom_base_url: Optional[str] = None,
        custom_model_name: Optional[str] = None,
        debug_mode: bool = False,
    ):
        self.api_key = api_key
        self.provider = provider
        self.custom_base_url = custom_base_url
        self.custom_model_name = custom_model_name
        self.debug_mode = debug_mode

        # 延迟初始化，按需创建
        self._agent_executor = None
        self._llm = None

    def _ensure_agent_initialized(self, project: Project):
        """确保 Agent 已初始化（延迟加载）"""
        if self._agent_executor is None:
            logger.info("[ConflictResolver] 初始化 LLM Agent...")
            # 使用完整工具集（5 个工具）
            self._agent_executor, self._llm = self._create_full_agent(project)

    def _create_full_agent(self, project: Project):
        """
        创建完整版 Agent，包含全部 5 个工具

        工具列表：viewcode, locate_symbol, git_history, git_show, validate
        """
        from langchain.agents import AgentExecutor, create_tool_calling_agent
        from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
        from langchain_openai import ChatOpenAI
        from .prompt import SYSTEM_PROMPT, USER_PROMPT_HUNK

        # 获取 LLM 配置
        from .invoke_llm import _get_llm_config
        base_url, model_name = _get_llm_config(
            self.provider, self.custom_base_url, self.custom_model_name
        )

        # 创建 LLM 实例
        llm = ChatOpenAI(
            temperature=0.5,
            model=model_name,
            api_key=self.api_key,
            openai_api_base=base_url,
            verbose=self.debug_mode,
        )

        # 获取完整的 5 个工具：viewcode, locate_symbol, validate, git_history, git_show
        tools = list(project.get_tools())
        logger.info(f"[ConflictResolver] 已加载 {len(tools)} 个工具: {[t.name for t in tools]}")

        # 创建提示词模板
        prompt = ChatPromptTemplate.from_messages([
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT_HUNK),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        # 创建 Agent
        agent = create_tool_calling_agent(llm, tools, prompt)
        agent_executor = AgentExecutor(
            agent=agent, tools=tools, verbose=self.debug_mode, max_iterations=30
        )

        return agent_executor, llm

    def resolve_conflict(
        self,
        repo_path: str,
        original_patch: str,
        target_branch: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ConflictResolutionResult:
        """
        解决补丁冲突

        Args:
            repo_path: 仓库路径
            original_patch: 原始补丁内容
            target_branch: 目标分支
            context: 额外上下文（如 CVE ID、commit 信息等）

        Returns:
            ConflictResolutionResult 解决结果
        """
        logger.info("[ConflictResolver] 开始解决补丁冲突")
        logger.info(f"  - 目标分支: {target_branch}")
        logger.info(f"  - 补丁长度: {len(original_patch)} 字符")

        # 创建临时 Project 对象（复用现有基础设施）
        project = self._create_temporary_project(repo_path, target_branch)

        try:
            return self._do_resolve(project, original_patch, context)
        finally:
            # 清理临时资源
            self._cleanup_project(project)

    def _create_temporary_project(self, repo_path: str, target_branch: str) -> Project:
        """
        创建临时 Project 对象

        复用 Project 类的工具方法（viewcode, validate 等）
        """
        from git import Repo as GitRepo

        # 创建临时目录作为 project_dir（用于存放补丁文件等）
        temp_dir = tempfile.mkdtemp(prefix="cvekit_conflict_resolve_")

        try:
            # 获取目标分支的 HEAD commit 作为 new_patch_parent
            # 这是 git_history 工具所需的关键参数
            repo = GitRepo(repo_path)
            try:
                # 尝试解析 target_branch 获取其 commit hash
                new_patch_parent = repo.commit(target_branch).hexsha
                logger.debug(f"[ConflictResolver] new_patch_parent 设置为: {new_patch_parent[:8]}")
            except Exception as e:
                # 如果无法解析，使用 HEAD
                new_patch_parent = repo.head.commit.hexsha
                logger.warning(f"[ConflictResolver] 无法解析 {target_branch}，使用 HEAD: {new_patch_parent[:8]}")

            # 构造最小化的 Project 配置（使用 SimpleNamespace 兼容 Project 类）
            project_config = SimpleNamespace(
                project_dir=repo_path,  # 直接使用目标仓库
                target_path=repo_path,
                project_url="",  # 不需要
                target_release=target_branch,
                target_release_name=target_branch,
                new_patch="",  # 将通过参数传入
                new_patch_parent=new_patch_parent,  # 设置为目标分支的 commit
                error_message="",
                equivalent_exists=False,
            )

            project = Project(project_config)
            project._temp_dir = temp_dir  # 保存临时目录路径用于清理

            # 确保工作区干净
            safe_git_reset_hard(project.repo)
            project.repo.git.clean("-fdx")

            # 包装 _prepare 方法，使 ctags 失败时不中断流程
            self._wrap_prepare_method(project)

            # 包装 _git_history 方法，处理跨仓库场景的容错
            self._wrap_git_history_method(project)

            return project

        except Exception:
            # 如果创建失败，清理临时目录
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

    def _wrap_prepare_method(self, project: Project):
        """
        包装 Project._prepare 方法，使 ctags 失败时只记录警告而不中断
        """
        original_prepare = project._prepare

        def safe_prepare(ref: str, use_target_repo: bool = True) -> None:
            try:
                original_prepare(ref, use_target_repo=use_target_repo)
            except Exception as e:
                logger.warning(f"[ConflictResolver] ctags 生成失败（非致命）: {str(e)}")
                logger.warning("[ConflictResolver] 继续执行，符号定位功能可能受限")
                # 初始化空的 symbol_map，避免后续代码出错
                project.symbol_map[ref] = {}

        project._prepare = safe_prepare

    def _wrap_git_history_method(self, project: Project):
        """
        包装 Project._git_history 方法，处理跨仓库场景和异常的容错
        """
        original_git_history = project._git_history

        def safe_git_history() -> str:
            try:
                return original_git_history()
            except Exception as e:
                error_msg = str(e)
                logger.warning(f"[ConflictResolver] git_history 执行失败: {error_msg}")
                # 返回友好的提示，引导 LLM 使用其他工具
                return (
                    "git_history is not available in this context. "
                    "This may happen in cross-repository scenarios or when patch parent is not set.\n"
                    "Please use `viewcode` and `locate_symbol` to analyze the code directly.\n"
                )

        project._git_history = safe_git_history

    def _cleanup_project(self, project: Project):
        """清理 Project 相关的临时资源"""
        temp_dir = getattr(project, '_temp_dir', None)
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _normalize_patch(self, patch_content: str) -> str:
        """
        规范化补丁内容，确保格式正确

        处理多个 hunk 拼接时可能产生的格式问题：
        - 合并同一文件的多个 hunk（共享文件头部）
        - 移除 chunk 之间的多余空行
        - 确保文件末尾有且仅有一个换行符
        """
        import re

        if not patch_content:
            return patch_content

        # 解析补丁，按文件分组
        # 每个文件块以 "--- a/" 开头
        file_blocks = re.split(r'(?=^--- a/)', patch_content, flags=re.MULTILINE)
        file_blocks = [b for b in file_blocks if b.strip()]

        if not file_blocks:
            return patch_content

        # 按文件路径分组
        file_patches = {}  # file_path -> {header_a, header_b, hunks: []}

        for block in file_blocks:
            lines = block.split('\n')
            if len(lines) < 3:
                continue

            # 提取文件头部
            header_a = lines[0]  # --- a/path
            header_b = lines[1] if lines[1].startswith('+++ ') else None

            if not header_a.startswith('--- ') or not header_b:
                continue

            # 提取文件路径
            file_path = header_a[6:].strip() if header_a.startswith('--- a/') else header_a[4:].strip()

            # 提取 hunk 内容（从 @@ 开始）
            hunk_start = -1
            for i, line in enumerate(lines):
                if line.startswith('@@'):
                    hunk_start = i
                    break

            if hunk_start < 0:
                continue

            hunk_content = '\n'.join(lines[hunk_start:])

            # 提取 hunk 的源位置作为去重 key（只用起始行号 X，不用行数 Y）
            # 同一位置的多次修改只保留最后一个
            hunk_header = lines[hunk_start] if hunk_start >= 0 else ''
            hunk_key = None
            if hunk_header.startswith('@@'):
                # 只提取 -X 部分作为 key（起始行号）
                import re as re_inner
                match = re_inner.search(r'@@ -(\d+)', hunk_header)
                if match:
                    hunk_key = int(match.group(1))  # 只用起始行号

            # 添加到对应文件的 hunk 列表（去重）
            if file_path not in file_patches:
                file_patches[file_path] = {
                    'header_a': header_a,
                    'header_b': header_b,
                    'hunks': {},  # 改用 dict 以便去重
                }

            # 使用 hunk_key 去重，保留最后一个（最新的）
            if hunk_key:
                file_patches[file_path]['hunks'][hunk_key] = hunk_content
            else:
                # 无法提取 key 时，使用内容 hash
                file_patches[file_path]['hunks'][hash(hunk_content)] = hunk_content

        # 重建补丁：每个文件只有一个头部，后跟所有 hunks
        result_parts = []
        for file_path, data in file_patches.items():
            file_patch = data['header_a'] + '\n' + data['header_b'] + '\n'
            # 去掉每个 hunk 末尾的换行符，然后用单个换行符连接
            # 避免产生空行（\n\n）导致 "patch fragment without header" 错误
            # data['hunks'] 现在是 dict，需要获取 values()
            # 按源代码行号排序（key 是起始行号 int）
            sorted_hunks = sorted(data['hunks'].items(), key=lambda x: x[0] if isinstance(x[0], int) else 0)
            cleaned_hunks = [h.rstrip('\n') for _, h in sorted_hunks]
            file_patch += '\n'.join(cleaned_hunks)
            result_parts.append(file_patch)

        result = '\n'.join(result_parts)

        # 清理多余空行（3个以上连续空行变成2个）
        result = re.sub(r'\n{3,}', '\n\n', result)

        # 确保以单个换行符结尾
        result = result.rstrip() + '\n'

        return result

    def _do_resolve(
        self,
        project: Project,
        original_patch: str,
        context: Optional[Dict[str, Any]],
    ) -> ConflictResolutionResult:
        """
        执行冲突解决（核心逻辑，复用 do_backport 模式）

        简化版：针对 apply-patch 场景优化，不需要 cherry-pick 等复杂逻辑
        """
        self._ensure_agent_initialized(project)

        # 保存原始补丁
        project.now_hunk = original_patch

        # 构造输入（Project 类直接暴露属性，不是通过 config 字典）
        invoke_input = {
            "project_url": getattr(project, 'project_url', ""),
            "new_patch_parent": getattr(project, 'new_patch_parent', ""),
            "new_patch": original_patch,
            "target_release": project.target_release,
            "similar_block": "",  # 可扩展：从冲突信息中提取
        }

        # 添加额外上下文
        if context:
            invoke_input.update(context)

        try:
            # 调用 Agent 解决冲突
            logger.info("[ConflictResolver] 调用 LLM Agent 解决冲突...")
            self._agent_executor.invoke(invoke_input)

            # 检查结果（简化版 Agent 直接从 succeeded_patches 提取）
            logger.info(f"[ConflictResolver] Agent 执行完成，检查补丁生成结果...")
            logger.info(f"  - round_succeeded: {project.round_succeeded}")
            logger.info(f"  - succeeded_patches 数量: {len(project.succeeded_patches) if project.succeeded_patches else 0}")
            logger.info(f"  - validated_patch: {bool(project.validated_patch)}")

            if project.round_succeeded and project.succeeded_patches:
                # 优先使用 validated_patch，否则通过 rebuild_complete_patch 重建
                resolved_patch = project.validated_patch
                if not resolved_patch and project.succeeded_patches:
                    resolved_patch = project.rebuild_complete_patch()

                if resolved_patch:
                    resolved_patch = self._normalize_patch(resolved_patch)
                    logger.info(f"[ConflictResolver] 成功生成补丁，长度: {len(resolved_patch)} 字符")
                    logger.debug(f"[ConflictResolver] 补丁内容预览:\n{resolved_patch[:500]}...")
                    return ConflictResolutionResult(
                        success=True,
                        patch_content=resolved_patch,
                        iterations_used=project.context_mismatch_times,
                    )

            # 检查是否有任何成功的补丁
            if project.succeeded_patches:
                resolved_patch = project.rebuild_complete_patch()
                if resolved_patch.strip():
                    resolved_patch = self._normalize_patch(resolved_patch)
                    logger.info(f"[ConflictResolver] 从 succeeded_patches 提取补丁，长度: {len(resolved_patch)} 字符")
                    logger.debug(f"[ConflictResolver] 补丁内容预览:\n{resolved_patch[:500]}...")
                    return ConflictResolutionResult(
                        success=True,
                        patch_content=resolved_patch,
                        iterations_used=project.context_mismatch_times,
                    )

            return ConflictResolutionResult(
                success=False,
                error_message="LLM 未能生成有效补丁",
                iterations_used=project.context_mismatch_times,
            )

        except Exception as e:
            logger.error(f"[ConflictResolver] 冲突解决失败: {str(e)}")
            return ConflictResolutionResult(
                success=False,
                error_message=str(e),
            )


# 便捷函数：快速解决冲突
def resolve_patch_conflict(
    repo_path: str,
    patch_content: str,
    target_branch: str,
    api_key: str,
    provider: str = "openai",
    custom_base_url: Optional[str] = None,
    custom_model_name: Optional[str] = None,
    debug_mode: bool = False,
    context: Optional[Dict[str, Any]] = None,
) -> ConflictResolutionResult:
    """
    快速解决补丁冲突（函数式接口）

    使用示例：
        result = resolve_patch_conflict(
            repo_path="/path/to/repo",
            patch_content=patch_content,
            target_branch="ule4-develop",
            api_key=os.getenv("API_KEY"),
            provider="deepseek",
            custom_base_url="https://api.deepseek.com",
        )
        if result.success:
            apply_patch_content(result.patch_content)
    """
    resolver = LLMConflictResolver(
        api_key=api_key,
        provider=provider,
        custom_base_url=custom_base_url,
        custom_model_name=custom_model_name,
        debug_mode=debug_mode,
    )
    return resolver.resolve_conflict(repo_path, patch_content, target_branch, context)
