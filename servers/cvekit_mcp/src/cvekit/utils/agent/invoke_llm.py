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
from ..tools.project import Project
from ..tools.utils import split_patch


def _get_llm_config(provider: str = "openai"):
    """
    获取不同 LLM 提供商的配置信息
    
    Args:
        provider: 模型提供商，可选值: "openai", "deepseek", "siliconflow", "minimax", "local"
                  - openai      : 使用 OpenAI 官方接口，或兼容 OpenAI 的云服务
                  - deepseek    : 使用 DeepSeek 官方接口
                  - siliconflow : 使用 SiliconFlow 托管的 DeepSeek 模型
                  - minimax     : 使用 MiniMax OpenAI 兼容接口
                  - local       : 使用本地 / 自建的 OpenAI 兼容模型服务
    
    Returns:
        tuple: (base_url, model_name) 配置元组。
        对于使用者而言，只需要配置两个环境变量：
          - LLM_PROVIDER : "openai" / "deepseek" / "siliconflow" / "local"
          - MODEL_NAME   : 模型名称（例如 "gpt-4.1"、"deepseek-ai/DeepSeek-V3" 等）
        其他环境变量不再推荐使用，仅作为向下兼容保留。
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
    if provider not in configs:
        logger.warning(f"[_get_llm_config] 未知的提供商 '{provider}'，使用 'openai' 作为默认值")
        provider = "openai"
    
    base_url_raw = configs[provider]["base_url"]
    model_name_default = configs[provider]["model"]

    # 统一模型名：优先使用 MODEL_NAME，其次兼容旧的 DEFAULT_MODEL_TYPE。
    model_name = os.getenv("MODEL_NAME") or os.getenv("DEFAULT_MODEL_TYPE") or model_name_default

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

    logger.debug(f"[_get_llm_config] 最终配置:")
    logger.debug(f"  - 原始 provider={original_provider}")
    logger.debug(f"  - 使用的 provider={provider}")
    logger.debug(f"  - base_url={base_url}")
    logger.debug(f"  - model_name={model_name}")
    logger.debug(f"[_get_llm_config] 返回配置: ({base_url}, {model_name})")
    
    return base_url, model_name


def initial_agent(
    project: Project,
    api_key: Optional[str],
    debug_mode: bool,
    provider: str = "openai",
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
        provider: 模型提供商，可选值: "openai", "deepseek"，默认为 "openai"
    
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

    provider_lower = (provider or "openai").lower()

    # 对于非 local 提供商，如果没有显式提供 api_key，则提前给出清晰错误，避免底层报错不直观。
    if not api_key and provider_lower != "local":
        raise ValueError(
            "[initial_agent] 未提供 API Key，但当前 LLM provider 不为 'local'。"
            " 请通过配置 api_key 或环境变量 API_KEY/OPENAI_KEY 提供有效密钥，"
            "或者将 LLM_PROVIDER 设置为 'local' 以使用免鉴权本地模型。"
        )

    # local 场景下允许省略 api_key，为避免底层客户端因 None 报错，这里使用占位或环境变量。
    if not api_key and provider_lower == "local":
        api_key_env = os.getenv("API_KEY") or os.getenv("OPENAI_KEY")
        api_key = api_key_env or "EMPTY_KEY"
        logger.debug(
            "[initial_agent] provider=local 且未显式提供 api_key，"
            "将使用占位符密钥（或环境变量）以满足客户端要求。"
        )

    # 获取 LLM 配置
    logger.debug("[initial_agent] 获取 LLM 配置...")
    base_url, model_name = _get_llm_config(provider_lower)
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


def do_backport(
    agent_executor: AgentExecutor, project: Project, data, llm: ChatOpenAI, logfile: str
):
    """
    执行补丁回移植的主函数
    
    流程包括：
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

    # 分割补丁为多个 hunk
    logger.debug("[do_backport] 分割补丁为多个 hunk...")
    pps_generator = split_patch(patch, True)
    logger.debug(f"[do_backport] split_patch 返回类型: {type(pps_generator)}")
    # 将生成器转换为列表，以便可以多次迭代和使用 len()
    pps = list(pps_generator)
    logger.debug(f"[do_backport] 补丁分割完成:")
    logger.debug(f"  - hunk 数量: {len(pps)}")

    # 逐个处理每个 hunk
    logger.debug("=" * 80)
    logger.debug("[do_backport] 开始逐个处理 hunk")
    logger.debug("=" * 80)
    for idx, pp in enumerate(pps):
        logger.debug("-" * 80)
        logger.debug(f"[do_backport] 处理 hunk {idx}/{len(pps)-1}")
        logger.debug("-" * 80)
        logger.debug(f"  - hunk 内容: {pp}")
        
        # 重置状态
        project.round_succeeded = False
        project.context_mismatch_times = 0
        logger.debug(f"[do_backport] 重置状态: round_succeeded={project.round_succeeded}, context_mismatch_times={project.context_mismatch_times}")

        # 尝试应用 hunk
        logger.debug(f"[do_backport] 尝试应用 hunk {idx} 到 target_release={data.target_release}")
        ret = project._apply_hunk(data.target_release, pp, False)
        logger.debug(f"[do_backport] hunk 应用结果: ret 长度={len(ret)} 字符")
        logger.debug(f"[do_backport] hunk 应用结果内容: {ret}")
        logger.debug(f"[do_backport] round_succeeded={project.round_succeeded}")
        
        if project.round_succeeded:
            logger.debug(f"[do_backport] Hunk {idx} 可以无冲突地应用，跳过")
            continue
        else:
            # 使用正则表达式提取相似代码块
            logger.debug(f"[do_backport] Hunk {idx} 无法直接应用，使用 LLM 生成修复")
            logger.debug(f"[do_backport] 从应用结果中提取相似代码块...")
            block_list = re.findall(r"older version.\n(.*?)\nBesides,", ret, re.DOTALL)
            logger.debug(f"[do_backport] 找到相似代码块数量: {len(block_list)}")
            for i, block in enumerate(block_list):
                logger.debug(f"  - 代码块 {i} 长度: {len(block)} 字符")
                logger.debug(f"  - 代码块 {i} 内容: {block[:200]}..." if len(block) > 200 else f"  - 代码块 {i} 内容: {block}")
            
            similar_block = "\n".join(block_list)
            logger.debug(f"[do_backport] 合并后的相似代码块长度: {len(similar_block)} 字符")
            logger.debug(f"[do_backport] 相似代码块内容: {similar_block[:300]}..." if len(similar_block) > 300 else f"[do_backport] 相似代码块内容: {similar_block}")

            # 设置当前处理的 hunk
            project.now_hunk = pp
            project.now_hunk_num = idx
            logger.debug(f"[do_backport] 设置当前 hunk: now_hunk_num={project.now_hunk_num}")
            logger.debug(f"[do_backport] 当前 hunk 内容: {project.now_hunk[:200]}..." if len(project.now_hunk) > 200 else f"[do_backport] 当前 hunk 内容: {project.now_hunk}")

            # 调用 LLM 代理生成修复
            logger.debug("[do_backport] 调用 LLM 代理生成修复...")
            invoke_input = {
                "project_url": data.project_url,
                "new_patch_parent": data.new_patch_parent,
                "new_patch": pp,
                "target_release": data.target_release,
                "similar_block": similar_block,
            }
            
            logger.debug("[do_backport] 执行 agent_executor.invoke()...")
            agent_executor.invoke(
                invoke_input,
                {"callbacks": [log_handler]},
            )
            logger.debug(f"[do_backport] agent_executor.invoke() 执行完成")
            logger.debug(f"[do_backport] round_succeeded={project.round_succeeded}")
            logger.debug(f"[do_backport] context_mismatch_times={project.context_mismatch_times}")
            
            if not project.round_succeeded:
                logger.debug(
                    f"[do_backport] 回移植 hunk {idx} 失败\n----------------------------------\n{pp}\n----------------------------------\n"
                )
                logger.error(f"[do_backport] Hunk {idx} 达到最大迭代次数")
                logger.debug("[do_backport] 提前返回，停止处理后续 hunk")
                return

    # 所有 hunk 应用成功
    logger.debug("=" * 80)
    logger.debug("[do_backport] 所有 hunk 处理完成")
    logger.debug("=" * 80)
    project.all_hunks_applied_succeeded = True
    logger.info(f"[do_backport] 应用补丁中的所有 hunk 成功")
    logger.debug(f"[do_backport] all_hunks_applied_succeeded={project.all_hunks_applied_succeeded}")
    
    project.now_hunk = "completed"
    logger.debug(f"[do_backport] now_hunk={project.now_hunk}")
    
    # 合并所有成功的补丁
    complete_patch = "\n".join(project.succeeded_patches)
    logger.debug(f"[do_backport] 合并后的完整补丁:")
    logger.debug(f"  - succeeded_patches 数量: {len(project.succeeded_patches)}")
    logger.debug(f"  - complete_patch 长度: {len(complete_patch)} 字符")
    logger.debug(f"  - complete_patch 内容: {complete_patch}")
    
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
