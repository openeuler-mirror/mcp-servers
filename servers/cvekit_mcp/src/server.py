import subprocess
import json
import argparse
import logging
from typing import Optional
from pydantic import Field
from mcp.server.fastmcp import FastMCP
import os

logger = logging.getLogger(__name__)

base_dir = os.path.dirname(__file__)
os.environ["PYTHONPATH"] = base_dir

from cvekit.utils.locales import i18n, update_docstring
from cvekit.utils.cache import BRANCHES_ANALYSIS_CACHE, _get_cache_key, get_cached_data, save_cache, delete_cache_key

mcp = FastMCP(i18n("CVE修复流程自动化工具，提供CVE分析、补丁适配等功能"))

# 全局变量，用于存储命令行参数
default_llm_provider = None
default_api_key = None
default_gitee_token = None

# 配置参数解析
parser = argparse.ArgumentParser()
parser.add_argument('--gitee-token', help=i18n('Gitee访问令牌'))
parser.add_argument('--llm-provider', help=i18n('LLM提供商(可选，默认openai)'))
parser.add_argument('--api-key', help=i18n('LLM API密钥(可选，用于自动调整补丁)'))
parser.add_argument('--branches-to-analyze', default="OLK-6.6,OLK-5.10,openEuler-1.0-LTS", help=i18n('用于分析的分支列表，逗号分隔'))
parser.add_argument('--test-analyze-branches', help=i18n('测试模式：直接调用analyze_branches函数，传入JSON文件路径'))
parser.add_argument('--test-apply-patch',help=i18n("""测试模式：直接调用apply_patch函数，传入JSON文件路径"""))
args, _ = parser.parse_known_args()


@update_docstring(i18n("""执行cvekit命令并返回结果"""))
def run_cvekit(action: str, params: dict) -> dict:
    try:
        env = os.environ.copy()
        # 构建基础命令
        cmd = ['cvekit', f'--action={action}']
        # 所有action都使用JSON格式输出，确保解析一致性
        cmd.append('--json')
        
        # 添加公共参数
        if 'cve_id' in params and params["cve_id"]:
            cmd.append(f'--cve-id={params["cve_id"]}')
        if args.gitee_token:
            cmd.append(f'--gitee-token={args.gitee_token}')
        elif 'gitee_token' in params:
            cmd.append(f'--gitee-token={params["gitee_token"]}')
        
        # 添加动作特定参数
        if action == 'setup-env':
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')
                
        elif action == 'analyze-branches':
            if 'branches' in params:
                cmd.append(f'--branches={params["branches"]}')
            if 'signer_name' in params:
                cmd.append(f'--signer-name={params["signer_name"]}')
            if 'signer_email' in params:
                cmd.append(f'--signer-email={params["signer_email"]}')
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
        
        elif action == 'backport':
            if 'cve_id' in params:
                cmd.append(f'--cve-id={params["cve_id"]}')
            if 'branch' in params:
                cmd.append(f'--branch={params["branch"]}')
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')
            if 'api_key' in params:
                cmd.append(f'--api-key={params["api_key"]}')
            if 'llm_provider' in params:
                cmd.append(f'--llm-provider={params["llm_provider"]}')
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
        
        elif action == 'apply-patch':
            if 'patch_path' in params:
                cmd.append(f'--patch-path={params["patch_path"]}')
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')
            if 'branch' in params:
                cmd.append(f'--branch={params["branch"]}')
            if 'signer_name' in params:
                cmd.append(f'--signer-name={params["signer_name"]}')
            if 'signer_email' in params:
                cmd.append(f'--signer-email={params["signer_email"]}')

        elif action == 'get-commits':
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')
                
        elif action == 'create-pr':
            if 'branch' in params:
                cmd.append(f'--branch={params["branch"]}')
            if 'fork_repo_url' in params:
                cmd.append(f'--fork-repo-url={params["fork_repo_url"]}')
            if 'repo_url' in params:
                cmd.append(f'--repo-url={params["repo_url"]}')
            if 'clone_dir' in params:
                cmd.append(f'--clone-dir={params["clone_dir"]}')

        result = subprocess.run(
            cmd,
            check=True,
            env = env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 尝试解析JSON输出
        # 如果输出中包含日志信息，尝试从最后提取JSON
        stdout_content = result.stdout.strip()
        
        try:
            return json.loads(stdout_content)
        except json.JSONDecodeError as e:
            # 如果直接解析失败，尝试从输出中提取JSON
            # JSON通常以 { 或 [ 开头，以 } 或 ] 结尾
            # 查找最后一个 { 或 [ 的位置
            json_start = -1
            json_end = -1
            
            for i in range(len(stdout_content) - 1, -1, -1):
                if stdout_content[i] == '{':
                    json_start = i
                    break
                elif stdout_content[i] == '[':
                    json_start = i
                    break
            
            if json_start >= 0:
                brace_count = 0
                bracket_count = 0
                json_end = json_start
                
                for i in range(json_start, len(stdout_content)):
                    char = stdout_content[i]
                    if char == '{':
                        brace_count += 1
                    elif char == '}':
                        brace_count -= 1
                    elif char == '[':
                        bracket_count += 1
                    elif char == ']':
                        bracket_count -= 1
                    
                    # 当所有括号都匹配时，找到JSON结束位置
                    if brace_count == 0 and bracket_count == 0:
                        json_end = i + 1
                        break
                
                if json_end > json_start:
                    json_str = stdout_content[json_start:json_end]
                    try:
                        return json.loads(json_str)
                    except json.JSONDecodeError as parse_error:
                        # 如果提取的JSON仍然无法解析，记录详细信息
                        logging.debug(i18n("提取的JSON片段无法解析: %s") % (str(parse_error)))
                        logging.debug(i18n("JSON片段: %s") % (json_str[:200]))  # 只记录前200个字符
            
            logging.error(i18n("cvekit输出非JSON格式: %s") % (str(e)))
            logging.error(i18n("输出内容前500字符: %s") % (stdout_content[:500]))  # 只记录前500个字符
            logging.error(i18n("输出内容后500字符: %s") % (stdout_content[-500:] if len(stdout_content) > 500 else stdout_content))  # 记录后500个字符
            return {"error": "Invalid JSON output", "output": stdout_content, "command": " ".join(cmd)}
        
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        # 过滤掉 stderr 中的 SyntaxWarning，只保留真正的错误信息
        if error_msg:
            lines = error_msg.split('\n')
            filtered_lines = []
            for line in lines:
                if 'SyntaxWarning' not in line and 'invalid escape sequence' not in line:
                    filtered_lines.append(line)
            error_msg = '\n'.join(filtered_lines).strip()
            # 如果过滤后没有内容，使用原始错误信息
            if not error_msg:
                error_msg = e.stderr if e.stderr else str(e)
        
        logging.error(i18n("cvekit执行失败: %s") % (str(error_msg)))
        try:
            if e.stderr:
                error_json = json.loads(e.stderr)
                return error_json
        except (json.JSONDecodeError, AttributeError):
            pass
        return {"error": error_msg, "command": " ".join(cmd)}

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第一步，必须严格按照顺序执行：
        1. 通过调用gitee的api，解析gitee issue URL并获取基本信息
        2. 将解析得到的issue_info以结构化格式清晰反馈给用户
        3. 明确告知用户获取到的以下信息：
           - issue_id: Issue编号
           - cve_id: CVE编号
           - org_name: 组织名称
           - repo_name: 仓库名称
           - affected_versions: 受影响版本列表
        4. 解析完成后可自动进入下一步
    """))
def parse_issue(
    cve_id: str = Field(..., description="cve id"),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    
    result = run_cvekit('parse-issue', {
        'cve_id': cve_id,
        'gitee_token': gitee_token
    })
    
    if 'error' in result:
        return i18n("解析Issue失败: %s") % (result['error'])
    
    data = result.get('data', {})
    res = i18n("已解析Issue: %s\n") % (data.get('issue_id', ''))
    res += f"- CVE ID: {data.get('cve_id', '')}\n"
    res += f"- Issue URL: {data.get('issue_url', '')}\n"
    res += i18n("- 组织: %s\n") % (data.get('org_name', ''))
    res += i18n("- 仓库: %s\n") % (data.get('repo_name', ''))
    res += i18n("- 受影响版本: %s\n") % (data.get('affected_versions', ''))
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第二步，必须严格按照顺序执行：
        1. 设置仓库环境，克隆官方仓库到指定目录
        2. 添加fork远程仓库
        3. 明确反馈执行结果：
           - 仓库克隆是否成功
           - 克隆目录的完整路径
           - fork远程是否添加成功
        4. 环境设置完成后可自动进入下一步
    """))
def setup_env(
    fork_repo_url: str = Field(..., description=i18n("Fork仓库URL")),
    clone_dir: str = Field(..., description=i18n("工作空间或克隆目录，本地克隆仓库在该目录所在的仓库名文件夹中")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> dict:

    result = run_cvekit('setup-env', {
        'fork_repo_url': fork_repo_url,
        'clone_dir': clone_dir,
        'gitee_token': gitee_token
    })
    
    if 'error' in result:
        return i18n("环境设置失败: %s") % (result['error'])
    
    res = i18n("环境设置成功！\n")
    res += i18n("- 仓库已克隆到: %s\n") % (clone_dir)
    res += i18n("- Fork远程仓库: %s\n") % (fork_repo_url)
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第三步，必须严格按照顺序执行：
        1. 获取漏洞相关的真实上游提交信息
        2. 明确反馈以下提交信息：
           - introduced: 引入漏洞的提交（commit hash和提交信息）
           - fixed: 修复漏洞的提交（commit hash和提交信息）
        3. 将获取到的commit信息以清晰格式告知用户
        4. 获取提交信息完成后可自动进入下一步
    """))
def get_commits(
    cve_id: str = Field(..., description="cve id"),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)")),
    clone_dir: Optional[str] = Field(None, description=i18n("克隆目录(可选)"))
) -> str:
    result = run_cvekit('get-commits', {
        'cve_id': cve_id,
        'gitee_token': gitee_token,
        'clone_dir': clone_dir
    })
    
    # Check for errors first
    if 'error' in result:
        return i18n("获取提交信息失败: %s") % (result['error'])
    
    res = i18n("已获取CVE %s的提交信息:\n") % (result.get('cve_id', ''))
    res += i18n("- 引入漏洞的提交: %s\n") % (result.get('introduced', ''))
    res += i18n("- 修复漏洞的提交: %s\n") % (result.get('fixed', ''))
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第四步，必须严格按照顺序执行：
        1. 分析introduced_commit在本地仓库的哪些分支被引入
        2. 检查每个分支是否已经被fixed（已修复）
        3. 对于未修复的分支，检查从上游获取的补丁直接应用是否存在冲突
        4. 对于需要调整的补丁，自动调用backport进行调整
        5. **必须完整展示分析结果**，包括：
           - 完整的分析结果表格，包含以下列：
             * 补丁ID
             * 目标分支
             * 是否受影响
             * 适配状态
             * 冲突点（补丁路径）
             * 建议调整文件
             * 是否存在冲突
             * 提交信息
             * 差异文件路径
           - 每个分支的详细信息（受影响状态、适配状态、补丁路径、差异文件等）
        6. **必须完整展示多选题格式**，清晰展示所有需要应用补丁的分支，格式如下：
           "请选择要在哪些分支应用补丁（可多选，输入分支名，用逗号分隔）：
           [A] 分支名1 - 适配状态: xxx, 补丁路径: xxx, 差异文件: xxx, 是否存在冲突: xxx
           [B] 分支名2 - 适配状态: xxx, 补丁路径: xxx, 差异文件: xxx, 是否存在冲突: xxx
           [C] 分支名3 - 适配状态: xxx, 补丁路径: xxx, 差异文件: xxx, 是否存在冲突: xxx
           ..."
        7. **重要**：必须将函数返回的完整结果（包括表格和多选题）完整展示给用户，不能简化或省略任何信息
        8. 等待用户明确选择要应用补丁的分支，只有用户选择后才可进入第五步
        注意：该步骤中的参数branches为kernel的分支名，和issue分析中的受影响版本并不一致，若用户未输入要分析的分支名，使用默认值即可
        注意：必须等待用户明确选择分支后才能执行后续步骤
        注意：函数返回的结果包含完整的分析表格和多选题格式，必须完整展示给用户，不能只显示简单的选项
    """))
def analyze_branches(
    cve_id: str = Field(..., description="cve id"),
    branches: Optional[str] = Field('OLK-5.10,OLK-6.6,master', description=i18n("要分析的分支列表，逗号分隔")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)")),
    clone_dir: Optional[str] = Field(None, description=i18n("克隆目录(可选)")),
    fork_repo_url: Optional[str] = Field(None, description=i18n("Fork仓库URL(可选)")),
    api_key: Optional[str] = Field(None, description=i18n("LLM API密钥(可选，用于自动调整补丁)")),
    llm_provider: Optional[str] = Field(None, description=i18n("LLM提供商(可选，默认openai)"))
) -> str:
    # 使用全局变量作为默认值
    if not gitee_token:
        gitee_token = default_gitee_token
    if api_key is None:
        # 若未显式传入 api_key，则回退到全局默认值（可能为空字符串，用于本地免鉴权模型）
        api_key = default_api_key
    if not llm_provider:
        llm_provider = default_llm_provider or 'openai'
    
    sorted_branches = sorted([branch.strip() for branch in branches.split(",")])
    cache_key = _get_cache_key(cve_id, ",".join(sorted_branches))
    cached_result = get_cached_data(BRANCHES_ANALYSIS_CACHE, cache_key)
   
    if cached_result:
        logging.info(f"[缓存命中] CVE {cve_id}, 分支: {branches}")
        return str(cached_result)
    
    result = run_cvekit('analyze-branches', {
        'cve_id': cve_id,
        'branches': branches,
        'gitee_token': gitee_token,
        'clone_dir': clone_dir,
        'fork_repo_url': fork_repo_url
    })
    
    if 'error' in result:
        return i18n("分支分析失败: %s") % result['error']
    
    if isinstance(result, dict):
        result = [result]
    
    if not result:
        return i18n("未找到受影响的分支")
    
    # 对于需要调整的分支，自动调用 backport（仅在有可用 LLM 配置时）
    for item in result:
        adapt_status = item.get(i18n('适配状态'), '')
        if adapt_status == i18n('需要调整'):
            target_branch = item.get(i18n('目标分支'), '')
            if target_branch:
                # 如果使用非本地 LLM 且未提供 api_key，则无法自动回移植，给出提示但不调用 backport
                if not api_key and (llm_provider or "").lower() != "local":
                    warn_msg = i18n(
                        "检测到分支 %s 需要适配，但未配置 LLM API_KEY（API_KEY 环境变量或命令行 --api-key）。"
                        " 已保留原始补丁路径，请手工在本地完成补丁适配，并在解决冲突后重新执行 `/create_pr`。"
                    ) % target_branch
                    logging.warning(warn_msg)
                    item[i18n('差异文件')] = warn_msg
                    # 保持适配状态为“需要调整”，提示用户手动处理
                    continue

                # 调用backport进行调整
                backport_result = run_cvekit(
                    'backport',
                    {
                        'cve_id': cve_id,
                        'branch': target_branch,
                        'clone_dir': clone_dir,
                        # 这里使用统一的 api_key 命名，run_cvekit 会映射为 --api-key 传给 cvekit CLI，
                        # 再由 CLI 映射为内部 openai_key 配置字段。
                        'api_key': api_key,
                        'llm_provider': llm_provider,
                        'fork_repo_url': fork_repo_url,
                        'gitee_token': gitee_token,
                    },
                )
                
                if 'error' not in backport_result:
                    # 调试信息：打印backport_result的完整结构
                    logging.debug(i18n("backport_result结构: %s") % json.dumps(backport_result, indent=2, ensure_ascii=False))
                    
                    # 更新结果：使用backport生成的补丁路径
                    # backport返回的结构：result['details']['backported_patch_path'] 和 result['details']['diff_path']
                    details = backport_result.get('details', {})
                    
                    # 如果details为空，尝试直接从backport_result获取（兼容不同的返回结构）
                    if not details:
                        details = backport_result
                    
                    # 获取调整后的补丁路径
                    backported_patch_path = details.get('backported_patch_path') or backport_result.get('backported_patch_path')
                    if backported_patch_path:
                        item[i18n('冲突点')] = backported_patch_path
                        item[i18n('适配状态')] = i18n('成功')
                        item[i18n('建议调整文件')] = backported_patch_path
                        item[i18n('是否存在冲突')] = i18n('是')
                        logging.info(i18n("backport成功: 更新冲突点/建议调整文件为 %s") % backported_patch_path)
                    
                        logging.info(f"缓存已更新: {cache_key} 中的冲突点/建议调整文件为 {backported_patch_path}")
                    else:
                        logging.warning(i18n("backport成功但未找到backported_patch_path"))

                    # 添加差异文件路径
                    diff_path = details.get('diff_path') or backport_result.get('diff_path')
                    if diff_path:
                        item[i18n('差异文件')] = diff_path
                        logging.info(i18n("backport成功: 差异文件为 %s") % diff_path)
                    else:
                        item[i18n('差异文件')] = 'N/A'
                        logging.warning(i18n("backport成功但未找到diff_path"))
                    
                    # 更新缓存
                    cached_result = get_cached_data(BRANCHES_ANALYSIS_CACHE, cache_key)
                    if cached_result:  
                        for cache_item in cached_result:
                            if cache_item.get(i18n("目标分支")) == target_branch:
                                if backported_patch_path:
                                    cache_item[i18n("冲突点")] = backported_patch_path
                                    cache_item[i18n("适配状态")] = i18n('成功')
                                    cache_item[i18n("建议调整文件")] = backported_patch_path
                                    cache_item[i18n("是否存在冲突")] = i18n('是')
                                
                                cache_item[i18n("差异文件")] = diff_path if diff_path else 'N/A'
                                break 
                        save_cache(BRANCHES_ANALYSIS_CACHE, cache_key, cached_result)
                        logging.info(i18n("缓存已更新: 分支 %s 的字段已同步")% target_branch)
                else:
                    delete_cache_key(BRANCHES_ANALYSIS_CACHE, cache_key)
                    error_msg = backport_result.get('error', '未知错误')
                    item[i18n('建议调整文件')] = i18n("backport失败: %s") % error_msg
                    item[i18n('差异文件')] = i18n("backport失败: %s") % error_msg
                    logging.error(i18n("backport失败: %s") % error_msg)
        else:
            # 对于不需要调整的分支，建议调整文件为N/A
            item[i18n('建议调整文件')] = 'N/A'
            item[i18n('是否存在冲突')] = i18n('否')
            item[i18n('差异文件')] = 'N/A'
    
    # 构建表格，添加"提交信息"、"差异文件"和"是否存在冲突"列
    table = i18n("| 补丁ID | 目标分支 | 是否受影响 | 适配状态 | 补丁路径 | 建议调整文件 | 差异文件 | 是否存在冲突 | 提交信息 |\n")
    table += "|--------|----------|------------|----------|--------|--------------|----------|--------------|----------|\n"
    
    for item in result:
        cve_id_val = item.get(i18n('补丁ID'), '')
        target_branch = item.get(i18n('目标分支'), '')
        is_affected = item.get(i18n('是否受影响'), '')
        adapt_status = item.get(i18n('适配状态'), '')
        conflict_point = item.get(i18n('冲突点'), '')
        suggess_file = item.get(i18n('建议调整文件'), '')
        commit_message = item.get(i18n('提交信息'), 'N/A')
        has_conflict = item.get(i18n('是否存在冲突'), 'N/A')
        diff_file = item.get(i18n('差异文件'), 'N/A')
        
        # 截断过长的路径
        if len(conflict_point) > 50:
            conflict_point = conflict_point[:47] + '...'
        if len(diff_file) > 50:
            diff_file = diff_file[:47] + '...'
        table += f"| {cve_id_val} | {target_branch} | {is_affected} | {adapt_status} | {conflict_point} | {suggess_file} | {diff_file} | {has_conflict} | {commit_message} |\n"

    res = i18n("【重要】分支分析结果 - 请完整展示以下所有信息给用户：\n")
    res += "=" * 60 + "\n"
    res += i18n("分支分析完成，共发现 %d 个受影响的分支:\n\n") % (len(result))
    res += table
    res += "\n" + "=" * 60 + "\n"
    res += i18n("请选择要在哪些分支应用补丁（可多选，输入分支名，用逗号分隔）：\n")
    
    # 生成多选题格式，只显示需要应用补丁的分支
    option_letter = ord('A')
    branch_options = []
    for item in result:
        target_branch = item.get(i18n('目标分支'), '')
        is_affected = item.get(i18n('是否受影响'), '')
        adapt_status = item.get(i18n('适配状态'), '')
        conflict_point = item.get(i18n('冲突点'), '')
        has_conflict = item.get(i18n('是否存在冲突'), 'N/A')
        diff_file = item.get(i18n('差异文件'), 'N/A')
        
        # 只显示受影响或无法判断的分支，确保可继续往下走
        # 判断是否为受影响/无法判断分支：值可能是"受影响"、"是"、"无法判断"或其他表示受影响的文本
        is_affected_str = str(is_affected)
        is_affected_lower = is_affected_str.lower()
        # 检查是否为受影响或无法判断分支（支持多种格式：受影响、是、affected、无法判断等）
        is_branch_affected = (
            is_affected_str in [i18n('受影响'), '受影响', i18n('是'), '是'] or
            '受影响' in is_affected_str or
            'affected' in is_affected_lower or
            is_affected_str in [i18n('无法判断'), '无法判断'] or
            '无法判断' in is_affected_str
        )
        if is_branch_affected:
            status_desc = i18n("适配状态: %s") % adapt_status
            if conflict_point:
                status_desc += i18n(", 补丁路径: %s") % conflict_point
            if diff_file != 'N/A':
                status_desc += i18n(", 差异文件: %s") % diff_file
            if has_conflict != 'N/A':
                status_desc += i18n(", 是否存在冲突: %s") % has_conflict
            
            option = f"[{chr(option_letter)}] {target_branch} - {status_desc}"
            branch_options.append((chr(option_letter), target_branch, option))
            res += option + "\n"
            option_letter += 1
    
    if not branch_options:
        res += i18n("未找到需要应用补丁的分支")
    else:
        res += "\n" + i18n("请输入要选择的分支选项（例如: A,B,C 或直接输入分支名，用逗号分隔）")
    
    res += "\n" + "=" * 60 + "\n"
    res += i18n("【重要提示】以上信息必须完整展示给用户，包括完整的分析表格和多选题格式，不能简化或省略任何信息。")
    
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第五步，必须严格按照顺序执行：
        1. 对于用户在第四步中选择的分支，应用相对应的patch
        2. 参数说明：
           - branch: 用户在第四步中选择的分支名（必须从第四步的选择结果中获取）
           - patch_path: 第四步分析结果中该分支对应的冲突点或补丁路径
           - clone_dir: 本地克隆目录, 必须与第四步使用的 clone_dir 保持一致
        3. 执行补丁应用操作：
           - 切换到指定分支
           - 应用补丁文件
           - 若patch应用成功，提交更改
           - 将修复后的分支推送到fork仓库
        4. 明确反馈执行结果：
           - 补丁应用是否成功
           - 目标分支名称
           - 修复分支名称（如果创建了新分支）
           - 应用的补丁路径
           - 如果失败，明确告知失败原因和解决建议
        5. 若patch应用失败，提示用户尝试解决冲突后重新执行该步骤
        6. 对于用户在第四步中选择的每个分支，都需要单独调用此函数执行
        注意：本地代码位于工作空间里面的仓库名所在的目录
    """))
def apply_patch(
    cve_id: str = Field(..., description="cve id"),
    branch: Optional[str] = Field(description=i18n("要应用patch的分支名")),
    fork_repo_url: Optional[str] = Field(description=i18n("fork仓库url")),
    patch_path: Optional[str] = Field(description=i18n("patch路径")),
    clone_dir: Optional[str] = Field(None, description=i18n("克隆目录(可选，与第四步保持一致)")),
    signer_name: Optional[str] = Field(description=i18n("提交者姓名")),
    signer_email: Optional[str] = Field(None, description=i18n("提交者邮箱")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    
    if not os.path.exists(patch_path):
        branches = sorted([branch.strip() for branch in args.branches_to_analyze.split(',')])
        cache_key = _get_cache_key(cve_id, ','.join(branches))
        cached_result = get_cached_data(BRANCHES_ANALYSIS_CACHE, cache_key)
        patch_path = ""
        for res in cached_result:
            if res[i18n('目标分支')]==branch:
                patch_path = res[i18n("冲突点")]
                break
    
    result = run_cvekit('apply-patch', {
        'cve_id': cve_id,
        'branch': branch,
        'fork_repo_url': fork_repo_url,
        'patch_path': patch_path,
        'clone_dir': clone_dir,
        'signer_name': signer_name,
        'signer_email': signer_email,
        'gitee_token': gitee_token
    })

    if 'error' in result or 'error' in result.get('status'):
        error_msg = result.get('error', '未知错误')
        res = i18n("应用patch失败！\n")
        res += i18n("- 目标分支: %s\n") % (branch)
        res += i18n("- 补丁路径: %s\n") % (patch_path)
        res += i18n("- 失败原因: %s\n") % (error_msg)
        res += i18n("请尝试解决冲突后重新执行该步骤")
        return res
    
    fix_branch = result.get('fix_branch', '')
    res = i18n("补丁应用成功！\n")
    res += i18n("- 目标分支: %s\n") % (branch)
    res += i18n("- 修复分支: %s\n") % (fix_branch)
    res += i18n("- 补丁路径: %s\n") % (patch_path)
    return res

@mcp.tool()
@update_docstring(i18n("""
    该函数是CVE修复流程的第六步，必须严格按照顺序执行（仅当第五步补丁应用成功后才可执行）：
        1. 对于第五步中修复成功的分支，创建并提交Pull Request
        2. 参数说明：
           - branch: 受影响分支名，作为提交PR的目标分支
           - repo_url: 目标仓库URL（必须由用户显式提供）
           - fork_repo_url: fork仓库URL
           - clone_dir: 本地克隆目录，必须与第四步/第五步使用的 clone_dir 保持一致
        3. 执行PR创建操作：
           - 创建PR标题（包含CVE ID和分支信息）
           - 创建PR描述（包含修复详情）
           - 提交PR到目标仓库
        4. 明确反馈执行结果：
           - PR是否创建成功
           - PR的完整URL链接
           - PR编号和标题
           - 如果失败，明确告知失败原因
        5. 对于第五步中每个成功应用补丁的分支，都需要单独调用此函数创建PR
    """))
def create_pr(
    cve_id: str = Field(..., description="cve id"),
    branch: Optional[str] = Field(None, description=i18n("受影响分支名，目标分支")),
    fork_repo_url: Optional[str] = Field(None, description=i18n("fork仓库url")),
    repo_url: str = Field(..., description=i18n("目标仓库url")),
    clone_dir: Optional[str] = Field(None, description=i18n("克隆目录(可选，与第四/第五步保持一致)")),
    gitee_token: Optional[str] = Field(None, description=i18n("Gitee访问令牌(可选)"))
) -> str:
    result = run_cvekit('create-pr', {
        'cve_id': cve_id,
        'branch': branch,
        'fork_repo_url': fork_repo_url,
        'repo_url': repo_url,
        'clone_dir': clone_dir,
        'gitee_token': gitee_token
    })
    if 'error' in result or 'error' in result.get('status'):
        error_msg = result.get('error', '未知错误')
        res = i18n("PR提交失败！\n")
        res += i18n("- 目标分支: %s\n") % (branch)
        res += i18n("- 目标仓库: %s\n") % (repo_url)
        res += i18n("- 失败原因: %s\n") % (error_msg)
        return res
    
    pr_url = result.get('pr_html_url', '')
    pr_number = result.get('pr_number', '')
    pr_title = result.get('pr_title', '')
    res = i18n("PR已成功提交！\n")
    res += i18n("- PR编号: %s\n") % (pr_number)
    res += i18n("- PR标题: %s\n") % (pr_title)
    res += i18n("- PR链接: %s\n") % (pr_url)
    res += i18n("- 目标分支: %s\n") % (branch)
    res += i18n("请确认PR是否创建成功")
    return res

def _init_defaults_from_args() -> None:
    """根据命令行参数初始化全局默认配置。"""
    global default_gitee_token, default_llm_provider, default_api_key

    if args.gitee_token:
        default_gitee_token = args.gitee_token
    if args.llm_provider:
        default_llm_provider = args.llm_provider
    if args.api_key:
        default_api_key = args.api_key


def _run_test_analyze_branches(config_path: str) -> int:
    """测试模式：从JSON文件读取参数并调用 analyze_branches。"""
    import sys
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            test_data = json.load(f)

        logger.info("=" * 60)
        logger.info("测试模式：直接调用 analyze_branches 函数")
        logger.info("=" * 60)
        logger.info("测试参数: %s", json.dumps(test_data, indent=2, ensure_ascii=False))
        logger.info("=" * 60)

        result = analyze_branches(
            cve_id=test_data.get("cve_id", ""),
            branches=test_data.get("branches", "OLK-5.10,OLK-6.6,master"),
            gitee_token=test_data.get("gitee_token") or default_gitee_token,
            clone_dir=test_data.get("clone_dir"),
            fork_repo_url=test_data.get("fork_repo_url"),
            # 兼容旧字段 openai_key，同时支持新的 api_key
            api_key=test_data.get("api_key") or test_data.get("openai_key") or default_api_key,
            llm_provider=test_data.get("llm_provider") or default_llm_provider,
        )

        logger.info("=" * 60)
        logger.info("函数执行结果:")
        logger.info("=" * 60)
        logger.info("%s", result)
        logger.info("=" * 60)
        return 0

    except FileNotFoundError:
        logger.error("错误: 找不到文件 %s", config_path)
        return 1
    except json.JSONDecodeError as e:
        logger.error("错误: JSON解析失败: %s", e)
        return 1
    except Exception as e:  # noqa: BLE001
        logger.exception("错误: %s", e)
        return 1

def _run_test_apply_patch(config_path: str) -> int:
    """测试模式：从JSON文件读取参数并调用 apply_patch"""
    import sys

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            test_data = json.load(f)

        logger.info("=" * 60)
        logger.info("测试模式：直接调用 apply-patch 函数")
        logger.info("=" * 60)
        logger.info("测试参数: %s", json.dumps(test_data, indent=2, ensure_ascii=False))
        logger.info("=" * 60)
        result = apply_patch(
            cve_id=test_data.get("cve_id", ""),
            branch=test_data.get("branch", "OLK-6.6"),
            gitee_token=test_data.get("gitee_token") or default_gitee_token,
            fork_repo_url=test_data.get("fork_repo_url"),
            signer_name=test_data.get("signer_name"),
            signer_email=test_data.get("signer_email")
        )

        logger.info("=" * 60)
        logger.info("函数执行结果:")
        logger.info("=" * 60)
        logger.info("%s", result)
        logger.info("=" * 60)
        return 0

    except FileNotFoundError:
        logger.error("错误: 找不到文件 %s", config_path)
        return 1
    except json.JSONDecodeError as e:
        logger.error("错误: JSON解析失败: %s", e)
        return 1
    except Exception as e:  # noqa: BLE001
        logger.exception("错误: %s", e)
        return 1

def main() -> None:
    """脚本入口：根据参数决定运行模式。"""
    _init_defaults_from_args()

    if args.test_analyze_branches:
        import sys

        exit_code = _run_test_analyze_branches(args.test_analyze_branches)
        sys.exit(exit_code)
    
    if args.test_apply_patch:
        import sys

        exit_code = _run_test_apply_patch(args.test_apply_patch)
        sys.exit(exit_code)
    # 正常模式：运行MCP服务器
    mcp.run()


if __name__ == "__main__":
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )

    main()