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


def _clean_config_value(value: str | None) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value or value.lower() in {"none", "null"}:
        return None
    return value


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
    custom_base_url = _clean_config_value(custom_base_url)
    custom_model_name = _clean_config_value(custom_model_name)
    provider = _clean_config_value(provider)

    # 只有调用方没有显式 provider 时，才使用环境变量兜底，避免父进程环境覆盖 MCP 参数。
    env_provider = _clean_config_value(os.getenv("LLM_PROVIDER"))
    if not provider and env_provider:
        logger.debug(
            f"[_get_llm_config] 使用环境变量 LLM_PROVIDER 作为 provider: {env_provider}"
        )
        provider = env_provider
    elif provider and env_provider and provider.lower() != env_provider.lower():
        logger.debug(
            f"[_get_llm_config] 忽略环境变量 LLM_PROVIDER={env_provider}，"
            f"优先使用显式 provider={provider}"
        )

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
            "model": "MiniMax-M2.7-highspeed",
        },
        # 兼容别名：minimaxi -> minimax
        "minimaxi": {
            "base_url": "https://api.minimaxi.com/v1",
            "model": "MiniMax-M2.7-highspeed",
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
    env_base_url = _clean_config_value(os.getenv("LLM_BASE_URL"))
    env_model_name = (
        _clean_config_value(os.getenv("LLM_MODEL_NAME"))
        or _clean_config_value(os.getenv("MODEL_NAME"))
        or _clean_config_value(os.getenv("DEFAULT_MODEL_TYPE"))
    )

    # 确定是否使用自定义配置
    use_custom = custom_base_url or custom_model_name or env_base_url or env_model_name or provider not in configs

    if use_custom and (custom_base_url or env_base_url or custom_model_name or env_model_name):
        # 使用自定义配置：优先级 参数 > 环境变量
        if custom_base_url:
            base_url = custom_base_url
        elif env_base_url:
            base_url = env_base_url
        elif provider in configs:
            base_url = configs[provider]["base_url"]
        else:
            # 如果没有自定义 base_url，使用 openai 的默认值
            base_url = configs.get("openai", {}).get("base_url", "https://api.openai.com/v1")

        if custom_model_name:
            model_name = custom_model_name
        elif env_model_name:
            model_name = env_model_name
        elif provider in configs:
            model_name = configs[provider]["model"]
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

    if not base_url or not base_url.startswith(("http://", "https://")):
        raise ValueError(
            f"Invalid LLM base_url for provider={provider}: {base_url!r}. "
            "Set --llm-base-url or LLM_BASE_URL to a full URL with http:// or https://."
        )
    if not model_name:
        raise ValueError(
            f"Invalid LLM model_name for provider={provider}: {model_name!r}. "
            "Set --llm-model-name, LLM_MODEL_NAME, or MODEL_NAME."
        )
    
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
    tools_from_project = list(project.get_tools())
    if len(tools_from_project) < 5:
        raise RuntimeError(
            f"project.get_tools() returned {len(tools_from_project)} tools, expected at least 5"
        )
    viewcode = tools_from_project[0]
    locate_symbol = tools_from_project[1]
    validate = tools_from_project[-3]
    git_history = tools_from_project[-2]
    git_show = tools_from_project[-1]
    logger.debug(f"[initial_agent] 工具获取完成:")
    logger.debug(f"  - viewcode={viewcode} (类型: {type(viewcode)})")
    logger.debug(f"  - locate_symbol={locate_symbol} (类型: {type(locate_symbol)})")
    logger.debug(f"  - validate={validate} (类型: {type(validate)})")
    logger.debug(f"  - git_history={git_history} (类型: {type(git_history)})")
    logger.debug(f"  - git_show={git_show} (类型: {type(git_show)})")
    
    # Expose all available tools to the agent (including source-repo tools
    # in cross-repo backport mode).
    tools = tools_from_project
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


def _enforce_complete_patch_check_or_raise(project: Project, data) -> None:
    patch_to_check = project.validated_patch or project.rebuild_complete_patch()
    has_valid_diff_header = (
        any(marker in patch_to_check for marker in ("diff --git ", "\n--- ", "\n+++ ", "\n@@ "))
        or patch_to_check.startswith(("diff --git ", "--- ", "+++ ", "@@ "))
    )
    if not patch_to_check.strip() or not has_valid_diff_header:
        if getattr(project, "equivalent_exists", False):
            logger.info("[do_backport] 最终结果为等效存在（need not ported），跳过 git apply --check")
            return
        raise RuntimeError("empty or non-diff complete patch is not allowed as success")
    project._check_patch(patch_to_check, data.target_release)


def _sync_patch_dataset_to_target(project: Project, data) -> None:
    logger.debug("[do_backport] 清理工作区并同步 patch_dataset_dir...")
    project.target_repo.git.clean("-fdx")
    if not os.path.exists(data.patch_dataset_dir):
        logger.warning(f"[do_backport] patch_dataset_dir 不存在: {data.patch_dataset_dir}")
        return
    for file in os.listdir(data.patch_dataset_dir):
        source_path = os.path.join(data.patch_dataset_dir, file)
        target_path = os.path.join(project.target_dir, file)
        if os.path.exists(target_path):
            os.remove(target_path)
        shutil.copy2(source_path, target_path)


def _run_final_llm_fix(
    project: Project,
    data,
    llm: ChatOpenAI,
    patch: str,
    complete_patch: str,
    validate_ret: str,
    log_handler: FileCallbackHandler,
) -> None:
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT_PTACH),
            ("user", USER_PROMPT_PATCH),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
    )
    tools_from_project = list(project.get_tools())
    if len(tools_from_project) < 3:
        raise RuntimeError(
            f"project.get_tools() returned {len(tools_from_project)} tools, expected at least 3"
        )
    viewcode = tools_from_project[0]
    locate_symbol = tools_from_project[1]
    validate = tools_from_project[-3] if len(tools_from_project) >= 5 else tools_from_project[2]
    tools = [viewcode, locate_symbol, validate]
    agent = create_tool_calling_agent(llm, tools, prompt)
    final_executor = AgentExecutor(agent=agent, tools=tools, verbose=True, max_iterations=20)
    final_executor.invoke(
        {
            "project_url": data.project_url,
            "new_patch_parent": data.new_patch_parent,
            "target_release": data.target_release,
            "new_patch": patch,
            "complete_patch": complete_patch,
            "compile_ret": validate_ret,
        },
        {"callbacks": [log_handler]},
    )


def _log_backport_success(project: Project, target_release: str) -> None:
    logger.info(f"[do_backport] 成功将补丁回移植到目标发布版本 {target_release}")
    for i, patch in enumerate(project.succeeded_patches):
        logger.info(f"[do_backport] 补丁 {i+1}: {patch}")


def do_backport(
    agent_executor: AgentExecutor,
    project: Project,
    data,
    llm: ChatOpenAI,
    logfile: str,
    skip_cherry_pick: bool = False,
    source_patch_override: str | None = None,
):
    logger.debug("[do_backport] 开始执行补丁回移植")
    log_handler = FileCallbackHandler(logfile)
    patch = source_patch_override if source_patch_override is not None else project._get_patch(data.new_patch)

    cherry_pick_ok = False
    cherry_pick_patch = None
    if not skip_cherry_pick:
        cherry_pick_ok, cherry_pick_patch = _try_cherry_pick_backport(project, data)

    if cherry_pick_ok and cherry_pick_patch:
        project.all_hunks_applied_succeeded = True
        project.set_succeeded_patches([cherry_pick_patch])
        project.now_hunk = "completed"
        complete_patch = cherry_pick_patch
    else:
        file_patches = project.extract_grouped_file_patches(patch)
        ok, complete_patch = project.apply_file_patches_with_freeze(
            target_release=data.target_release,
            project_url=data.project_url,
            new_patch_parent=data.new_patch_parent,
            file_patches=file_patches,
            agent_executor=agent_executor,
            log_handler=log_handler,
            patch_dataset_dir=getattr(data, "patch_dataset_dir", None),
        )
        if not ok:
            return False

    _sync_patch_dataset_to_target(project, data)
    project.context_mismatch_times = 0
    validate_ret = project._validate(data.target_release, complete_patch)

    if project.poc_succeeded:
        _enforce_complete_patch_check_or_raise(project, data)
        _log_backport_success(project, data.target_release)
        return True

    _run_final_llm_fix(
        project=project,
        data=data,
        llm=llm,
        patch=patch,
        complete_patch=complete_patch,
        validate_ret=validate_ret,
        log_handler=log_handler,
    )
    if project.poc_succeeded:
        _enforce_complete_patch_check_or_raise(project, data)
        _log_backport_success(project, data.target_release)
        return True
    else:
        logger.error(f"[do_backport] 回移植补丁到目标发布版本 {data.target_release} 失败")
        return False
