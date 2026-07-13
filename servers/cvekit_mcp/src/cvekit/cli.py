import argparse
import sys
import logging
import os
import json
import multiprocessing
import asyncio
import git
from datetime import datetime

from typing import Optional, Tuple, List, Dict
from tabulate import tabulate
from .utils.gitee import parse_gitee_issue_url, setup_repository, get_issue_url_from_cve_id
from .utils.commits import get_vulnerability_commits, branch_commit_from_upstream
from .utils.branches import process_branches
from .utils.apply_patch import apply_patch
from .utils.create_pr import create_pr
from .utils.locales import i18n
from .utils.backporting import run_backport_from_config
from .utils.backport_batch import (
    handle_backport_batch,
    generate_backport_batch_config_from_excel,
)
from .utils.package.patch_crawler import PackagePatchCrawler
from .utils.package.patch_download import download_package_patch
from .utils.env_loader import get_rpmbuild_path
from .utils.package.source_repo import get_spec_version_from_branch, sync_rpmbuild_to_repo, cleanup_package

logger = logging.getLogger(__name__)
apply_patch_lock = multiprocessing.Lock()
create_pr_lock = multiprocessing.Lock()


def _build_log_formatter():
    return logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')


def _setup_logging(args):
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    formatter = _build_log_formatter()
    debug_enabled = bool(getattr(args, "debug", False))

    if debug_enabled:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
    else:
        log_dir = os.path.expanduser('~/.cvekit')
        os.makedirs(log_dir, exist_ok=True)
        if args.cve_id:
            log_file = os.path.join(log_dir, f'cvekit-{args.cve_id}.log')
        else:
            log_file = os.path.join(log_dir, 'cvekit.log')
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    if args.action == 'backport-batch':
        backport_log_dir = os.path.expanduser('~/.backport')
        os.makedirs(backport_log_dir, exist_ok=True)
        timestamp = datetime.utcnow().strftime('%Y-%m-%d-%H-%M')
        backport_log_file = os.path.join(backport_log_dir, f'{timestamp}.log')

        if not debug_enabled:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

        backport_file_handler = logging.FileHandler(backport_log_file)
        backport_file_handler.setLevel(logging.DEBUG if debug_enabled else logging.INFO)
        backport_file_handler.setFormatter(formatter)
        root_logger.addHandler(backport_file_handler)

        args.backport_log_file = backport_log_file
        logger.info("backport-batch 日志文件: %s", backport_log_file)

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
                      choices=[
                          'parse-issue',
                          'get-commits',
                          'analyze-branches',
                          'setup-env',
                          'apply-patch',
                          'create-pr',
                          'backport',
                          'backport-batch',
                          'get-commits-package',
                          'download-patch-package',
                          'playwright',
                          'apply-patch-package',
                          'analyze-branch-package',
                          'mystique',
                      ],
                      default='analyze-branches',
                      help='''执行模式:
                      parse-issue(解析issue),
                      get-commits(获取提交),
                      analyze-branches(分析分支,默认),
                      setup-env(设置仓库环境),
                      apply-patch(应用patch),
                      create-pr(创建PR),
                      backport(补丁回移植),
                      backport-batch(批量补丁回移植),
                      get-commits-package(获取软件包提交),
                      download-patch-package(下载软件包补丁),
                      playwright(运行playwright agent),
                      apply-patch-package(应用软件包补丁),
                      analyze-branch-package(分析软件包分支),
                      mystique(补丁迁移)''')


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
    pr_group.add_argument(
        '--fix-branch',
        type=str,
        default=None,  # 改为 None，未指定时自动生成
        help='修复分支名称 (也可通过 FIX_BRANCH 环境变量设置)，未指定时自动生成为 fix-{branch}-{issue_num}',
    )
    # LLM 冲突解决参数（复用 backport_group 的 --llm-provider 等参数）
    pr_group.add_argument(
        '--use-llm',
        action='store_true',
        help='启用 LLM 自动解决补丁冲突（当 git apply 失败时，复用 --llm-provider 等参数配置）',
    )
    pr_group.add_argument(
        '--no-confirm',
        action='store_true',
        default=False,
        help='跳过 LLM 生成补丁后的人工确认步骤（默认需要确认，此参数用于自动化场景）',
    )

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
        default=None,  # 改为 None，让环境变量和实际逻辑决定默认值
        help='LLM提供商 (优先级: 命令行参数 > 环境变量LLM_PROVIDER > 默认openai；可传入任意值配合 --llm-base-url 和 --llm-model-name 使用)',
    )
    backport_group.add_argument(
        '--llm-base-url',
        type=str,
        help='LLM API 基础地址 (例如: https://api.example.com/v1)，可覆盖默认配置',
    )
    backport_group.add_argument(
        '--llm-model-name',
        type=str,
        help='LLM 模型名称 (例如: gpt-4o-mini)，可覆盖默认配置',
    )
    backport_group.add_argument(
        '--format-mode',
        choices=['full', 'changed'],
        default=None,
        help=(
            '格式调整模式：full为整函数格式化；changed仅格式化变化区域'
        ),
    )
    backport_group.add_argument(
        '--backport-engine',
        choices=['portgpt', 'mystique'],
        default=None,
        help='仅在 backport-batch 下使用：选择回移植引擎；默认读取配置，未配置时使用 portgpt',
    )
    backport_group.add_argument(
        '--target-config-layout',
        choices=['none', 'anolis'],
        default='',
        help=(
            '仅在 backport-batch 下使用：目标仓配置文件布局；'
            'none 为默认行为（不处理 defconfig），'
            'anolis 将 openEuler defconfig 改动适配到 anolis/configs 拆分配置'
        ),
    )
    backport_group.add_argument(
        '--target-config-layout-opts',
        type=str,
        default='',
        help=(
            '仅在 backport-batch 下使用：目标仓配置布局的额外选项（JSON 格式）；'
            '例如: \'{"default_level":"L2-OPTIONAL"}\''
        ),
    )
    backport_group.add_argument('--patch-dataset-dir', type=str,
                               help='补丁数据集目录 (也可通过PATCH_DATASET_DIR环境变量设置)')
    backport_group.add_argument('--error-message', type=str,
                               help='错误信息 (可选)')
    backport_group.add_argument('--sanitizer', type=str,
                               help='Sanitizer类型 (可选)')
    backport_group.add_argument('--backport-config', type=str,
                               help='批量回移植配置文件路径 (YAML/JSON)，用于 backport-batch')
    backport_group.add_argument(
        '--backport-excel',
        type=str,
        help='Excel 输入路径（包含 commit title 与 commit hash），用于生成 backport-batch 原始配置'
    )
    backport_group.add_argument(
        '-o',
        '--output',
        type=str,
        help='输出路径（用于 backport-batch 的配置生成子功能）'
    )
    backport_group.add_argument(
        '--excel-sheet',
        type=str,
        help='指定 Excel sheet 名称（默认第一个）'
    )
    backport_group.add_argument(
        '--commit-sort',
        choices=['describe', 'time'],
        default='describe',
        help='backport-batch commit 排序方式；不传时使用配置里的 commit_sort。describe 按 git describe 的 tag+distance 排序；time 按提交时间排序，同秒时用 git topo-order 稳定顺序'
    )
    backport_group.add_argument(
        '-i',
        '--interactive',
        action='store_true',
        help='交互式编辑 backport-batch 报告配置（如 merged_in_target）'
    )
    backport_group.add_argument(
        '-e',
        '--execute',
        action='store_true',
        help='仅在 backport-batch 下使用：显式执行 .report.yml 中的回移植流程（推荐）'
    )
    backport_group.add_argument(
        '--apply',
        type=str,
        help='仅在 backport-batch 下使用：直接应用补丁（可传 backported patch 路径或 commit id）'
    )
    backport_group.add_argument(
        '--preview-commit-message',
        action='store_true',
        help='仅在 backport-batch 下使用：预览指定 --apply 条目的模板化 commit message，不修改仓库'
    )
    backport_group.add_argument(
        '--stop-at-first-conflict',
        action='store_true',
        help='仅在 backport-batch 下使用：生成/续扫 report 时检测到第一条冲突后停止，后续条目标记为 pending'
    )
    backport_group.add_argument(
        '--enable-conflict-summary',
        action='store_true',
        help='仅在 backport-batch 下使用：对已生成解冲突补丁的冲突条目调用 opencode 生成总结和评分'
    )
    backport_group.add_argument(
        '--commit-message-template',
        type=str,
        help='仅在 backport-batch 下使用：覆盖配置文件中的 commit message 模板'
    )
    backport_group.add_argument(
        '--commit-message-source',
        choices=['auto', 'openEuler', 'upstream'],
        default='',
        help='仅在 backport-batch 下使用：固定 commit message 来源，auto 表示自动判断'
    )
    backport_group.add_argument(
        '--linux-repo-path',
        type=str,
        help='仅在 backport-batch 下使用：用于验证 upstream commit 的 Linux 仓库路径'
    )
    

    # mystique 补丁迁移参数
    mystique_group = parser.add_argument_group('mystique补丁迁移参数')
    mystique_group.add_argument('--project-dir', type=str,
                               help='源代码仓库路径（包含待迁移commit的仓库）')
    mystique_group.add_argument('--target-path', type=str,
                               help='目标代码仓库路径（补丁迁移的目标仓库）')
    mystique_group.add_argument('--commit-id', type=str,
                               help='待迁移的commit ID')

    # package相关参数
    package_group = parser.add_argument_group('软件包CVE适配参数')
    package_group.add_argument('--package-name', type=str, default=None,
                               help='软件包名称 (可选)')
    package_group.add_argument('--commit', type=str,
                               help='commit url (可选)')
    package_group.add_argument('--patch-dir', type=str,
                               help='软件包补丁目录 (可选)')
    package_group.add_argument('--sup-url', type=str,
                               help='补充链接 (可选)')
    package_group.add_argument('--rpmbuild-path', type=str,
                               help='rpmbuild根目录 (可选)',
                               default=os.path.expanduser("~/rpmbuild"))
    args = parser.parse_args()

    # 从环境变量获取参数默认值
    args.fork_repo_url = args.fork_repo_url or os.environ.get('FORK_REPO_URL')
    args.repo_url = args.repo_url or os.environ.get('REPO_URL')
    args.gitee_token = args.gitee_token or os.environ.get('GITEE_TOKEN')
    args.clone_dir = args.clone_dir or os.environ.get('CLONE_DIR')
    if args.clone_dir:
        args.clone_dir = os.path.abspath(os.path.expanduser(args.clone_dir))
    args.branches = args.branches or os.environ.get('BRANCHES', "OLK-5.10,OLK-6.6,master")
    args.signer_name = args.signer_name or os.environ.get('SIGNER_NAME')
    args.signer_email = args.signer_email or os.environ.get('SIGNER_EMAIL')
    args.fix_branch = args.fix_branch or os.environ.get('FIX_BRANCH')
    # 统一使用 api_key 命名，同时兼容历史的 OPENAI_KEY 环境变量
    args.api_key = args.api_key or os.environ.get('API_KEY') or os.environ.get('OPENAI_KEY', "")
    args.patch_dataset_dir = args.patch_dataset_dir or os.environ.get('PATCH_DATASET_DIR', os.path.join(os.path.expanduser("~"), "backports/patch_dataset"))
    args.rpmbuild_path = args.rpmbuild_path or get_rpmbuild_path()
    # LLM 自定义配置：从环境变量获取 provider、base_url 和 model_name
    # 优先级：命令行参数 > 环境变量 > 默认值
    args.llm_provider = args.llm_provider or os.environ.get('LLM_PROVIDER') or 'openai'
    args.llm_base_url = args.llm_base_url or os.environ.get('LLM_BASE_URL')
    args.llm_model_name = args.llm_model_name or os.environ.get('LLM_MODEL_NAME') or os.environ.get('MODEL_NAME')
    
    # 当执行 backport 且使用非 local LLM 时，必须配置 api_key
    if args.action == 'backport':
        provider_lower = str(args.llm_provider or 'openai').strip().lower()
        if not args.api_key and provider_lower != 'local':
            parser.error(
                "当 --llm-provider 不为 'local' 时，必须提供 LLM API 密钥 "
                "(通过 --api-key 参数或 API_KEY/OPENAI_KEY 环境变量)。"
            )

    # 检查必要的 gitee-token（仅 parse-issue 和 create-pr 需要）
    if not args.gitee_token and args.action in ['parse-issue', 'create-pr']:
        parser.error("必须提供Gitee访问令牌(通过--gitee-token参数或GITEE_TOKEN环境变量)")

    # 检查必要的cve-id或issue-url（setup-env、backport-batch和mystique模式不需要强制提供）
    if args.action not in ['setup-env', 'backport-batch', 'mystique'] and not (args.cve_id or args.issue_url):
        parser.error("非setup-env模式需提供--cve-id或--issue-url参数")

    # 检查必要的clone-dir（某些action需要）
    if not args.clone_dir and args.action in ['setup-env', 'analyze-branches', 'apply-patch', 'create-pr', 'backport', 'get-commits', 'mystique']:
        parser.error("必须提供克隆目录(通过--clone-dir参数或CLONE_DIR环境变量)")
    
    # 检查必要的fork-repo-url（仅create-pr需要，其他action有默认值或可选）
    if not args.fork_repo_url and args.action in ['create-pr']:
        parser.error("必须提供Fork仓库URL(通过--fork-repo-url参数或FORK_REPO_URL环境变量)")
    
    # 检查必要的signer-name和signer-email（apply-patch需要）
    if not args.signer_name and args.action == 'apply-patch':
        parser.error("必须提供提交者姓名(通过--signer-name参数或SIGNER_NAME环境变量)")
    
    if not args.signer_email and args.action == 'apply-patch':
        parser.error("必须提供提交者邮箱(通过--signer-email参数或SIGNER_EMAIL环境变量)")

    # 检查必要的branch（apply-patch、create-pr、backport需要）
    if not args.branch and args.action in ['apply-patch', 'create-pr', 'backport']:
        parser.error(f"{args.action} 模式需要指定目标分支，请使用 --branch 参数")

    _setup_logging(args)

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
            repo, repo_path = setup_repository(
                args.fork_repo_url, args.gitee_token, args.clone_dir,
                target_path=getattr(args, 'target_path', '') or None,
            )
        except Exception as e:
            return {
                'status': 'failed',
                'message': str(e)
            }
        return {
            'status': 'success',
            'repo_path': repo_path
        }
    if args.action == 'backport-batch':
        logger.info(
            "开始执行 backport-batch: config=%s, excel=%s, execute=%s, apply=%s, preview=%s, interactive=%s",
            getattr(args, 'backport_config', None),
            getattr(args, 'backport_excel', None),
            getattr(args, 'execute', False),
            getattr(args, 'apply', None),
            getattr(args, 'preview_commit_message', False),
            getattr(args, 'interactive', False),
        )
        if args.backport_excel:
            return generate_backport_batch_config_from_excel(
                excel_path=args.backport_excel,
                output_path=args.output,
                template_config_path=args.backport_config,
                sheet_name=args.excel_sheet,
            )
        return handle_backport_batch(args)

    if args.action == 'analyze-branches':
        return handle_analyze_branches(args)

    if args.action == 'get-commits':
        if not args.cve_id:
            raise ValueError("get-commits 模式需要提供 --cve-id 参数")
        return handle_get_commits(args.cve_id, not args.no_cache, args.clone_dir,
                                  project_dir=getattr(args, 'project_dir', '') or '')

    if args.action == 'backport':
        if not args.cve_id:
            raise ValueError("backport 模式需要提供 --cve-id 参数")
        return handle_backport(args.cve_id, args)

    if args.action == 'apply-patch':
        if not args.cve_id:
            raise ValueError("apply-patch 模式需要提供 --cve-id 参数")
        # 尝试获取 issue_url（但不强制要求成功）
        if args.cve_id and not args.issue_url:
            try:
                args.issue_url = get_issue_url_from_cve_id(args.cve_id, args.gitee_token, package_name = args.package_name)
            except Exception as e:
                logger.warning(f"获取 issue_url 失败: {str(e)}，将使用 cve_id 作为标识")
        return handle_apply_patch(args.cve_id, args)

    if args.cve_id and not args.issue_url:
        args.issue_url = get_issue_url_from_cve_id(args.cve_id, args.gitee_token, package_name = args.package_name)

    cve_id = args.cve_id
    if not cve_id and args.issue_url:
        cve_id = fetch_cve_id(args.issue_url, args.gitee_token, not args.no_cache)

    if args.action == 'parse-issue':
        logger.info(f"handle_action: parse_issue, issue_url={args.issue_url}")
        return handle_parse_issue(args)
    elif args.action == 'create-pr':
        return handle_create_pr(cve_id, args)
    elif args.action == 'get-commits-package':
        return handle_get_commits_package(args)
    elif args.action == 'download-patch-package':
        return handle_download_patch_package(args)
    elif args.action == 'playwright':
        return handle_plawright(args)
    elif args.action == 'apply-patch-package':
        return handle_apply_patch_to_package(args)
    elif args.action == 'analyze-branch-package':
        return handle_analyze_branch_package(args)
    elif args.action == 'mystique':
        return handle_mystique(cve_id, args)

    else:
        raise RuntimeError("action not supported: %s", args.action)


def handle_apply_patch(cve_id, args):
    """应用 patch 到本地仓库（可选推送到 fork 分支）"""
    apply_patch_lock.acquire()
    try:
        # 默认需要人工确认，除非使用 --no-confirm 参数
        llm_confirm = not getattr(args, 'no_confirm', False)

        result = apply_patch(
            fork_repo_url=args.fork_repo_url,
            gitee_token=args.gitee_token,
            branch=args.branch,
            clone_dir=args.clone_dir,
            patch_path=args.patch_path,
            signer_name=args.signer_name,
            signer_email=args.signer_email,
            cve_id=cve_id,
            issue_url=args.issue_url,
            fix_branch=args.fix_branch,
            use_llm=getattr(args, 'use_llm', False),
            llm_provider=getattr(args, 'llm_provider', None),
            llm_base_url=getattr(args, 'llm_base_url', None),
            llm_model_name=getattr(args, 'llm_model_name', None),
            api_key=getattr(args, 'api_key', None),
            llm_confirm=llm_confirm,
            project_dir=getattr(args, 'project_dir', '') or '',
            target_path=getattr(args, 'target_path', '') or None,
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
            gitee_token=args.gitee_token,
            target_path=getattr(args, 'target_path', '') or None,
        )
    finally:
        create_pr_lock.release()
        
    if args.package_name:
        cleanup_package(args.clone_dir, args.rpmbuild_path, args.package_name)
    return result

def handle_backport(cve_id, args):
    """处理补丁回移植逻辑"""
    # 获取提交信息
    _project_dir = getattr(args, 'project_dir', '') or ''
    _target_path = getattr(args, 'target_path', '') or ''
    commits = get_vulnerability_commits(
        cve_id,
        not args.no_cache,
        clone_dir=args.clone_dir,
        project_dir=_project_dir,
    )
    if not commits or len(commits) != 2:
        raise ValueError(f"无法获取提交信息: {commits}")

    introduced_commit, fixed_commit = commits

    # 确定目标分支
    target_branch = args.branch
    if not target_branch:
        if args.branches:
            target_branch = args.branches.split(',')[0].strip()
        else:
            raise ValueError("backport模式需要指定目标分支，请使用--branch参数")
    temp_upstream_commit = branch_commit_from_upstream(fixed_commit, target_branch, args.clone_dir,
                                                       project_dir=_project_dir)
    if temp_upstream_commit:
        fixed_commit = temp_upstream_commit

    # 构建配置字典
    config_dict = {
        "project": "linux",
        "project_url": "",
        "project_dir": _project_dir or os.path.join(args.clone_dir, "linux"),
        "target_path": _target_path or os.path.join(args.clone_dir, "kernel"),
        "new_patch": fixed_commit,
        "target_release": target_branch,
        # 内部配置字段仍使用 openai_key 以兼容 backporting 逻辑，这里用统一的 api_key 映射过去
        "openai_key": args.api_key,
        "llm_provider": args.llm_provider,
        "llm_base_url": args.llm_base_url,
        "llm_model_name": args.llm_model_name,
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
    is_empty_patch = bool(backport_result.get('empty_patch'))
    equivalent_exists = bool(backport_result.get('equivalent_exists'))
    result = {
        i18n("补丁ID"): cve_id,
        i18n("目标分支"): target_branch,
        i18n("是否受影响"): i18n("受影响"),
        i18n("适配状态"): i18n("成功") if backport_result.get('status') == 'success' else i18n("需要调整"),
        i18n("冲突点"): "" if is_empty_patch else (backport_result.get('backported_patch_path') or backport_result.get('original_patch_path', '')),
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
        'empty_patch': is_empty_patch,
        'equivalent_exists': equivalent_exists,
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

def handle_mystique(cve_id, args):
    """处理 mystique 补丁迁移逻辑，返回结构与 handle_backport 一致"""
    import sys as _sys
    _mystique_src = os.path.join(os.path.dirname(__file__), "utils", "mystique", "src")
    if _mystique_src not in _sys.path:
        _sys.path.insert(0, _mystique_src)
    import config as mystique_config
    import main as mystique_main

    mystique_config.configure_llm(
        provider=args.llm_provider,
        api_key=args.api_key,
        base_url=args.llm_base_url,
        model_name=args.llm_model_name,
    )
    mystique_config.configure_format_normalization(
        getattr(args, "format_mode", None)
    )

    # 获取修复提交：优先使用 --commit-id，否则从 CVE ID 自动获取
    fixed_commit = args.commit_id or None
    if not fixed_commit and cve_id:
        commits = get_vulnerability_commits(
            cve_id,
            not args.no_cache,
            clone_dir=args.clone_dir,
            project_dir=getattr(args, 'project_dir', '') or '',
        )
        if commits and len(commits) == 2:
            _, fixed_commit = commits
    if not fixed_commit:
        raise ValueError("mystique模式需要提供 --commit-id 或 --cve-id 参数来获取修复提交")

    # 确定目标分支
    target_release = args.branch
    if not target_release:
        if args.branches:
            target_release = args.branches.split(',')[0].strip()
        else:
            raise ValueError("mystique模式需要指定目标分支，请使用--branch参数")

    # 仓库路径：优先使用显式参数，否则从 clone_dir 推导
    project_dir = args.project_dir or os.path.join(args.clone_dir, "linux")
    target_path = args.target_path or os.path.join(args.clone_dir, "kernel")

    results = mystique_main.main_from_repo(
        project_dir=project_dir,
        target_path=target_path,
        new_patch=fixed_commit,
        target_release=target_release,
        signatures=None,
        output=args.output,
        cve_id=cve_id,
        debug=args.debug,
    )

    # Use the path produced by this run. Do not guess a filename and
    # accidentally return an older patch from a previous run.
    combined_patch_path = next(
        (
            item.get("backported_patch_path")
            for item in results
            if item.get("backported_patch_path")
        ),
        None,
    )
    logfile = next(
        (item.get("logfile") for item in results if item.get("logfile")),
        None,
    )
    original_patch_path = next(
        (
            item.get("original_patch_path")
            for item in results
            if item.get("original_patch_path")
        ),
        None,
    )

    is_empty_patch = all(r.get("status") == "need_not_ported" for r in results)
    status = "empty_patch" if is_empty_patch else "success"

    result = {
        i18n("补丁ID"): cve_id,
        i18n("目标分支"): target_release,
        i18n("是否受影响"): i18n("受影响"),
        i18n("适配状态"): (
            i18n("无需执行（补丁已存在）") if is_empty_patch else i18n("成功")
        ),
        i18n("冲突点"): "" if is_empty_patch else (combined_patch_path or ""),
        i18n("建议调整文件"): "N/A" if is_empty_patch else (combined_patch_path or ""),
    }

    result["details"] = {
        "action": "mystique",
        "cve_id": cve_id,
        "target_branch": target_release,
        "fixed_commit": fixed_commit,
        "original_patch_path": original_patch_path,
        "backported_patch_path": combined_patch_path,
        "diff_path": combined_patch_path,
        "empty_patch": is_empty_patch,
        "logfile": logfile,
        "time_cost": None,
        "status": status,
    }

    return result

def handle_parse_issue(args):
    """处理issue解析逻辑"""
    issue_data = parse_gitee_issue_url(args.issue_url, args.gitee_token, not args.no_cache)
    return {
        "action": "parse-issue",
        "data": issue_data
    }

def handle_get_commits(cve_id, use_cache, clone_dir, project_dir=""):
    """处理提交获取逻辑"""
    introduced, fixed = get_vulnerability_commits(
        cve_id,
        use_cache,
        clone_dir=clone_dir,
        project_dir=project_dir,
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
    """处理分支分析逻辑
    
    支持两种模式：
    1. 提供 issue_url：从 issue 获取详细信息并分析分支
    2. 只提供 cve_id：直接使用 cve_id 获取 commit 信息并分析分支
    """
    issue_data = {}
    cve_id = args.cve_id
    
    if args.issue_url:
        issue_data = parse_gitee_issue_url(args.issue_url, args.gitee_token, not args.no_cache)
        if not cve_id:
            cve_id = issue_data.get('cve_id')
    
    if not cve_id:
        raise ValueError(i18n("必须提供 --cve-id 或 --issue-url 参数"))

    issue_info = IssueInfo(
        issue_id=issue_data.get('issue_id', 'N/A'),
        cve_id=cve_id,
        org_name=issue_data.get('org_name', ''),
        repo_name=issue_data.get('repo_name', ''),
        affected_versions=issue_data.get('affected_versions', ''),
        issue_url=args.issue_url
    )

    commits = get_vulnerability_commits(
        cve_id,
        not args.no_cache,
        clone_dir=args.clone_dir,
        project_dir=getattr(args, 'project_dir', '') or '',
    )
    if commits and len(commits) == 2:
        issue_info.introduced_commit, issue_info.fixed_commit = commits
    else:
        logger.warning(f"获取提交信息失败: {commits}")
        issue_info.introduced_commit = None
        issue_info.fixed_commit = None

    repo, repo_path = setup_repository(
        args.fork_repo_url, args.gitee_token, args.clone_dir,
        target_path=getattr(args, 'target_path', '') or None,
    )

    branch_list = [b.strip() for b in args.branches.split(',')]
    return process_branches(
                repo=repo,
                issue_info=issue_info,
                fork_repo_url=args.fork_repo_url,
                gitee_token=args.gitee_token,
                clone_dir=args.clone_dir,
                branchList=branch_list,
                use_cache=not args.no_cache,
                project_dir=getattr(args, 'project_dir', '') or '',
            )

def handle_get_commits_package(args) -> Tuple[List[Dict], List[Dict]]:
    """获取指定软件包CVE的提交列表与补丁详情。"""
    ensure_cve_tracking_reuse_path()
    crawler = PackagePatchCrawler()
    # 获取commit链接
    commits_tuple, patch_details = asyncio.run(crawler.get_package_commits(args.cve_id, args.package_name))
    commits = [ct["url"] for ct in commits_tuple if ct.get("url")]
    # 获取没有对应commit url的issue或者pr链接作为补充链接
    supplement_urls = set()
    for item in patch_details or []:
        for detail in item.get("details") or []:
            issue = detail.get("issue") or {}
            issue_url = issue.get("url")
            prs = issue.get("prs") or []
            if issue_url and not prs:
                supplement_urls.add(issue_url)
            if not issue_url and prs:
                for pr in prs:
                    if not pr.get("commits") and pr.get("url"):
                        supplement_urls.add(pr.get("url"))

        for url in sorted(supplement_urls):
            logger.info("issue/pr 待检查: %s", url)
    return commits, sorted(supplement_urls)

def handle_download_patch_package(args):
    """下载指定commit的补丁"""
    ensure_cve_tracking_reuse_path()
    commit_out_files, commit_failed = download_package_patch(
        commit_url=args.commit,
        patch_dir=args.patch_dir,
        cve_id=args.cve_id,
        clone_dir=args.clone_dir,
        rpm_name=args.package_name,
        branch=args.branch,
        )
    return commit_out_files

def handle_plawright(args):
    """用playwright mcp测试cve"""
    from .utils.package.playwright_for_patch import run_agent
    agent_result = asyncio.run(run_agent(args.sup_url, args.package_name, args.cve_id))
    return agent_result

def handle_apply_patch_to_package(args):
    """通过 cve_tracking 复用模块的 PathApply 应用补丁。"""
    ensure_cve_tracking_reuse_path()
    from core.verification.apply import PathApply

    patch_apply = PathApply(
        rpm_name=args.package_name,
        branch_rpm=args.branch,
        patch_path=args.patch_dir,
        source_path=args.clone_dir,
        cve_num=args.cve_id,
        rpmbuild_path=args.rpmbuild_path
    )
    result = patch_apply.packing_source()
    if result=="完全适配":
        sync_rpmbuild_to_repo(
            rpmbuild_path=args.rpmbuild_path,
            repo_path=os.path.join(args.clone_dir, args.package_name) if args.clone_dir and args.package_name else None,
            rpm_name=args.package_name
        )
    return result


def handle_analyze_branch_package(args) -> List[Dict]:
    repo_path = os.path.join(args.clone_dir, args.package_name)
    if not os.path.exists(repo_path):
        return {
            "action": "analyze-branch-package",
            "error": "未找到指定软件包仓库"
        }
    repo = git.Repo(repo_path)
    version = get_spec_version_from_branch(repo, branch_name=args.branch, repo_name=args.package_name)
    return {"action": "analyze-branch-package",
            "version": version}

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

def ensure_cve_tracking_reuse_path() -> str:
    """Ensure cve_tracking_reuse is on sys.path and return its path."""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cve_tracking_path = os.path.join(current_dir, "utils", "cve_tracking_reuse")
    if not os.path.exists(cve_tracking_path):
        raise FileNotFoundError(f"cve_tracking_reuse目录不存在: {cve_tracking_path}")
    if cve_tracking_path not in sys.path:
        sys.path.insert(0, cve_tracking_path)
    return cve_tracking_path

if __name__ == "__main__":
    main()
