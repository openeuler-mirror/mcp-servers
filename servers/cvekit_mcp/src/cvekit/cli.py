import argparse
import sys
import logging
import os
import json

from tabulate import tabulate
from .utils.gitee import parse_gitee_issue_url, setup_repository
from .utils.commits import get_vulnerability_commits
from .utils.branches import process_branches
from .utils.cache import get_cached_data, save_cache
from .utils.apply_patch import apply_patch
from .utils.create_pr import create_pr
from .utils.locales import i18n

logger = logging.getLogger(__name__)

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
                      choices=['parse-issue', 'get-commits', 'analyze-branches', 'setup-env', 'apply-patch', 'create-pr'],
                      default='analyze-branches',
                      help='''执行模式: 
                      parse-issue(解析issue),
                      get-commits(获取提交),
                      analyze-branches(分析分支,默认),
                      setup-env(设置仓库环境),
                      apply-patch(应用patch),
                      create-pr(创建PR)''')


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

    args = parser.parse_args()

    # 从环境变量获取参数默认值
    args.fork_repo_url = args.fork_repo_url or os.environ.get('FORK_REPO_URL', "https://gitee.com/lw520203/kernel_4")
    args.repo_url = args.repo_url or os.environ.get('REPO_URL', "https://gitee.com/openeuler/kernel")
    args.gitee_token = args.gitee_token or os.environ.get('GITEE_TOKEN')
    args.clone_dir = args.clone_dir or os.environ.get('CLONE_DIR', os.path.join(os.path.expanduser("~"), "Image"))
    args.branches = args.branches or os.environ.get('BRANCHES', "OLK-5.10,OLK-6.6,master")
    args.signer_name = args.signer_name or os.environ.get('SIGNER_NAME', "suyibk")
    args.signer_email = args.signer_email or os.environ.get('SIGNER_EMAIL', "suyibk@qq.com")

    # 检查必要的gitee-token
    if not args.gitee_token and args.action != 'setup-env':
        parser.error("必须提供Gitee访问令牌(通过--gitee-token参数或GITEE_TOKEN环境变量)")

    if args.action != 'setup-env' and not (args.cve_id or args.issue_url):
        parser.error("非setup-env模式需提供--cve-id或--issue-url参数")

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

    cve_id = args.cve_id if args.cve_id else fetch_cve_id(args.issue_url, args.gitee_token, not args.no_cache)

    if args.action == 'parse-issue':
        return handle_parse_issue(args)
    elif args.action == 'get-commits':
        return handle_get_commits(cve_id, not args.no_cache)
    elif args.action == 'analyze-branches':  # analyze-branches
        return handle_analyze_branches(args)
    elif args.action == 'apply-patch':
        return handle_apply_patch(cve_id, args)
    elif args.action == 'create-pr':
        return handle_create_pr(cve_id, args)
    else:
        raise RuntimeError("action not supported: %s", args.action)

def handle_apply_patch(cve_id, args):
    """应用patch并把branch提交到fork分支"""
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
    return result

def handle_create_pr(cve_id, args):
    """创建pr"""
    result = create_pr(
        cve_id=cve_id,
        issue_url=args.issue_url,
        fork_repo_url=args.fork_repo_url,
        repo_url=args.repo_url,
        branch=args.branch,
        clone_dir=args.clone_dir,
        gitee_token=args.gitee_token
    )
    return result

def handle_parse_issue(args):
    """处理issue解析逻辑"""
    issue_data = parse_gitee_issue_url(args.issue_url, args.gitee_token, not args.no_cache)
    return {
        "action": "parse-issue",
        "data": issue_data
    }

def handle_get_commits(cve_id, use_cache):
    """处理提交获取逻辑"""
    introduced, fixed = get_vulnerability_commits(cve_id, use_cache)
    return {
        "action": "get-commits",
        "cve_id": cve_id,
        "introduced": introduced,
        "fixed": fixed
    }

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
    commits = get_vulnerability_commits(issue_data.get('cve_id'), not args.no_cache)
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
                signer_name=args.signer_name,
                signer_email=args.signer_email,
                branchList=branch_list
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
        table_data.append([
            branch[i18n('目标分支')],
            branch[i18n('是否受影响')],
            branch[i18n('适配状态')],
            branch[i18n('冲突点')][:50] + '...' if len(branch[i18n('冲突点')]) > 50 else branch[i18n('冲突点')]
        ])
    print(tabulate(table_data,
                  headers=[i18n('分支'), i18n('受影响'), i18n('状态'), i18n('冲突点')],
                  tablefmt='grid'))

if __name__ == "__main__":
    main()