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

import argparse
import datetime
import logging
import os
import shutil
import time
from types import SimpleNamespace

import git
import yaml

from .agent.invoke_llm import do_backport, initial_agent
from .check.usage import get_usage
from .tools.logger import add_file_handler, logger
from .tools.project import Project


def is_commit_valid(commit_id: str, project_dir: str):
    """
    验证指定的 commit ID 是否在项目仓库中有效。
    
    支持多种引用格式：
    - commit SHA1 哈希值
    - 本地分支名
    - 远程分支名（如 origin/branch）
    - 标签名
    - 远程引用（如 remotes/origin/branch）
    
    Args:
        commit_id (str): 要验证的 commit ID
        project_dir (str): 项目目录路径
        
    Returns:
        bool: 如果 commit 有效返回 True，否则返回 False
    """
    logger.debug(f"[is_commit_valid] 开始验证 commit ID: commit_id={commit_id}, project_dir={project_dir}")
    try:
        repo = git.Repo(project_dir)
        logger.debug(f"[is_commit_valid] Git 仓库对象创建成功: repo={repo}")
        
        # 使用 rev_parse 来解析引用，它更灵活，能够处理各种引用格式
        # 包括远程分支引用（如 remotes/origin/branch）
        try:
            full_sha = repo.git.rev_parse(commit_id)
            repo.commit(full_sha)
            return True
        except (git.exc.BadName, git.exc.GitCommandError):
            # 如果直接解析失败，尝试作为远程分支引用
            logger.debug(f"[is_commit_valid] 直接解析失败，尝试作为远程分支引用: remotes/origin/{commit_id}")
            try:
                remote_ref = f"remotes/origin/{commit_id}"
                full_sha = repo.git.rev_parse(remote_ref)
                repo.commit(full_sha)
                return True
            except (git.exc.BadName, git.exc.GitCommandError):
                # 再尝试作为本地分支引用
                logger.debug(f"[is_commit_valid] 远程分支引用失败，尝试作为本地分支引用: {commit_id}")
                try:
                    branch_ref = f"heads/{commit_id}"
                    full_sha = repo.git.rev_parse(branch_ref)
                    repo.commit(full_sha)
                    return True
                except (git.exc.BadName, git.exc.GitCommandError) as e:
                    logger.error(f"Commit id {commit_id} 无效: {e}")
                    return False
        
    except Exception as e:
        logger.error(f"[is_commit_valid] 验证过程中发生异常: {type(e).__name__}={e}")
        return False


def rev_parse_commit(commit_id: str, project_dir: str):
    """
    解析 commit ID，返回完整的 SHA1 哈希值。
    
    支持多种引用格式：
    - commit SHA1 哈希值
    - 本地分支名
    - 远程分支名（如 origin/branch）
    - 标签名
    - 远程引用（如 remotes/origin/branch）
    
    Args:
        commit_id (str): 要解析的 commit ID（可以是短哈希、标签等）
        project_dir (str): 项目目录路径
        
    Returns:
        str: 完整的 commit SHA1 哈希值，如果失败返回 False
    """
    logger.debug(f"[rev_parse_commit] 开始解析 commit ID: commit_id={commit_id}, project_dir={project_dir}")
    try:
        repo = git.Repo(project_dir)
        logger.debug(f"[rev_parse_commit] Git 仓库对象创建成功: repo={repo}")
        
        # 使用 rev_parse 来解析引用，它更灵活，能够处理各种引用格式
        # 包括远程分支引用（如 remotes/origin/branch）
        try:
            full_sha = repo.git.rev_parse(commit_id)
            logger.debug(f"[rev_parse_commit] Commit 解析成功: 原始 commit_id={commit_id}, 完整 SHA={full_sha}")
            return full_sha
        except (git.exc.BadName, git.exc.GitCommandError):
            # 如果直接解析失败，尝试作为远程分支引用
            logger.debug(f"[rev_parse_commit] 直接解析失败，尝试作为远程分支引用: remotes/origin/{commit_id}")
            try:
                remote_ref = f"remotes/origin/{commit_id}"
                full_sha = repo.git.rev_parse(remote_ref)
                logger.debug(f"[rev_parse_commit] 远程分支引用解析成功: {remote_ref} -> {full_sha}")
                return full_sha
            except (git.exc.BadName, git.exc.GitCommandError):
                # 再尝试作为本地分支引用
                logger.debug(f"[rev_parse_commit] 远程分支引用失败，尝试作为本地分支引用: {commit_id}")
                try:
                    branch_ref = f"heads/{commit_id}"
                    full_sha = repo.git.rev_parse(branch_ref)
                    logger.debug(f"[rev_parse_commit] 本地分支引用解析成功: {branch_ref} -> {full_sha}")
                    return full_sha
                except (git.exc.BadName, git.exc.GitCommandError) as e:
                    logger.error(f"[rev_parse_commit] Commit id {commit_id} 无效: {e}")
                    logger.debug(f"[rev_parse_commit] 解析失败，返回 False")
                    return False
        
    except Exception as e:
        logger.error(f"解析 commit 时发生异常: {type(e).__name__}={e}")
        return False


def load_yml(file_path: str):
    """
    从 YAML 文件加载配置，并返回 SimpleNamespace 对象。
    
    这个函数会：
    1. 读取 YAML 配置文件
    2. 解析配置项（项目名、路径、commit ID 等）
    3. 验证目录和 commit 的有效性
    4. 规范化路径格式

    Args:
        file_path (str): YAML 配置文件的路径

    Returns:
        data (SimpleNamespace): 包含所有配置数据的 SimpleNamespace 对象
    """
    logger.debug(f"[load_yml] 开始加载 YAML 配置文件: file_path={file_path}")
    
    if not os.path.exists(file_path):
        logger.error(f"[load_yml] 配置文件不存在: {file_path}")
        exit(1)
    
    with open(file_path, "r") as file:
        config = yaml.safe_load(file)
    logger.debug(f"[load_yml] YAML 文件读取成功，原始配置内容: {config}")

    data = SimpleNamespace()
    
    # 加载基本配置项
    data.project = config.get("project")
    data.project_url = config.get("project_url")
    data.project_dir = config.get("project_dir")
    data.patch_dataset_dir = config.get("patch_dataset_dir")
    data.openai_key = config.get("openai_key")
    data.tag = config.get("tag")
    data.llm_provider = config.get("llm_provider", "openai")
    data.target_path = config.get("target_path", "")
    
    logger.debug(f"[load_yml] 基本配置项加载完成:")
    logger.debug(f"  - project={data.project}")
    logger.debug(f"  - project_url={data.project_url}")
    logger.debug(f"  - project_dir={data.project_dir}")
    logger.debug(f"  - patch_dataset_dir={data.patch_dataset_dir}")
    logger.debug(f"  - tag={data.tag}")
    logger.debug(f"  - llm_provider={data.llm_provider}")
    logger.debug(f"  - openai_key={'***' + data.openai_key[-4:] if data.openai_key else 'None'} (已脱敏)")
    logger.debug(f"  - target_path={data.target_path if data.target_path else 'None (使用 project_dir)'}")

    # 加载并验证新补丁 commit
    data.new_patch = config.get("new_patch", "")
    logger.debug(f"[load_yml] new_patch 原始值: {data.new_patch}")
    if not data.new_patch or not data.new_patch:
        logger.error(
            "Please check your configuration to make sure new_patch is correct!\n"
        )
        exit(1)

    # 加载新补丁的父 commit（如果未提供，将在路径规范化后自动获取）
    data.new_patch_parent = config.get("new_patch_parent", "")
    logger.debug(f"[load_yml] new_patch_parent 原始值: {data.new_patch_parent}")

    # 加载并验证目标发布版本 commit
    data.target_release = config.get("target_release", "")
    logger.debug(f"[load_yml] target_release 原始值: {data.target_release}")
    if not data.target_release or not data.target_release:
        logger.error("Please check your configuration to make sure target_release is correct!")
        exit(1)

    # 加载错误信息（可选）
    data.error_message = config.get("error_message", "")
    if not data.error_message:
        logger.warning(
            "Dataset without error info which means that this vulnerability may not have PoC\n"
        )

    # 规范化路径格式（确保以 / 结尾）
    data.project_dir = os.path.expanduser(
        data.project_dir if data.project_dir.endswith("/") else data.project_dir + "/"
    )
    data.patch_dataset_dir = os.path.expanduser(
        data.patch_dataset_dir
        if data.patch_dataset_dir.endswith("/")
        else data.patch_dataset_dir + "/"
    )
    
    if data.target_path:
        data.target_path = os.path.expanduser(
            data.target_path if data.target_path.endswith("/") else data.target_path + "/"
        )

    # 验证目录是否存在
    if not os.path.isdir(data.project_dir):
        logger.error(f"Project directory does not exist: {data.project_dir}")
        exit(1)
    
    if not os.path.isdir(data.patch_dataset_dir):
        logger.error(
            f"Patch dataset directory does not exist: {data.patch_dataset_dir}"
        )
        exit(1)
    
    # 如果指定了 target_path，验证目标仓库是否存在
    if data.target_path:
        if not os.path.isdir(data.target_path):
            logger.error(f"Target repository directory does not exist: {data.target_path}")
            exit(1)
        try:
            git.Repo(data.target_path)
        except Exception as e:
            logger.error(f"目标路径不是有效的 Git 仓库: {data.target_path}, 错误: {e}")
            exit(1)

    # 如果未提供 new_patch_parent，尝试从 new_patch 自动获取其父 commit
    if not data.new_patch_parent:
        logger.info(f"[load_yml] new_patch_parent 未提供，尝试从 new_patch 自动获取父 commit...")
        try:
            repo = git.Repo(data.project_dir)
            # 使用 new_patch^ 获取父 commit（Git 支持 ^ 符号表示父 commit）
            parent_commit = repo.git.rev_parse(f"{data.new_patch}^")
            data.new_patch_parent = parent_commit
            logger.info(f"[load_yml] 成功从 new_patch 自动获取父 commit: {data.new_patch_parent}")
        except Exception as e:
            logger.error(f"[load_yml] 无法自动获取 new_patch_parent: {e}")
            logger.error(
                "Please check your configuration to make sure new_patch_parent is correct or new_patch is valid!\n"
            )
            exit(1)

    # 验证所有 commit 是否有效
    logger.debug(f"[load_yml] 开始验证 commit 有效性...")
    logger.debug(f"  验证 new_patch: {data.new_patch}")
    is_new_patch_valid = is_commit_valid(data.new_patch, data.project_dir)
    logger.debug(f"  验证 new_patch_parent: {data.new_patch_parent}")
    is_new_patch_parent_valid = is_commit_valid(data.new_patch_parent, data.project_dir)
    
    # target_release 应该在目标仓库中验证（如果指定了 target_path）
    target_repo_dir = data.target_path if data.target_path else data.project_dir
    logger.debug(f"  验证 target_release: {data.target_release}")
    logger.debug(f"    在仓库中验证: {target_repo_dir}")
    is_target_release_valid = is_commit_valid(data.target_release, target_repo_dir)
    
    if (
        not is_new_patch_valid
        or not is_target_release_valid
        or not is_new_patch_parent_valid
    ):
        logger.error(f"[load_yml] 部分 commit 验证失败，退出程序")
        exit(1)
    logger.debug(f"[load_yml] 所有 commit 验证通过")

    # 解析 commit 为完整 SHA1
    logger.debug(f"[load_yml] 开始解析 commit 为完整 SHA1...")
    original_new_patch = data.new_patch
    data.new_patch = rev_parse_commit(data.new_patch, data.project_dir)
    logger.debug(f"[load_yml] new_patch: {original_new_patch} -> {data.new_patch}")
    
    original_target_release = data.target_release
    # target_release 应该在目标仓库中解析（如果指定了 target_path）
    target_repo_dir = data.target_path if data.target_path else data.project_dir
    data.target_release = rev_parse_commit(data.target_release, target_repo_dir)
    logger.debug(f"[load_yml] target_release: {original_target_release} -> {data.target_release}")
    logger.debug(f"[load_yml] target_release 在仓库中解析: {target_repo_dir}")
    
    original_new_patch_parent = data.new_patch_parent
    data.new_patch_parent = rev_parse_commit(data.new_patch_parent, data.project_dir)
    logger.debug(f"[load_yml] new_patch_parent: {original_new_patch_parent} -> {data.new_patch_parent}")

    logger.debug(f"[load_yml] 配置加载完成，最终配置对象:")
    logger.debug(f"  - data.project={data.project}")
    logger.debug(f"  - data.project_url={data.project_url}")
    logger.debug(f"  - data.project_dir={data.project_dir}")
    logger.debug(f"  - data.patch_dataset_dir={data.patch_dataset_dir}")
    logger.debug(f"  - data.tag={data.tag}")
    logger.debug(f"  - data.llm_provider={data.llm_provider}")
    logger.debug(f"  - data.new_patch={data.new_patch}")
    logger.debug(f"  - data.new_patch_parent={data.new_patch_parent}")
    logger.debug(f"  - data.target_release={data.target_release}")
    logger.debug(f"  - data.error_message={data.error_message}")

    return data


def load_config_from_dict(config_dict: dict):
    """
    从配置字典加载配置，并返回 SimpleNamespace 对象。
    
    这个函数与 load_yml 类似，但直接从字典加载配置，而不是从文件。
    
    Args:
        config_dict (dict): 配置字典
        
    Returns:
        data (SimpleNamespace): 包含所有配置数据的 SimpleNamespace 对象
    """
    logger.debug(f"[load_config_from_dict] 开始从字典加载配置")
    
    data = SimpleNamespace()
    
    # 加载基本配置项
    data.project = config_dict.get("project", "linux")
    data.project_url = config_dict.get("project_url", "")
    data.project_dir = config_dict.get("project_dir")
    data.patch_dataset_dir = config_dict.get("patch_dataset_dir", os.path.join(os.path.expanduser("~"), "backports/patch_dataset"))
    data.openai_key = config_dict.get("openai_key", "")
    data.tag = config_dict.get("tag", "unknown")
    data.llm_provider = config_dict.get("llm_provider", "openai")
    data.target_path = config_dict.get("target_path", "")
    
    # 加载并验证新补丁 commit
    data.new_patch = config_dict.get("new_patch", "")
    if not data.new_patch:
        logger.error("Please check your configuration to make sure new_patch is correct!")
        raise ValueError("new_patch is required")
    
    # 加载新补丁的父 commit（如果未提供，将在路径规范化后自动获取）
    data.new_patch_parent = config_dict.get("new_patch_parent", "")
    
    # 加载并验证目标发布版本 commit
    data.target_release = config_dict.get("target_release", "")
    if not data.target_release:
        logger.error("Please check your configuration to make sure target_release is correct!")
        raise ValueError("target_release is required")
    
    # 加载错误信息（可选）
    data.error_message = config_dict.get("error_message", "")
    if not data.error_message:
        logger.warning("Dataset without error info which means that this vulnerability may not have PoC")
    
    # 规范化路径格式（确保以 / 结尾）
    data.project_dir = os.path.expanduser(
        data.project_dir if data.project_dir.endswith("/") else data.project_dir + "/"
    )
    data.patch_dataset_dir = os.path.expanduser(
        data.patch_dataset_dir
        if data.patch_dataset_dir.endswith("/")
        else data.patch_dataset_dir + "/"
    )
    
    if data.target_path:
        data.target_path = os.path.expanduser(
            data.target_path if data.target_path.endswith("/") else data.target_path + "/"
        )
    
    # 验证目录是否存在
    if not os.path.isdir(data.project_dir):
        logger.error(f"Project directory does not exist: {data.project_dir}")
        raise ValueError(f"Project directory does not exist: {data.project_dir}")
    
    os.makedirs(data.patch_dataset_dir, exist_ok=True)
    
    if data.target_path:
        if not os.path.isdir(data.target_path):
            logger.error(f"Target repository directory does not exist: {data.target_path}")
            raise ValueError(f"Target repository directory does not exist: {data.target_path}")
        try:
            target_repo = git.Repo(data.target_path)
        except Exception as e:
            logger.error(f"Target path is not a valid Git repository: {data.target_path}, error: {e}")
            raise ValueError(f"Target path is not a valid Git repository: {data.target_path}")
    
    # 如果未提供 new_patch_parent，尝试从 new_patch 自动获取其父 commit
    if not data.new_patch_parent:
        logger.info("new_patch_parent not provided, trying to get parent commit from new_patch...")
        try:
            repo = git.Repo(data.project_dir)
            parent_commit = repo.git.rev_parse(f"{data.new_patch}^")
            data.new_patch_parent = parent_commit
            logger.info(f"Successfully got parent commit from new_patch: {data.new_patch_parent}")
        except Exception as e:
            logger.error(f"Unable to automatically get new_patch_parent: {e}")
            raise ValueError("Please check your configuration to make sure new_patch_parent is correct or new_patch is valid!")
    
    # 验证所有 commit 是否有效
    is_new_patch_valid = is_commit_valid(data.new_patch, data.project_dir)
    is_new_patch_parent_valid = is_commit_valid(data.new_patch_parent, data.project_dir)
    
    target_repo_dir = data.target_path if data.target_path else data.project_dir
    is_target_release_valid = is_commit_valid(data.target_release, target_repo_dir)
    
    if not is_new_patch_valid or not is_target_release_valid or not is_new_patch_parent_valid:
        logger.error("Some commit validation failed")
        raise ValueError("Some commit validation failed")
    
    # 解析 commit 为完整 SHA1
    original_new_patch = data.new_patch
    data.new_patch = rev_parse_commit(data.new_patch, data.project_dir)
    
    original_target_release = data.target_release
    target_repo_dir = data.target_path if data.target_path else data.project_dir
    data.target_release = rev_parse_commit(data.target_release, target_repo_dir)
    
    original_new_patch_parent = data.new_patch_parent
    data.new_patch_parent = rev_parse_commit(data.new_patch_parent, data.project_dir)
    
    logger.debug(f"Configuration loaded from dict:")
    logger.debug(f"  - project={data.project}")
    logger.debug(f"  - new_patch={data.new_patch}")
    logger.debug(f"  - target_release={data.target_release}")
    
    return data


def run_backport_from_config(config_dict: dict, debug_mode: bool = False):
    """
    从配置字典运行补丁回移植流程。
    
    Args:
        config_dict (dict): 配置字典
        debug_mode (bool): 是否启用调试模式
        
    Returns:
        dict: 执行结果
    """
    logger.debug("=" * 80)
    logger.debug("[run_backport_from_config] 开始执行补丁回移植")
    logger.debug("=" * 80)
    
    # 设置日志级别
    if debug_mode:
        logger.setLevel(logging.DEBUG)
    
    # 创建日志文件并添加文件处理器
    log_dir = os.path.join(os.path.expanduser("~"), ".cvekit", "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    now = datetime.datetime.now().strftime("%m%d%H%M")
    project_name = config_dict.get("project", "linux")
    tag_name = config_dict.get("tag", "unknown")
    logfile = os.path.join(log_dir, f"{project_name}-{tag_name}-{now}.log")
    
    add_file_handler(logger, logfile)
    
    # 加载配置
    data = load_config_from_dict(config_dict)
    
    # 使用 LLM 进行补丁回移植
    project = Project(data)
    
    logger.debug("Cleaning workspace (git clean -fdx)...")
    project.repo.git.clean("-fdx")
    
    start_time = time.time()
    
    before_usage = get_usage(data.openai_key, data.llm_provider)
    
    agent_executor, llm = initial_agent(project, data.openai_key, debug_mode, data.llm_provider)
    
    # 获取原始补丁文件路径（在 try 之前，确保即使失败也能保存）
    # 优化：优先从本地 clone_dir 目录读取，避免网络请求
    original_patch_content = None
    original_patch_path = None
    
    # 尝试从本地 clone_dir 目录读取补丁文件
    # clone_dir 通常是 project_dir 的父目录
    # 注意：project_dir 可能包含尾随斜杠，需要先规范化
    clone_dir = None
    if data.project_dir:
        # 去掉尾随斜杠，然后获取父目录
        project_dir_normalized = data.project_dir.rstrip('/')
        clone_dir = os.path.dirname(project_dir_normalized)
        # 确保路径已展开（处理 ~ 符号）
        clone_dir = os.path.expanduser(clone_dir)
    
    local_patch_file = None
    if clone_dir:
        local_patch_file = os.path.join(clone_dir, f"commit_patch_{data.new_patch}.patch")
        logger.debug(f"尝试从本地文件读取补丁: {local_patch_file}")
        if os.path.exists(local_patch_file):
            try:
                with open(local_patch_file, 'r', encoding='utf-8') as f:
                    original_patch_content = f.read()
                logger.info(f"从本地文件读取原始补丁: {local_patch_file}")
                original_patch_path = os.path.join(data.patch_dataset_dir, f"original_{data.new_patch}.patch")
                # 复制到 patch_dataset_dir 目录
                with open(original_patch_path, 'w', encoding='utf-8') as f:
                    f.write(original_patch_content)
                logger.info(f"原始补丁文件已保存: {original_patch_path}")
            except Exception as e:
                logger.warning(f"读取本地补丁文件失败: {str(e)}，将尝试从网络获取")
                original_patch_content = None
    
    # 如果本地文件不存在或读取失败，从网络获取
    if not original_patch_content:
        from .patch import getUrlText
        original_patch_url = f'https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id={data.new_patch}'
        try:
            logger.info(f"从网络获取原始补丁: {original_patch_url}")
            original_patch_content = getUrlText(original_patch_url)
            original_patch_path = os.path.join(data.patch_dataset_dir, f"original_{data.new_patch}.patch")
            with open(original_patch_path, 'w', encoding='utf-8') as f:
                f.write(original_patch_content)
            logger.info(f"原始补丁文件已保存: {original_patch_path}")
        except Exception as e:
            logger.warning(f"从网络获取或保存原始补丁文件失败: {str(e)}")
    
    try:
        logger.debug("=" * 80)
        logger.debug("Starting patch backporting...")
        logger.debug("=" * 80)
        do_backport(agent_executor, project, data, llm, logfile)
        
        end_time = time.time()
        
        # 对于 OpenAI 提供商，等待 API 使用量统计更新（可能有延迟）
        # 对于其他提供商（如 deepseek），无需等待
        if data.llm_provider == "openai":
            logger.debug("等待 API 使用量统计更新...")
            time.sleep(10)
        
        after_usage = get_usage(data.openai_key, data.llm_provider)
        
        # 获取调整后的补丁文件
        backported_patch_path = None
        diff_path = None
        
        if project.succeeded_patches:
            # 保存调整后的补丁文件
            backported_patch_path = os.path.join(
                data.patch_dataset_dir, f"backported_{data.tag}_{data.target_release}.patch"
            )

            def _normalize_unified_diff(patch_text: str) -> str:
                """
                Ensure unified diff lines are properly prefixed.

                Some model-generated patches miss the leading ' ' on context
                lines (e.g., lines starting with tabs), which makes git apply
                treat the patch as corrupt. This normalizes those lines.
                """
                out_lines = []
                for line in patch_text.splitlines():
                    if (
                        line.startswith("diff --git ")
                        or line.startswith("index ")
                        or line.startswith("--- ")
                        or line.startswith("+++ ")
                        or line.startswith("@@")
                        or line.startswith("+")
                        or line.startswith("-")
                        or line.startswith(" ")
                        or line.startswith("\\ No newline at end of file")
                    ):
                        out_lines.append(line)
                    else:
                        out_lines.append(" " + line)
                return "\n".join(out_lines)

            normalized_patches = []
            for patch in project.succeeded_patches:
                if patch and not patch.endswith("\n"):
                    patch = patch + "\n"
                normalized_patches.append(_normalize_unified_diff(patch))

            export_patch = project.validated_patch or "\n".join(normalized_patches)
            # 防呆：导出前先做 git apply --check
            try:
                project._check_patch(export_patch, data.target_release)
            except Exception as e:
                logger.error(f"导出补丁前 git apply --check 失败: {e}")
                raise RuntimeError("backported patch failed git apply --check")

            with open(backported_patch_path, 'w', encoding='utf-8') as f:
                f.write(export_patch)
            
            # 生成 diff 文件显示差异
            import difflib
            diff_path = os.path.join(data.patch_dataset_dir, f"diff_{data.tag}_{data.target_release}.diff")
            original_lines = original_patch_content.splitlines(keepends=True)
            backported_lines = export_patch.splitlines(keepends=True)
            
            diff = difflib.unified_diff(
                original_lines,
                backported_lines,
                fromfile=f"original_{data.new_patch}.patch",
                tofile=f"backported_{data.tag}_{data.target_release}.patch",
                lineterm=''
            )
            
            with open(diff_path, 'w', encoding='utf-8') as f:
                f.writelines(diff)
            
            logger.info(f"原始补丁文件: {original_patch_path}")
            logger.info(f"调整后补丁文件: {backported_patch_path}")
            logger.info(f"差异文件: {diff_path}")
        
        result = {
            'status': 'success',
            'logfile': logfile,
            'time_cost': int(end_time - start_time),
            'original_patch_path': original_patch_path,
            'backported_patch_path': backported_patch_path,
            'diff_path': diff_path
        }
        
        if data.llm_provider == "openai":
            total_cost = after_usage['total_cost'] - before_usage['total_cost']
            total_tokens = after_usage['total_consume_tokens'] - before_usage['total_consume_tokens']
            result['cost'] = total_cost
            result['tokens'] = total_tokens
            logger.info(f"This patch total cost: ${total_cost:.2f}")
            logger.info(f"This patch total consume tokens: {total_tokens/1000}(k)")
        
        logger.info(f"This patch total cost time: {int(end_time - start_time)} Seconds.")
        
        return result
        
    except KeyboardInterrupt:
        logger.debug("KeyboardInterrupt detected, calculating usage!")
        end_time = time.time()
        after_usage = get_usage(data.openai_key, data.llm_provider)
        
        result = {
            'status': 'interrupted',
            'logfile': logfile,
            'time_cost': int(end_time - start_time),
            'original_patch_path': original_patch_path
        }
        
        if data.llm_provider == "openai":
            total_cost = after_usage['total_cost'] - before_usage['total_cost']
            total_tokens = after_usage['total_consume_tokens'] - before_usage['total_consume_tokens']
            result['cost'] = total_cost
            result['tokens'] = total_tokens
        
        return result
        
    except Exception as e:
        logger.error(f"Error during execution: {type(e).__name__}={e}")
        logger.debug("Exception stack trace:", exc_info=True)
        return {
            'status': 'failed',
            'error': str(e),
            'logfile': logfile,
            'original_patch_path': original_patch_path
        }
    
    finally:
        # 复制日志文件到补丁数据集目录
        try:
            shutil.copy(logfile, data.patch_dataset_dir)
        except Exception as e:
            logger.warning(f"Failed to copy log file: {e}")


def main():
    """
    主函数：协调整个补丁回移植流程。
    
    流程包括：
    1. 解析命令行参数
    2. 加载配置文件
    3. 初始化日志系统
    4. 创建项目对象并清理工作区
    5. 初始化 LLM 代理
    6. 执行补丁回移植
    7. 统计使用量和耗时
    8. 保存日志文件
    """
    logger.debug("=" * 80)
    logger.debug("[main] 程序开始执行")
    logger.debug("=" * 80)
    
    # 处理命令行参数
    logger.debug("[main] 开始解析命令行参数...")
    parser = argparse.ArgumentParser(
        description="Backports patch with the help of LLM",
        usage="%(prog)s --config CONFIG.yml\ne.g.: python %(prog)s --config CVE-examaple.yml",
    )
    parser.add_argument(
        "-c", "--config", type=str, required=True, help="CVE config yml"
    )
    parser.add_argument("-d", "--debug", action="store_true", help="enable debug mode")
    args = parser.parse_args()
    debug_mode = args.debug
    config_file = args.config
    
    logger.debug(f"[main] 命令行参数解析完成:")
    logger.debug(f"  - config_file={config_file}")
    logger.debug(f"  - debug_mode={debug_mode}")
    
    # 设置日志级别
    if debug_mode:
        logger.setLevel(logging.DEBUG)
        logger.debug("[main] 日志级别设置为 DEBUG")
    else:
        logger.setLevel(logging.INFO)
        logger.debug("[main] 日志级别设置为 INFO")

    # 先读取配置文件的基本信息（project 和 tag），用于创建日志文件
    # 这样可以在 load_yml() 之前就添加文件处理器，确保所有日志都被保存
    logger.debug("[main] 预读取配置文件以获取日志文件名...")
    if not os.path.exists(config_file):
        logger.error(f"[main] 配置文件不存在: {config_file}")
        exit(1)
    
    with open(config_file, "r") as f:
        pre_config = yaml.safe_load(f)
    project_name = pre_config.get("project", "unknown")
    tag_name = pre_config.get("tag", "unknown")
    logger.debug(f"[main] 预读取配置完成: project={project_name}, tag={tag_name}")
    
    # 创建日志文件并添加文件处理器（在 load_yml() 之前）
    log_dir = "../logs"
    logger.debug(f"[main] 准备创建日志目录: {log_dir}")
    os.makedirs(log_dir, exist_ok=True)
    logger.debug(f"[main] 日志目录准备完成: {log_dir}")
    
    now = datetime.datetime.now().strftime("%m%d%H%M")
    logger.debug(f"[main] 当前时间戳: {now}")
    logfile = os.path.join(log_dir, f"{project_name}-{tag_name}-{now}.log")
    logger.debug(f"[main] 日志文件路径: {logfile}")
    
    add_file_handler(logger, logfile)
    logger.debug(f"[main] 文件日志处理器已添加: {logfile}")

    # 加载并检查配置
    logger.debug("[main] 开始加载配置文件...")
    data = load_yml(config_file)
    logger.debug(f"[main] 配置文件加载完成，data 对象类型: {type(data)}")

    # 使用 LLM 进行补丁回移植
    logger.debug("[main] 开始初始化项目对象...")
    project = Project(data)
    logger.debug(f"[main] 项目对象创建成功: project={project}")
    logger.debug(f"[main] 项目仓库路径: {project.repo.working_dir if hasattr(project, 'repo') else 'N/A'}")
    
    logger.debug("[main] 清理工作区（git clean -fdx）...")
    project.repo.git.clean("-fdx")
    logger.debug("[main] 工作区清理完成")
    
    start_time = time.time()
    logger.debug(f"[main] 开始时间记录: start_time={start_time}")
    
    logger.debug(f"[main] 获取 LLM 使用量统计（回移植前）...")
    logger.debug(f"  - openai_key={'***' + data.openai_key[-4:] if data.openai_key else 'None'} (已脱敏)")
    logger.debug(f"  - llm_provider={data.llm_provider}")
    before_usage = get_usage(data.openai_key, data.llm_provider)
    logger.debug(f"[main] 回移植前使用量统计: {before_usage}")
    
    logger.debug("[main] 初始化 LLM 代理...")
    logger.debug(f"  参数: project={project}, openai_key={'***' + data.openai_key[-4:] if data.openai_key else 'None'}, debug_mode={debug_mode}, llm_provider={data.llm_provider}")
    agent_executor, llm = initial_agent(project, data.openai_key, debug_mode, data.llm_provider)
    logger.debug(f"[main] LLM 代理初始化完成:")
    logger.debug(f"  - agent_executor={agent_executor}")
    logger.debug(f"  - llm={llm}")
    
    try:
        logger.debug("=" * 80)
        logger.debug("[main] 开始执行补丁回移植...")
        logger.debug("=" * 80)
        logger.debug(f"  参数: agent_executor={agent_executor}, project={project}, data={data}, llm={llm}, logfile={logfile}")
        do_backport(agent_executor, project, data, llm, logfile)
        logger.debug("[main] 补丁回移植执行完成")
        
        end_time = time.time()
        logger.debug(f"[main] 结束时间记录: end_time={end_time}")
        logger.debug(f"[main] 总耗时: {end_time - start_time:.2f} 秒")
        
        # 对于 OpenAI 提供商，等待 API 使用量统计更新（可能有延迟）
        # 对于其他提供商（如 deepseek），无需等待
        if data.llm_provider == "openai":
            logger.debug("[main] 等待 10 秒后获取最终使用量统计...")
            time.sleep(10)
        
        logger.debug("[main] 获取 LLM 使用量统计（回移植后）...")
        after_usage = get_usage(data.openai_key, data.llm_provider)
        logger.debug(f"[main] 回移植后使用量统计: {after_usage}")
        
        if data.llm_provider == "openai":
            total_cost = after_usage['total_cost'] - before_usage['total_cost']
            total_tokens = after_usage['total_consume_tokens'] - before_usage['total_consume_tokens']
            logger.debug(f"[main] 使用量对比:")
            logger.debug(f"  - 回移植前总成本: ${before_usage['total_cost']:.2f}")
            logger.debug(f"  - 回移植后总成本: ${after_usage['total_cost']:.2f}")
            logger.debug(f"  - 本次补丁总成本: ${total_cost:.2f}")
            logger.debug(f"  - 回移植前总 token: {before_usage['total_consume_tokens']}")
            logger.debug(f"  - 回移植后总 token: {after_usage['total_consume_tokens']}")
            logger.debug(f"  - 本次补丁总消耗 tokens: {total_tokens/1000}(k)")
            logger.debug(
                f"This patch total cost: ${total_cost:.2f}"
            )
            logger.debug(
                f"This patch total consume tokens: {total_tokens/1000}(k)"
            )
        else:
            logger.debug(
                f"Usage statistics not available for provider: {data.llm_provider}"
            )
        logger.debug(
            f"This patch total cost time: {int(end_time - start_time)} Seconds."
        )
    except KeyboardInterrupt:
        logger.debug("[main] 检测到 KeyboardInterrupt，开始计算使用量!")
        end_time = time.time()
        logger.debug(f"[main] 结束时间记录: end_time={end_time}")
        logger.debug(f"[main] 总耗时: {end_time - start_time:.2f} 秒")

        logger.debug("[main] 获取 LLM 使用量统计（中断后）...")
        after_usage = get_usage(data.openai_key, data.llm_provider)
        logger.debug(f"[main] 中断后使用量统计: {after_usage}")
        
        if data.llm_provider == "openai":
            total_cost = after_usage['total_cost'] - before_usage['total_cost']
            total_tokens = after_usage['total_consume_tokens'] - before_usage['total_consume_tokens']
            logger.debug(f"[main] 使用量对比:")
            logger.debug(f"  - 回移植前总成本: ${before_usage['total_cost']:.2f}")
            logger.debug(f"  - 中断后总成本: ${after_usage['total_cost']:.2f}")
            logger.debug(f"  - 本次补丁总成本: ${total_cost:.2f}")
            logger.debug(f"  - 回移植前总 token: {before_usage['total_consume_tokens']}")
            logger.debug(f"  - 中断后总 token: {after_usage['total_consume_tokens']}")
            logger.debug(f"  - 本次补丁总消耗 tokens: {total_tokens/1000}(k)")
            logger.debug(
                f"This patch total cost: ${total_cost:.2f}"
            )
            logger.debug(
                f"This patch total consume tokens: {total_tokens/1000}(k)"
            )
        else:
            logger.debug(
                f"Usage statistics not available for provider: {data.llm_provider}"
            )
        logger.debug(
            f"This patch total cost time: {int(end_time - start_time)} Seconds."
        )
    except Exception as e:
        logger.error(f"[main] 执行过程中发生异常: {type(e).__name__}={e}")
        logger.debug(f"[main] 异常堆栈:", exc_info=True)
        raise

    logger.debug(f"[main] 复制日志文件到补丁数据集目录...")
    logger.debug(f"  源文件: {logfile}")
    logger.debug(f"  目标目录: {data.patch_dataset_dir}")
    shutil.copy(logfile, data.patch_dataset_dir)
    logger.debug(f"[main] 日志文件复制完成")
    
    logger.debug("=" * 80)
    logger.debug("[main] 程序执行完成")
    logger.debug("=" * 80)


if __name__ == "__main__":
    main()

#                    Version A           Version A(Fixed)
#   ┌───┐            ┌───┐             ┌───┐
#   │   ├───────────►│   ├────────────►│   │
#   └─┬─┘            └───┘             └───┘
#     │
#     │
#     │
#     │              Version B
#     │              ┌───┐
#     └─────────────►│   ├────────────► ??
#                    └───┘
