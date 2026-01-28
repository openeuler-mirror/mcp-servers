import argparse
import sys
import logging
import os
import json
import multiprocessing

from tabulate import tabulate
from .utils.gitee import parse_gitee_issue_url, setup_repository, get_issue_url_from_cve_id
from .utils.commits import get_vulnerability_commits, branch_commit_from_upstream
from .utils.branches import process_branches
from .utils.apply_patch import apply_patch
from .utils.create_pr import create_pr
from .utils.locales import i18n
from .utils.backporting import run_backport_from_config

logger = logging.getLogger(__name__)
apply_patch_lock = multiprocessing.Lock()
create_pr_lock = multiprocessing.Lock()

class IssueInfo:
    def __init__(self, issue_id, cve_id, org_name, repo_name, affected_versions, issue_url):
        self.issue_id = issue_id
        self.cve_id = cve_id
        self.org_name = org_name
        self.repo_name = repo_name
        self.affected_versions = affected_versions
        self.issue_url = issue_url
        self.introduced_commit = None
        self.fixed_commit = None

def main():
    parser = argparse.ArgumentParser(description='CVE分析和补丁适配工具')

    # 操作模式参数
    parser.add_argument('--action', type=str,
                      choices=['parse-issue', 'get-commits', 'analyze-branches', 'setup-env', 'apply-patch', 'create-pr', 'backport'],
                      default='analyze-branches',
                      help='''执行模式: 
                      parse-issue(解析issue),
                      get-commits(获取提交),
                      analyze-branches(分析分支,默认),
                      setup-env(设置仓库环境),
                      apply-patch(应用patch),
                      create-pr(创建PR),
                      backport(补丁回移植)''')


    # 输入源参数组（互斥组：必须提供CVE ID或Issue URL）
    input_group = parser.add_argument_group('输入源').add_mutually_exclusive_group(required=False)
    input_group.add_argument('--cve-id', type=str, help='CVE ID (例如: CVE-2025-38226)')
    input_group.add_argument('--issue-url', type=str, help='Gitee Issue URL')

    # 仓库环境参数
    env_group = parser.add_argument_group('仓库环境参数')
    env_group.add_argument('--fork-repo-url', type=str,
                         help='Fork仓库URL (也可通过FORK_REPO_URL环境变量设置)')
    env_group.add_argument('--repo-url', type=str,
                         help='仓库URL (也可通过REPO_URL环境变量设置)')
    env_group.add_argument('--gitee-token', type=str,
                         help='Gitee访问令牌(也可通过GITEE_TOKEN环境变量设置)')
    env_group.add_argument('--clone-dir', type=str,
                         help='克隆仓库工作目录 (也可通过CLONE_DIR环境变量设置)，仓库目录该目录下仓库名文件夹中')

    # 分支分析专用参数
    branch_group = parser.add_argument_group('分支分析参数')
    branch_group.add_argument('--branches', type=str,
                             help='要分析的分支列表，逗号分隔 (也可通过BRANCHES环境变量设置)')
    branch_group.add_argument('--signer-name', type=str,
                             help='提交者姓名 (也可通过SIGNER_NAME环境变量设置)')
    branch_group.add_argument('--signer-email', type=str,
                             help='提交者邮箱 (也可通过SIGNER_EMAIL环境变量设置)')

    # 输出控制参数
    output_group = parser.add_argument_group('输出控制')
    output_group.add_argument('--json', action='store_true', help='以JSON格式输出结果')
    output_group.add_argument('--table', action='store_true', help='以表格形式输出结果')
    output_group.add_argument('--no-cache', action='store_true', help='禁用缓存')
    output_group.add_argument('--debug', action='store_true', help='开启调试模式')

    # 提交pr参数
    pr_group = parser.add_argument_group('提交pr')
    pr_group.add_argument('--patch-path', type=str, help='patch文件路径')
    pr_group.add_argument('--branch', type=str, help='pr提交分支')

    # 补丁回移植参数
    backport_group = parser.add_argument_group('补丁回移植参数')
    backport_group.add_argument(
        '--api-key',
        type=str,
        help='LLM API 密钥 (也可通过 API_KEY 或 OPENAI_KEY 环境变量设置)'
    )
    backport_group.add_argument(
        '--llm-provider',
        type=str,
        default='openai',
        choices=['openai', 'deepseek', 'siliconflow', 'minimax', 'minimaxi', 'local'],
        help='LLM提供商 (默认: openai；当为 local 时可不提供 --api-key，用于本地免鉴权模型)',
    )
    backport_group.add_argument('--patch-dataset-dir', type=str,
                               help='补丁数据集目录 (也可通过PATCH_DATASET_DIR环境变量设置)')
    backport_group.add_argument('--error-message', type=str,
                               help='错误信息 (可选)')
    backport_group.add_argument('--sanitizer', type=str,
                               help='Sanitizer类型 (可选)')

    args = parser.parse_args()

    # 从环境变量获取参数默认值
    args.fork_repo_url = args.fork_repo_url or os.environ.get('FORK_REPO_URL')
    args.repo_url = args.repo_url or os.environ.get('REPO_URL')
    args.gitee_token = args.gitee_token or os.environ.get('GITEE_TOKEN')
    args.clone_dir = args.clone_dir or os.environ.get('CLONE_DIR')
    args.branches = args.branches or os.environ.get('BRANCHES', "OLK-5.10,OLK-6.6,master")
    args.signer_name = args.signer_name or os.environ.get('SIGNER_NAME')
    args.signer_email = args.signer_email or os.environ.get('SIGNER_EMAIL')
    # 统一使用 api_key 命名，同时兼容历史的 OPENAI_KEY 环境变量
    args.api_key = args.api_key or os.environ.get('API_KEY') or os.environ.get('OPENAI_KEY', "")
    args.patch_dataset_dir = args.patch_dataset_dir or os.environ.get('PATCH_DATASET_DIR', os.path.join(os.path.expanduser("~"), "backports/patch_dataset"))

    # 当执行 backport 且使用非 local LLM 时，必须配置 api_key
    if args.action == 'backport':
        provider_lower = str(args.llm_provider or 'openai').strip().lower()
        if not args.api_key and provider_lower != 'local':
            parser.error(
                "当 --llm-provider 不为 'local' 时，必须提供 LLM API 密钥 "
                "(通过 --api-key 参数或 API_KEY/OPENAI_KEY 环境变量)。"
            )

    # 检查必要的 gitee-token
    if not args.gitee_token and args.action != 'setup-env' and args.action != 'backport':
        parser.error("必须提供Gitee访问令牌(通过--gitee-token参数或GITEE_TOKEN环境变量)")

    # 检查必要的cve-id或issue-url（setup-env模式不需要）
    if args.action != 'setup-env' and not (args.cve_id or args.issue_url):
        parser.error("非setup-env模式需提供--cve-id或--issue-url参数")
    
    # 检查必要的fork-repo-url（某些action需要）
    if not args.fork_repo_url and args.action in ['setup-env', 'analyze-branches', 'apply-patch', 'create-pr']:
        parser.error("必须提供Fork仓库URL(通过--fork-repo-url参数或FORK_REPO_URL环境变量)")
    
    # 检查必要的signer-name和signer-email（apply-patch需要）
    if not args.signer_name and args.action == 'apply-patch':
        parser.error("必须提供提交者姓名(通过--signer-name参数或SIGNER_NAME环境变量)")
    
    if not args.signer_email and args.action == 'apply-patch':
        parser.error("必须提供提交者邮箱(通过--signer-email参数或SIGNER_EMAIL环境变量)")

    # 配置根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # 清除现有处理器
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    if args.debug:
        # 调试模式：添加控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    else:
        # 非调试模式：添加文件处理器
        log_dir = os.path.expanduser('~/.cvekit')
        os.makedirs(log_dir, exist_ok=True)  # 确保目录存在
        if args.cve_id:
            log_file = os.path.join(log_dir, f'cvekit-{args.cve_id}.log')
        else:
            log_file = os.path.join(log_dir, 'cvekit.log')
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    try:
        result = handle_action(args)
        format_output(result, args)
    except Exception as e:
        logger.error(f"执行失败: {str(e)}")
        if args.debug:
            logger.exception("错误详情")
        result = {
            'status': 'failed',
            'action': args.action,
            'message': str(e)
        }
        format_output(result, args)
        sys.exit(1)

def handle_action(args):
    """路由到不同操作处理器"""
    if args.action == 'setup-env':
        try:
            repo, repo_path = setup_repository(args.fork_repo_url, args.gitee_token, args.clone_dir)
        except Exception as e:
            return {
                'status': 'failed',
                'message': str(e)
            }
        return {
            'status': 'success',
            'repo_path': repo_path
        }
    if args.cve_id and not args.issue_url:
        args.issue_url = get_issue_url_from_cve_id(args.cve_id, args.gitee_token)

    cve_id = args.cve_id if args.cve_id else fetch_cve_id(args.issue_url, args.gitee_token, not args.no_cache)

    if args.action == 'parse-issue':
        logger.info(f"handle_action: parse_issue, issue_url={args.issue_url}")
        return handle_parse_issue(args)
    elif args.action == 'get-commits':
        return handle_get_commits(cve_id, not args.no_cache, args.clone_dir)
    elif args.action == 'analyze-branches':
        return handle_analyze_branches(args)
    elif args.action == 'apply-patch':
        return handle_apply_patch(cve_id, args)
    elif args.action == 'create-pr':
        return handle_create_pr(cve_id, args)
    elif args.action == 'backport':
        return handle_backport(cve_id, args)
    else:
        raise RuntimeError("action not supported: %s", args.action)

def handle_apply_patch(cve_id, args):
    """应用patch并把branch提交到fork分支"""
    apply_patch_lock.acquire()
    try:
        result = apply_patch(
            fork_repo_url=args.fork_repo_url,
            gitee_token=args.gitee_token,
            branch=args.branch,
            clone_dir=args.clone_dir,
            patch_path=args.patch_path,
            signer_name=args.signer_name,
            signer_email=args.signer_email,
            cve_id=cve_id,
            issue_url=args.issue_url
            )
    finally:
        apply_patch_lock.release()
    return result

def handle_create_pr(cve_id, args):
    """创建pr"""
    create_pr_lock.acquire()
    try:
        result = create_pr(
            cve_id=cve_id,
            issue_url=args.issue_url,
            fork_repo_url=args.fork_repo_url,
            repo_url=args.repo_url,
            branch=args.branch,
            clone_dir=args.clone_dir,
            gitee_token=args.gitee_token
        )
    finally:
        create_pr_lock.release()
    return result

def handle_backport(cve_id, args):
    """处理补丁回移植逻辑"""
    # 获取提交信息
    commits = get_vulnerability_commits(
        cve_id,
        not args.no_cache,
        clone_dir=args.clone_dir,
    )
    if not commits or len(commits) != 2:
        raise ValueError(f"无法获取提交信息: {commits}")
    
    introduced_commit, fixed_commit = commits
    
    # 确定目标分支
    target_branch = args.branch
    if not target_branch:
        # 如果没有指定 --branch，尝试从 --branches 中取第一个
        if args.branches:
            target_branch = args.branches.split(',')[0].strip()
        else:
            raise ValueError("backport模式需要指定目标分支，请使用--branch参数")
    temp_upstream_commit = branch_commit_from_upstream(fixed_commit, target_branch, args.clone_dir)
    if temp_upstream_commit:
        fixed_commit = temp_upstream_commit

    # 构建配置字典
    config_dict = {
        "project": "linux",
        "project_url": "",
        "project_dir": os.path.join(args.clone_dir, "linux"),
        "target_path": os.path.join(args.clone_dir, "kernel"),
        "new_patch": fixed_commit,
        "target_release": target_branch,
        # 内部配置字段仍使用 openai_key 以兼容 backporting 逻辑，这里用统一的 api_key 映射过去
        "openai_key": args.api_key,
        "llm_provider": args.llm_provider,
        "tag": cve_id,
        "patch_dataset_dir": os.path.join(args.patch_dataset_dir, cve_id) if args.patch_dataset_dir else os.path.join(os.path.expanduser("~"), "backports/patch_dataset", cve_id),
    }
    
    # 添加可选参数
    if args.error_message:
        config_dict["error_message"] = args.error_message
    if args.sanitizer:
        config_dict["sanitizer"] = args.sanitizer
    
    # 运行回移植
    backport_result = run_backport_from_config(config_dict, debug_mode=args.debug)
    
    # 构建与分支分析结果对应的返回结构
    result = {
        i18n("补丁ID"): cve_id,
        i18n("目标分支"): target_branch,
        i18n("是否受影响"): i18n("受影响"),
        i18n("适配状态"): i18n("成功") if backport_result.get('status') == 'success' else i18n("需要调整"),
        i18n("冲突点"): backport_result.get('backported_patch_path', backport_result.get('original_patch_path', '')),
        i18n("建议调整文件"): "N/A" if backport_result.get('status') == 'success' else "",
    }
    
    # 添加详细信息
    result['details'] = {
        'action': 'backport',
        'cve_id': cve_id,
        'target_branch': target_branch,
        'fixed_commit': fixed_commit,
        'original_patch_path': backport_result.get('original_patch_path'),
        'backported_patch_path': backport_result.get('backported_patch_path'),
        'diff_path': backport_result.get('diff_path'),
        'logfile': backport_result.get('logfile'),
        'time_cost': backport_result.get('time_cost'),
        'status': backport_result.get('status'),
    }
    
    if 'cost' in backport_result:
        result['details']['cost'] = backport_result['cost']
    if 'tokens' in backport_result:
        result['details']['tokens'] = backport_result['tokens']
    if 'error' in backport_result:
        result['details']['error'] = backport_result['error']
    
    return result

def handle_parse_issue(args):
    """处理issue解析逻辑"""
    issue_data = parse_gitee_issue_url(args.issue_url, args.gitee_token, not args.no_cache)
    return {
        "action": "parse-issue",
        "data": issue_data
    }

def handle_get_commits(cve_id, use_cache, clone_dir):
    """处理提交获取逻辑"""
    introduced, fixed = get_vulnerability_commits(
        cve_id,
        use_cache,
        clone_dir=clone_dir,
    )
    if not fixed:
        return {
            "action": "get-commits",
            "cve_id": cve_id,
            "error": "未能获取完整的修复提交(fixed)，无法继续流程"
        }
    result = {
        "action": "get-commits",
        "cve_id": cve_id,
        "introduced": introduced,
        "fixed": fixed
    }
    if not introduced:
        result["warning"] = "仅获取到修复提交(fixed)，未找到引入提交(introduced)"
    return result

def fetch_cve_id(issue_url, gitee_token, use_cache):
    """从issue URL自动获取CVE ID"""
    issue_data = parse_gitee_issue_url(issue_url, gitee_token, use_cache)
    if not issue_data.get('cve_id'):
        raise ValueError(i18n("提供的issue中未找到CVE ID"))
    return issue_data['cve_id']

def handle_analyze_branches(args):
    """处理分支分析逻辑"""
    issue_data = {}
    if args.issue_url:
        issue_data = parse_gitee_issue_url(args.issue_url, args.gitee_token, not args.no_cache)

    # 准备issue_info对象
    issue_info = IssueInfo(
        issue_id=issue_data.get('issue_id', 'N/A'),
        cve_id=issue_data.get('cve_id'),
        org_name=issue_data.get('org_name', ''),
        repo_name=issue_data.get('repo_name', ''),
        affected_versions=issue_data.get('affected_versions', ''),
        issue_url=args.issue_url
    )

    # 获取提交信息（自动使用缓存）
    commits = get_vulnerability_commits(
        issue_data.get('cve_id'),
        not args.no_cache,
        clone_dir=args.clone_dir,
    )
    if commits and len(commits) == 2:
        issue_info.introduced_commit, issue_info.fixed_commit = commits
    else:
        logger.warning(f"获取提交信息失败: {commits}")
        issue_info.introduced_commit = None
        issue_info.fixed_commit = None

    # 分析分支
    repo, repo_path = setup_repository(args.fork_repo_url, args.gitee_token, args.clone_dir)

    branch_list = [b.strip() for b in args.branches.split(',')]
    return process_branches(
                repo=repo,
                issue_info=issue_info,
                fork_repo_url=args.fork_repo_url,
                gitee_token=args.gitee_token,
                clone_dir=args.clone_dir,
                branchList=branch_list,
                use_cache=not args.no_cache
            )

def format_output(result, args):
    """格式化输出结果"""
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.table and isinstance(result, list):
        _display_branch_table(result)
    else:
        print(i18n("\n分析结果:"))
        print(result) if result else print(i18n("无结果输出"))

def _display_branch_table(branches):
    """显示分支分析表格"""
    table_data = []
    for branch in branches:
        row = [
            branch[i18n('目标分支')],
            branch[i18n('是否受影响')],
            branch[i18n('适配状态')],
            branch[i18n('冲突点')][:50] + '...' if len(branch[i18n('冲突点')]) > 50 else branch[i18n('冲突点')]
        ]
        # 如果有提交信息，添加到表格中
        if i18n('提交信息') in branch and branch[i18n('提交信息')]:
            commit_msg = branch[i18n('提交信息')]
            row.append(commit_msg[:80] + '...' if len(commit_msg) > 80 else commit_msg)
        else:
            row.append('N/A')
        table_data.append(row)
    
    headers = [i18n('分支'), i18n('受影响'), i18n('状态'), i18n('补丁路径'), i18n('提交信息')]
    print(tabulate(table_data,
                  headers=headers,
                  tablefmt='grid'))

if __name__ == "__main__":
    main()
