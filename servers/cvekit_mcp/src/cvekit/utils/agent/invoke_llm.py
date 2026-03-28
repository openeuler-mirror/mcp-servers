"""
This file is based on the project "patch-backporting":
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
from typing import Optional

from langchain.agents import AgentExecutor, Agent, create_tool_calling_agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.callbacks import FileCallbackHandler
from langchain_openai import ChatOpenAI

from .prompt import (
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_PTACH,
    USER_PROMPT_HUNK,
    USER_PROMPT_PATCH,
)
from ..tools.logger import logger
from ..tools.project import Project, safe_git_reset_hard
from ..tools.utils import split_patch


def _get_llm_config(provider: str = "openai", custom_base_url: str = None, custom_model_name: str = None):
    """
    获取不同 LLM 提供商的配置信息
    
    Args:
        provider: 模型提供商，可选值: "openai", "deepseek", "siliconflow", "minimax", "local" 或任意自定义值
                  - openai      : 使用 OpenAI 官方接口，或兼容 OpenAI 的云服务
                  - deepseek    : 使用 DeepSeek 官方接口
                  - siliconflow : 使用 SiliconFlow 托管的 DeepSeek 模型
                  - minimax     : 使用 MiniMax OpenAI 兼容接口
                  - local       : 使用本地 / 自建的 OpenAI 兼容模型服务
                  - 任意其他值  : 使用 custom_base_url 和 custom_model_name 配置
        custom_base_url: 自定义 API 基础地址（可选，覆盖默认配置）
        custom_model_name: 自定义模型名称（可选，覆盖默认配置）
    
    Returns:
        tuple: (base_url, model_name) 配置元组。
        对于使用者而言，可以通过以下方式配置：
          - 环境变量 LLM_PROVIDER : "openai" / "deepseek" / "siliconflow" / "local" 或任意值
          - 环境变量 MODEL_NAME   : 模型名称（例如 "gpt-4.1"、"deepseek-ai/DeepSeek-V3" 等）
          - 环境变量 LLM_BASE_URL : API 基础地址（例如 "https://api.example.com/v1"）
          - 或通过参数 custom_base_url / custom_model_name 直接传入
    """
    # 允许通过环境变量 LLM_PROVIDER 覆盖 provider 参数
    env_provider = os.getenv("LLM_PROVIDER")
    if env_provider:
        logger.debug(
            f"[_get_llm_config] 从环境变量 LLM_PROVIDER 覆盖 provider: "
            f"{provider} -> {env_provider}"
        )
        provider = env_provider

    provider = (provider or "openai").lower()
    logger.debug(f"[_get_llm_config] 开始获取 LLM 配置: provider={provider}")
    
    configs = {
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4-turbo"
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com/v1",
            "model": "deepseek-chat"
        },
        "siliconflow": {
            "base_url": "https://api.siliconflow.cn/v1/",
            "model":"deepseek-ai/DeepSeek-V3"
        },
        "minimax": {
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M2.1",
        },
        # 兼容别名：minimaxi -> minimax
        "minimaxi": {
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M2.1",
        },
        # 本地 / 自建 OpenAI 兼容模型服务：
        # - 默认假设为 OpenAI 兼容接口（/v1/completions 或 /v1/chat/completions）
        # - 这里直接使用你现有服务常见的形式：/v1/completions
        "local": {
            # 默认本地服务按 OpenAI 兼容风格提供 /v1/chat/completions 接口，
            # 因此 base_url 直接设为 /v1，后续由 ChatOpenAI 自己拼接路径。
            # 默认模型名与本地自训练模型保持一致，仍可通过 MODEL_NAME 环境变量覆盖。
            "base_url": "http://127.0.0.1:5000/v1",
            "model": "codellama-32b-instruct",
        },
    }
    logger.debug(f"[_get_llm_config] 可用配置列表: {list(configs.keys())}")
    logger.debug(f"[_get_llm_config] 完整配置信息: {configs}")
    
    original_provider = provider

    # 优先使用自定义配置（参数或环境变量）
    env_base_url = os.getenv("LLM_BASE_URL")
    env_model_name = os.getenv("MODEL_NAME") or os.getenv("DEFAULT_MODEL_TYPE")

    # 确定是否使用自定义配置
    use_custom = custom_base_url or custom_model_name or env_base_url or env_model_name or provider not in configs

    if use_custom and (custom_base_url or env_base_url or custom_model_name or env_model_name):
        # 使用自定义配置：优先级 参数 > 环境变量
        if custom_base_url:
            base_url = custom_base_url
        elif env_base_url:
            base_url = env_base_url
        else:
            # 如果没有自定义 base_url，使用 openai 的默认值
            base_url = configs.get("openai", {}).get("base_url", "https://api.openai.com/v1")

        if custom_model_name:
            model_name = custom_model_name
        elif env_model_name:
            model_name = env_model_name
        else:
            # 如果没有自定义 model_name，使用 openai 的默认值
            model_name = configs.get("openai", {}).get("model", "gpt-4-turbo")


        logger.debug(f"[_get_llm_config] 使用自定义配置:")
        logger.debug(f"  - provider={provider} (自定义)")
        logger.debug(f"  - base_url={base_url}")
        logger.debug(f"  - model_name={model_name}")
    else:
        # 使用预设配置
        if provider not in configs:
            logger.warning(f"[_get_llm_config] 未知的提供商 '{provider}'，使用 'openai' 作为默认值")
            provider = "openai"

        base_url_raw = configs[provider]["base_url"]
        model_name_default = configs[provider]["model"]

        # 统一模型名：优先使用 MODEL_NAME，其次兼容旧的 DEFAULT_MODEL_TYPE。
        model_name = env_model_name or model_name_default

        # 规范化 base_url：
        # - 如果是 /v1/completions 或 /v1/chat/completions，则转换为根 /v1 以兼容 ChatOpenAI。
        raw_base = base_url_raw.strip()
        if "/v1/completions" in raw_base:
            prefix = raw_base.split("/v1/completions", 1)[0]
            raw_base = prefix.rstrip("/") + "/v1"
        elif "/v1/chat/completions" in raw_base:
            prefix = raw_base.split("/v1/chat/completions", 1)[0]
            raw_base = prefix.rstrip("/") + "/v1"
        base_url = raw_base.rstrip("/")

        logger.debug(f"[_get_llm_config] 使用预设配置:")
        logger.debug(f"  - provider={provider}")
        logger.debug(f"  - base_url={base_url}")
        logger.debug(f"  - model_name={model_name}")

    logger.debug(f"[_get_llm_config] 最终配置:")
    logger.debug(f"  - 原始 provider={original_provider}")
    logger.debug(f"  - base_url={base_url}")
    logger.debug(f"  - model_name={model_name}")
    logger.debug(f"[_get_llm_config] 返回配置: ({base_url}, {model_name})")
    
    return base_url, model_name


def initial_agent(
    project: Project,
    api_key: Optional[str],
    debug_mode: bool,
    provider: str = "openai",
    custom_base_url: str = None,
    custom_model_name: str = None,
) -> tuple[Agent, ChatOpenAI]:
    """
    初始化 LangChain Agent 和 LLM 模型
    
    这个函数会：
    1. 获取 LLM 提供商配置
    2. 创建 ChatOpenAI 实例
    3. 创建提示词模板
    4. 获取项目工具
    5. 创建工具调用代理
    6. 创建代理执行器
    
    Args:
        project: 项目对象
        api_key: API 密钥（用于脱敏显示）
        debug_mode: 是否启用调试模式
        provider: 模型提供商，可选值: "openai", "deepseek" 等，或任意自定义值
        custom_base_url: 自定义 API 基础地址（可选，覆盖默认配置）
        custom_model_name: 自定义模型名称（可选，覆盖默认配置）
    
    Returns:
        tuple: (agent_executor, llm) 元组
    """
    logger.debug("=" * 80)
    logger.debug("[initial_agent] 开始初始化 LangChain Agent 和 LLM 模型")
    logger.debug("=" * 80)
    logger.debug(f"[initial_agent] 输入参数:")
    logger.debug(f"  - project={project}")
    logger.debug(f"  - project 类型: {type(project)}")
    logger.debug(f"  - api_key={'***' + api_key[-4:] if api_key else 'None'} (已脱敏)")
    logger.debug(f"  - debug_mode={debug_mode}")
    logger.debug(f"  - provider={provider}")
    logger.debug(f"  - custom_base_url={custom_base_url}")
    logger.debug(f"  - custom_model_name={custom_model_name}")

    provider_lower = (provider or "openai").lower()

    # 对于非 local 提供商，如果没有显式提供 api_key，则提前给出清晰错误，避免底层报错不直观。
    # 但如果有自定义 base_url，则可能不需要 api_key（本地服务等情况）
    if not api_key and provider_lower != "local" and not custom_base_url:
        raise ValueError(
            "[initial_agent] 未提供 API Key，但当前 LLM provider 不为 'local'。"
            " 请通过配置 api_key 或环境变量 API_KEY/OPENAI_KEY 提供有效密钥，"
            "或者将 LLM_PROVIDER 设置为 'local' 以使用免鉴权本地模型。"
        )

    # local 场景或自定义 base_url 场景下允许省略 api_key，为避免底层客户端因 None 报错，这里使用占位或环境变量。
    if not api_key and (provider_lower == "local" or custom_base_url):
        api_key_env = os.getenv("API_KEY") or os.getenv("OPENAI_KEY")
        api_key = api_key_env or "EMPTY_KEY"
        logger.debug(
            "[initial_agent] provider=local 或自定义 base_url 且未显式提供 api_key，"
            "将使用占位符密钥（或环境变量）以满足客户端要求。"
        )

    # 获取 LLM 配置
    logger.debug("[initial_agent] 获取 LLM 配置...")
    base_url, model_name = _get_llm_config(provider_lower, custom_base_url, custom_model_name)
    logger.info(f"Using LLM provider: {provider_lower}, model: {model_name}, base_url: {base_url}")
    logger.debug(f"[initial_agent] LLM 配置获取完成: base_url={base_url}, model_name={model_name}")

    # 创建 LLM 实例
    logger.debug("[initial_agent] 创建 ChatOpenAI 实例...")

    # 针对 local provider，尽量对齐你现有的本地 LLM 配置（mode=instruct / max_tokens / top_p / seed / do_sample）。
    # 其它 provider 保持原来的 temperature=0.5 行为。
    if provider_lower == "local":
        temperature = 0.0
        model_kwargs = {
            "mode": "instruct",
            "max_tokens": 4096,
            "top_p": 0.5,
            "seed": 10,
            "do_sample": True,
        }
    else:
        temperature = 0.5
        model_kwargs = {}

    logger.debug(
        "[initial_agent] ChatOpenAI 参数: temperature=%s, model=%s, api_key=%s, openai_api_base=%s, verbose=%s, model_kwargs=%s",
        temperature,
        model_name,
        "***" + api_key[-4:] if api_key else "None",
        base_url,
        True,
        model_kwargs,
    )

    llm = ChatOpenAI(
        temperature=temperature,
        model=model_name,
        api_key=api_key,
        openai_api_base=base_url,
        verbose=True,
        model_kwargs=model_kwargs,
    )
    logger.debug(f"[initial_agent] ChatOpenAI 实例创建成功: llm={llm}")
    logger.debug(f"[initial_agent] LLM 对象类型: {type(llm)}")

    # 创建提示词模板
    logger.debug("[initial_agent] 创建提示词模板...")
    logger.debug(f"  - SYSTEM_PROMPT 长度: {len(SYSTEM_PROMPT)} 字符")
    logger.debug(f"  - USER_PROMPT_HUNK 长度: {len(USER_PROMPT_HUNK)} 字符")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("user", USER_PROMPT_HUNK),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    logger.debug(f"[initial_agent] 提示词模板创建成功: prompt={prompt}")
    logger.debug(f"[initial_agent] 提示词模板类型: {type(prompt)}")

    # 获取项目工具
    logger.debug("[initial_agent] 获取项目工具...")
    viewcode, locate_symbol, validate, git_history, git_show = project.get_tools()
    logger.debug(f"[initial_agent] 工具获取完成:")
    logger.debug(f"  - viewcode={viewcode} (类型: {type(viewcode)})")
    logger.debug(f"  - locate_symbol={locate_symbol} (类型: {type(locate_symbol)})")
    logger.debug(f"  - validate={validate} (类型: {type(validate)})")
    logger.debug(f"  - git_history={git_history} (类型: {type(git_history)})")
    logger.debug(f"  - git_show={git_show} (类型: {type(git_show)})")
    
    tools = [viewcode, locate_symbol, validate, git_history, git_show]
    logger.debug(f"[initial_agent] 工具列表: {[tool.name for tool in tools] if hasattr(tools[0], 'name') else 'N/A'}")
    logger.debug(f"[initial_agent] 工具数量: {len(tools)}")

    # 创建工具调用代理
    logger.debug("[initial_agent] 创建工具调用代理...")
    logger.debug(f"  参数: llm={llm}, tools={tools}, prompt={prompt}")
    agent = create_tool_calling_agent(llm, tools, prompt)
    logger.debug(f"[initial_agent] 工具调用代理创建成功: agent={agent}")
    logger.debug(f"[initial_agent] Agent 对象类型: {type(agent)}")

    # 创建代理执行器
    logger.debug("[initial_agent] 创建代理执行器...")
    logger.debug(f"  参数: agent={agent}, tools={tools}, verbose={debug_mode}, max_iterations=30")
    agent_executor = AgentExecutor(
        agent=agent, tools=tools, verbose=debug_mode, max_iterations=30
    )
    logger.debug(f"[initial_agent] 代理执行器创建成功: agent_executor={agent_executor}")
    logger.debug(f"[initial_agent] AgentExecutor 对象类型: {type(agent_executor)}")
    logger.debug(f"[initial_agent] AgentExecutor 配置: verbose={debug_mode}, max_iterations=30")

    logger.debug("[initial_agent] 初始化完成，返回 (agent_executor, llm)")
    logger.debug("=" * 80)
    return agent_executor, llm


def _try_cherry_pick_backport(project: Project, data) -> tuple[bool, Optional[str]]:
    """
    在分割补丁、调用 LLM 之前，先尝试用 git cherry-pick 将修复提交应用到 target_release。
    若 cherry-pick 成功则直接得到回移植结果，无需走分 hunk + LLM 流程。

    若目标仓库与源仓库不同（指定了 target_path），则先把 project_dir 作为 upstream
    拉取到目标仓库，再在目标仓库执行 cherry-pick。

    Returns:
        (True, complete_patch) 若 cherry-pick 成功；
        (False, None) 若冲突或失败，调用方应继续走原有分 hunk + LLM 流程。
    """
    try:
        from git.exc import GitCommandError
    except ImportError:
        GitCommandError = Exception  # type: ignore[misc, assignment]

    target_repo = project.target_repo
    fixed_commit = data.new_patch
    target_release = data.target_release
    target_release_name = getattr(data, "target_release_name", None)

    logger.debug("[_try_cherry_pick_backport] 尝试 cherry-pick: fixed_commit=%s, target_release=%s", fixed_commit, target_release)

    # 先确保目标仓库工作区干净，并同步远程分支，避免本地改动污染
    try:
        if target_repo.is_dirty(untracked_files=True):
            safe_git_reset_hard(target_repo)
            target_repo.git.clean("-fdx")
    except Exception as e:
        logger.debug("[_try_cherry_pick_backport] 清理目标仓库失败: %s", e)

    if target_release_name:
        try:
            if "origin" in [r.name for r in target_repo.remotes]:
                origin = target_repo.remotes.origin
                origin.fetch()
                origin_ref = f"origin/{target_release_name}"
                if origin_ref in [r.name for r in origin.refs]:
                    if target_release_name in [h.name for h in target_repo.heads]:
                        target_repo.git.checkout(target_release_name)
                    else:
                        target_repo.git.checkout("-b", target_release_name, origin_ref)
                    safe_git_reset_hard(target_repo)
                    target_repo.git.reset("--hard", origin_ref)
                    target_repo.git.clean("-fdx")
        except Exception as e:
            logger.debug("[_try_cherry_pick_backport] 同步远程分支失败: %s", e)

    # 若目标仓库与源仓库不是同一个，需要先把 project_dir 作为 upstream 拉取，使 fixed_commit 在 target_repo 中可见
    if target_repo != project.repo:
        upstream_url = os.path.abspath(project.dir.rstrip("/"))
        remote_name = "upstream"
        try:
            existing = [r.name for r in target_repo.remotes]
            if remote_name not in existing:
                target_repo.create_remote(remote_name, upstream_url)
                logger.debug("[_try_cherry_pick_backport] 已添加 remote %s -> %s", remote_name, upstream_url)
            target_repo.remotes[remote_name].fetch()
            logger.debug("[_try_cherry_pick_backport] 已从 upstream fetch")
        except Exception as e:
            logger.debug("[_try_cherry_pick_backport] 添加/拉取 upstream 失败: %s，跳过 cherry-pick", e)
            return False, None

    # 在目标仓库：重置、切到 target_release、再 cherry-pick fixed_commit
    try:
        safe_git_reset_hard(target_repo)
        resolved = project._resolve_target_ref(target_release)
        project._checkout(resolved, use_target_repo=True)
        logger.debug("[_try_cherry_pick_backport] 已 checkout %s", resolved)
        target_repo.git.cherry_pick(fixed_commit)
        logger.info("[_try_cherry_pick_backport] cherry-pick 成功，无需调用 LLM")
        patch = target_repo.git.show("HEAD")
        return True, patch
    except GitCommandError as e:
        logger.debug("[_try_cherry_pick_backport] cherry-pick 失败（可能有冲突）: %s", e)
        try:
            target_repo.git.cherry_pick("--abort")
        except Exception:
            pass
        return False, None
    except Exception as e:
        logger.debug("[_try_cherry_pick_backport] cherry-pick 异常: %s", e)
        try:
            target_repo.git.cherry_pick("--abort")
        except Exception:
            pass
        return False, None


def do_backport(
    agent_executor: AgentExecutor,
    project: Project,
    data,
    llm: ChatOpenAI,
    logfile: str,
    skip_cherry_pick: bool = False,
):
    """
    执行补丁回移植的主函数

    流程包括：
    0. （可选）先尝试 git cherry-pick 将 fixed_commit 应用到 target_release，成功则直接验证并返回
    1. 获取原始补丁并分割为多个 hunk
    2. 逐个尝试应用每个 hunk
    3. 如果 hunk 无法直接应用，使用 LLM 生成修复
    4. 验证所有 hunk 是否成功应用
    5. 如果有编译错误，使用 LLM 进行最终修复

    Args:
        agent_executor: LangChain 代理执行器
        project: 项目对象
        data: 配置数据对象（包含 new_patch, target_release 等）
        llm: LLM 模型对象
        logfile: 日志文件路径
        skip_cherry_pick: 是否跳过 cherry-pick 直回流程
    """
    logger.debug("=" * 80)
    logger.debug("[do_backport] 开始执行补丁回移植")
    logger.debug("=" * 80)
    logger.debug(f"[do_backport] 输入参数:")
    logger.debug(f"  - agent_executor={agent_executor} (类型: {type(agent_executor)})")
    logger.debug(f"  - project={project} (类型: {type(project)})")
    logger.debug(f"  - data={data} (类型: {type(data)})")
    logger.debug(f"  - data.new_patch={data.new_patch}")
    logger.debug(f"  - data.target_release={data.target_release}")
    logger.debug(f"  - data.new_patch_parent={data.new_patch_parent}")
    logger.debug(f"  - data.project_url={data.project_url}")
    logger.debug(f"  - llm={llm} (类型: {type(llm)})")
    logger.debug(f"  - logfile={logfile}")

    def _enforce_complete_patch_check_or_raise() -> None:
        """
        Success criteria is the full patch bundle must pass `git apply --check`.
        """
        patch_to_check = project.validated_patch or project.rebuild_complete_patch()
        has_valid_diff_header = (
            any(marker in patch_to_check for marker in ("diff --git ", "\n--- ", "\n+++ ", "\n@@ "))
            or patch_to_check.startswith(("diff --git ", "--- ", "+++ ", "@@ "))
        )
        if not patch_to_check.strip() or not has_valid_diff_header:
            if getattr(project, "equivalent_exists", False):
                logger.info(
                    "[do_backport] 最终结果为等效存在（need not ported），跳过 git apply --check"
                )
                return
            raise RuntimeError("empty or non-diff complete patch is not allowed as success")
        project._check_patch(patch_to_check, data.target_release)

    # 创建文件回调处理器
    logger.debug(f"[do_backport] 创建文件回调处理器: logfile={logfile}")
    log_handler = FileCallbackHandler(logfile)
    logger.debug(f"[do_backport] 文件回调处理器创建成功: log_handler={log_handler}")

    # 获取原始补丁
    logger.debug(f"[do_backport] 获取原始补丁: new_patch={data.new_patch}")
    patch = project._get_patch(data.new_patch)
    logger.debug(f"[do_backport] 原始补丁获取成功:")
    logger.debug(f"  - patch 长度: {len(patch)} 字符")
    logger.debug(f"  - patch 内容预览: {patch[:200]}..." if len(patch) > 200 else f"  - patch 内容: {patch}")

    # 先尝试用 cherry-pick 直接回移植，成功则跳过分 hunk + LLM
    cherry_pick_ok = False
    cherry_pick_patch = None
    if not skip_cherry_pick:
        cherry_pick_ok, cherry_pick_patch = _try_cherry_pick_backport(project, data)
        if cherry_pick_ok and cherry_pick_patch:
            project.all_hunks_applied_succeeded = True
            project.succeeded_patches = [cherry_pick_patch]
            project.now_hunk = "completed"
            complete_patch = cherry_pick_patch
            logger.debug("[do_backport] cherry-pick 成功，跳过分 hunk + LLM 流程")
    else:
        logger.debug("[do_backport] skip_cherry_pick=True，跳过 cherry-pick 直回流程")

    frozen_file_patches = []
    if skip_cherry_pick or not (cherry_pick_ok and cherry_pick_patch):
        # 分割补丁为多个 hunk，并按文件合并，确保单文件内多 hunk 组合验证
        logger.debug("[do_backport] 分割补丁并按文件聚合...")
        pps = list(split_patch(patch, True))
        logger.debug(f"[do_backport] hunk 数量: {len(pps)}")

        def _normalize_diff_chunk(pp: str) -> str:
            """
            Trim non-diff metadata (commit/author/message) and keep only unified
            diff content starting from `--- a/...` or `--- /dev/null`.
            """
            if not pp:
                return ""
            lines = pp.splitlines()
            start_idx = -1
            for i, line in enumerate(lines):
                if line.startswith("--- a/") or line.startswith("--- /dev/null"):
                    start_idx = i
                    break
            if start_idx < 0:
                return ""
            normalized = "\n".join(lines[start_idx:])
            if normalized and not normalized.endswith("\n"):
                normalized += "\n"
            return normalized

        def _file_key(pp: str) -> str:
            normalized = _normalize_diff_chunk(pp)
            old_match = re.search(r"^--- a/(.+)$", normalized, re.MULTILINE)
            if old_match:
                return old_match.group(1)
            new_match = re.search(r"^\+\+\+ b/(.+)$", normalized, re.MULTILINE)
            if new_match:
                return new_match.group(1)
            return "__unknown__"

        grouped_files = []
        grouped_index = {}
        for pp in pps:
            key = _file_key(pp)
            if key == "__unknown__":
                logger.warning("[do_backport] 跳过无法解析文件路径的 patch chunk")
                continue
            if key not in grouped_index:
                grouped_index[key] = len(grouped_files)
                grouped_files.append([key, []])
            grouped_files[grouped_index[key]][1].append(_normalize_diff_chunk(pp))

        file_patches = []
        for key, hunks in grouped_files:
            header_a = ""
            header_b = ""
            hunk_bodies = []
            header_written = False
            for hunk in hunks:
                h_lines = hunk.splitlines()
                if not h_lines:
                    continue
                if not header_written:
                    if len(h_lines) < 3:
                        continue
                    header_a = h_lines[0]
                    header_b = h_lines[1]
                    header_written = True
                # 仅拼接 hunk 体（从第一个 @@ 开始），避免重复/污染文件头
                hunk_start = -1
                for idx, line in enumerate(h_lines):
                    if line.startswith("@@"):
                        hunk_start = idx
                        break
                if hunk_start >= 0:
                    hunk_bodies.append("\n".join(h_lines[hunk_start:]))
            if header_written and hunk_bodies:
                file_patch = f"{header_a}\n{header_b}\n" + "\n".join(hunk_bodies) + "\n"
                file_patches.append((key, file_patch))

        logger.debug(f"[do_backport] 文件块数量: {len(file_patches)}")

        # 文件级处理：一个文件通过后冻结，不再重复验证
        logger.debug("=" * 80)
        logger.debug("[do_backport] 开始逐个处理文件补丁（文件级冻结）")
        logger.debug("=" * 80)
        for file_idx, (file_key, file_patch) in enumerate(file_patches):
            logger.debug("-" * 80)
            logger.debug(
                f"[do_backport] 处理文件补丁 {file_idx}/{len(file_patches)-1}: {file_key}"
            )
            logger.debug("-" * 80)

            project.round_succeeded = False
            project.context_mismatch_times = 0
            project.set_succeeded_patches(frozen_file_patches)

            ret = project._apply_hunk(data.target_release, file_patch, False)
            logger.debug(f"[do_backport] 文件补丁应用结果长度: {len(ret)}")

            if not project.round_succeeded:
                logger.debug(
                    f"[do_backport] 文件补丁 {file_key} 无法直接应用，调用 LLM 修复"
                )
                block_list = re.findall(r"older version.\n(.*?)\nBesides,", ret, re.DOTALL)
                similar_block = "\n".join(block_list)

                project.now_hunk = file_patch
                project.now_hunk_num = file_idx
                invoke_input = {
                    "project_url": data.project_url,
                    "new_patch_parent": data.new_patch_parent,
                    "new_patch": file_patch,
                    "target_release": data.target_release,
                    "similar_block": similar_block,
                }
                agent_executor.invoke(
                    invoke_input,
                    {"callbacks": [log_handler]},
                )

            if not project.round_succeeded:
                logger.error(f"[do_backport] 文件补丁 {file_key} 达到最大迭代次数")
                return

            # 当前文件通过，冻结“修正后的成功版本”，而不是原始输入版本
            frozen_patch = project.build_succeeded_patch_for_file(file_key)
            if not frozen_patch:
                logger.warning(
                    f"[do_backport] 未能从成功结果提取文件补丁，回退使用输入版本: {file_key}"
                )
                frozen_patch = file_patch
            frozen_file_patches.append(frozen_patch)
            project.set_succeeded_patches(frozen_file_patches)
            logger.debug(
                f"[do_backport] 文件补丁已冻结: {file_key}, 当前冻结数={len(frozen_file_patches)}"
            )

        # 末尾只做全量检查；若失败仅回滚最后新增文件（栈式）
        while frozen_file_patches:
            candidate_patch = "\n".join(frozen_file_patches)
            try:
                project._check_patch(candidate_patch, data.target_release)
                complete_patch = candidate_patch
                break
            except Exception as e:
                removed = frozen_file_patches.pop()
                logger.warning(
                    "[do_backport] 全量 git apply --check 失败，仅回滚最后新增文件补丁。"
                    f"剩余冻结数={len(frozen_file_patches)}; error={e}"
                )
                logger.debug(
                    f"[do_backport] 已回滚补丁长度: {len(removed)}"
                )

        if not frozen_file_patches:
            project.set_succeeded_patches([])
            project.validated_patch = ""
            logger.error("[do_backport] 全量检查后无可用冻结补丁，终止")
            return

        project.set_succeeded_patches(frozen_file_patches)
        project.all_hunks_applied_succeeded = True
        project.now_hunk = "completed"
        logger.info("[do_backport] 文件级冻结流程完成")
    else:
        frozen_file_patches = [cherry_pick_patch]
        project.set_succeeded_patches(frozen_file_patches)
        complete_patch = cherry_pick_patch
    
    # 清理工作区（在目标仓库中）
    logger.debug("[do_backport] 清理工作区（git clean -fdx）...")
    logger.debug(f"[do_backport] 在目标仓库中清理: {project.target_dir}")
    project.target_repo.git.clean("-fdx")
    logger.debug("[do_backport] 工作区清理完成")

    # 复制文件到目标仓库目录
    logger.debug("[do_backport] 复制文件从 patch_dataset_dir 到 target_dir...")
    logger.debug(f"  - patch_dataset_dir={data.patch_dataset_dir}")
    logger.debug(f"  - target_dir={project.target_dir}")
    if os.path.exists(data.patch_dataset_dir):
        files_in_dataset = os.listdir(data.patch_dataset_dir)
        logger.debug(f"  - patch_dataset_dir 中的文件数量: {len(files_in_dataset)}")
        logger.debug(f"  - 文件列表: {files_in_dataset}")
        
        for file in files_in_dataset:
            source_path = os.path.join(data.patch_dataset_dir, file)
            target_path = os.path.join(project.target_dir, file)
            logger.debug(f"  处理文件: {file}")
            logger.debug(f"    - 源路径: {source_path}")
            logger.debug(f"    - 目标路径: {target_path}")
            
            if os.path.exists(target_path):
                logger.debug(f"    目标文件已存在，删除: {target_path}")
                os.remove(target_path)
            logger.debug(f"    复制文件: {source_path} -> {target_path}")
            shutil.copy2(source_path, target_path)
            logger.debug(f"    文件复制完成")
    else:
        logger.warning(f"[do_backport] patch_dataset_dir 不存在: {data.patch_dataset_dir}")

    # 验证补丁
    logger.debug("[do_backport] 重置 context_mismatch_times...")
    project.context_mismatch_times = 0
    logger.debug(f"[do_backport] context_mismatch_times={project.context_mismatch_times}")
    
    logger.debug("[do_backport] 验证补丁...")
    logger.debug(f"  参数: target_release={data.target_release}, complete_patch 长度={len(complete_patch)} 字符")
    validate_ret = project._validate(data.target_release, complete_patch)
    logger.debug(f"[do_backport] 验证结果:")
    logger.debug(f"  - validate_ret 长度: {len(validate_ret)} 字符")
    logger.debug(f"  - validate_ret 内容: {validate_ret}")
    logger.debug(f"  - poc_succeeded={project.poc_succeeded}")
    
    if project.poc_succeeded:
        # 强制整包可 apply，失败不能宣告成功
        _enforce_complete_patch_check_or_raise()
        logger.info(
            f"[do_backport] 成功将补丁回移植到目标发布版本 {data.target_release}"
        )
        logger.debug(f"[do_backport] 成功应用的补丁列表:")
        for i, patch in enumerate(project.succeeded_patches):
            logger.info(f"[do_backport] 补丁 {i+1}: {patch}")
            logger.debug(f"  - 补丁 {i+1} 长度: {len(patch)} 字符")
        logger.debug("[do_backport] 补丁回移植完成，返回")
        return

    # 如果验证失败，使用 LLM 进行最终修复
    logger.debug("=" * 80)
    logger.debug("[do_backport] 验证失败，使用 LLM 进行最终修复")
    logger.debug("=" * 80)
    
    # 创建新的提示词模板
    logger.debug("[do_backport] 创建新的提示词模板用于最终修复...")
    logger.debug(f"  - SYSTEM_PROMPT_PTACH 长度: {len(SYSTEM_PROMPT_PTACH)} 字符")
    logger.debug(f"  - USER_PROMPT_PATCH 长度: {len(USER_PROMPT_PATCH)} 字符")
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT_PTACH),
            ("user", USER_PROMPT_PATCH),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    logger.debug(f"[do_backport] 提示词模板创建成功: prompt={prompt}")

    # 获取工具（只使用部分工具）
    logger.debug("[do_backport] 获取工具（用于最终修复）...")
    viewcode, locate_symbol, validate, _, _ = project.get_tools()
    logger.debug(f"[do_backport] 工具获取完成:")
    logger.debug(f"  - viewcode={viewcode}")
    logger.debug(f"  - locate_symbol={locate_symbol}")
    logger.debug(f"  - validate={validate}")
    
    tools = [viewcode, locate_symbol, validate]
    logger.debug(f"[do_backport] 工具列表: {[tool.name for tool in tools] if hasattr(tools[0], 'name') else 'N/A'}")
    logger.debug(f"[do_backport] 工具数量: {len(tools)}")

    # 创建新的代理和执行器
    logger.debug("[do_backport] 创建新的工具调用代理和执行器...")
    agent = create_tool_calling_agent(llm, tools, prompt)
    logger.debug(f"[do_backport] 代理创建成功: agent={agent}")
    
    agent_executor = AgentExecutor(
        agent=agent, tools=tools, verbose=True, max_iterations=20
    )
    logger.debug(f"[do_backport] 代理执行器创建成功: agent_executor={agent_executor}")
    logger.debug(f"[do_backport] AgentExecutor 配置: verbose=True, max_iterations=20")

    # 调用 LLM 进行最终修复
    logger.debug("[do_backport] 调用 LLM 进行最终修复...")
    final_invoke_input = {
        "project_url": data.project_url,
        "new_patch_parent": data.new_patch_parent,
        "target_release": data.target_release,
        "new_patch": patch,
        "complete_patch": complete_patch,
        "compile_ret": validate_ret,
    }
    logger.debug(f"[do_backport] 最终修复调用参数:")
    logger.debug(f"  - project_url={final_invoke_input['project_url']}")
    logger.debug(f"  - new_patch_parent={final_invoke_input['new_patch_parent']}")
    logger.debug(f"  - target_release={final_invoke_input['target_release']}")
    logger.debug(f"  - new_patch 长度={len(final_invoke_input['new_patch'])} 字符")
    logger.debug(f"  - complete_patch 长度={len(final_invoke_input['complete_patch'])} 字符")
    logger.debug(f"  - compile_ret 长度={len(final_invoke_input['compile_ret'])} 字符")
    logger.debug(f"  - compile_ret 内容: {final_invoke_input['compile_ret']}")
    
    logger.debug("[do_backport] 执行 agent_executor.invoke() 进行最终修复...")
    agent_executor.invoke(
        final_invoke_input,
        {"callbacks": [log_handler]},
    )
    logger.debug(f"[do_backport] 最终修复调用完成")
    logger.debug(f"[do_backport] poc_succeeded={project.poc_succeeded}")
    logger.debug(f"[do_backport] context_mismatch_times={project.context_mismatch_times}")

    # 检查最终结果
    if project.poc_succeeded:
        # 强制整包可 apply，失败不能宣告成功
        _enforce_complete_patch_check_or_raise()
        logger.info(
            f"[do_backport] 成功将补丁回移植到目标发布版本 {data.target_release}"
        )
        logger.debug(f"[do_backport] 成功应用的补丁列表:")
        for i, patch in enumerate(project.succeeded_patches):
            logger.info(f"[do_backport] 补丁 {i+1}: {patch}")
            logger.debug(f"  - 补丁 {i+1} 长度: {len(patch)} 字符")
    else:
        logger.error(
            f"[do_backport] 回移植补丁到目标发布版本 {data.target_release} 失败"
        )
        logger.debug(f"[do_backport] 失败原因: poc_succeeded={project.poc_succeeded}")
    
    logger.debug("=" * 80)
    logger.debug("[do_backport] 补丁回移植流程结束")
    logger.debug("=" * 80)
