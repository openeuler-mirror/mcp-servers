import re
import logging
import time
from .cache import (
    cached,
    _get_cache_key,
    COMMITS_CACHE,
)
from .patch import getUrlText, get_upstream_commit_from_url

logger = logging.getLogger(__name__)


@cached(
    COMMITS_CACHE,
    key_builder=lambda cve_id, use_cache=True: _get_cache_key(cve_id),
    use_cache_kw="use_cache",
    # 兼容旧版本缓存结构：{"introduced": "...", "fixed": "..."}
    load_transform=lambda v: (
        (v.get("introduced"), v.get("fixed"))
        if isinstance(v, dict) and "introduced" in v and "fixed" in v
        else v
    ),
)
def get_vulnerability_commits(cve_id: str, use_cache: bool = True) -> tuple[str, str]:
    """
    获取漏洞相关的真实上游提交信息
    
    Args:
        cve_id: CVE ID
        use_cache: 是否使用缓存
    
    Returns:
        (introduced_commit, fixed_commit): 真实的上游引入提交和修复提交
    """
    logger.info(f"==========解析linux-cve-announce页面的两组commit id============")
    cve_announce_base_url = "https://lore.kernel.org/linux-cve-announce/"
    try:
        search_results_html = getUrlText(f"{cve_announce_base_url}?q={cve_id}")
    except Exception as e:
        logger.error(f"Failed to fetch vulnerability commits: {str(e)}")
        return None, None
    
    cve_detail_link_pattern = re.compile(f".*?<pre>1.*?<b><a.*?href=\"(?P<href>.*?)\">{cve_id}.*?", re.S)
    commit_section_pattern = re.compile(
        ".*?Affected and fixed versions.*?===========================(?P<href_text>.*?)Please see <a", re.S)
    cve_detail_link_match = cve_detail_link_pattern.search(search_results_html)
    
    introduced_commit = None
    fixed_commit = None
    
    if cve_detail_link_match:
        detail_url = cve_detail_link_match.group("href")
        commit_page_html = getUrlText(f"{cve_announce_base_url}{detail_url}")
        commit_section_match = commit_section_pattern.search(commit_page_html)
        if commit_section_match:
            commit_section_text = commit_section_match.group("href_text").strip()
            commit_lines = commit_section_text.split("\n")
            
            # 查找第一个引入提交和第一个修复提交
            for commit_line in commit_lines:
                if introduced_commit and fixed_commit:
                    break
                    
                line = commit_line.strip()
                if not line:
                    continue
                    
                # 移除开头的"Issue "（如果有）
                if line.startswith("Issue "):
                    line = line[6:]
                parts = line.split(' and ')
                
                for part in parts:
                    words = part.split()
                    if len(words) < 5:
                        continue
                        
                    if words[0] == 'introduced' and introduced_commit is None:
                        commit_hash = words[5]
                        commit_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={commit_hash}"
                        upstream_commit = get_upstream_commit_from_url(commit_url)
                        # 如果找不到upstream commit，使用原始commit作为备选
                        if upstream_commit:
                            introduced_commit = upstream_commit
                        else:
                            logger.error(f"无法获取introduced commit的upstream版本，使用原始commit: {commit_hash}")
                        
                    elif words[0] == 'fixed' and fixed_commit is None:
                        commit_hash = words[5]
                        commit_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={commit_hash}"
                        upstream_commit = get_upstream_commit_from_url(commit_url)
                        # 如果找不到upstream commit，使用原始commit作为备选
                        if upstream_commit:
                            fixed_commit = upstream_commit
                        else:
                            logger.error(f"无法获取fixed commit的upstream版本，使用原始commit: {commit_hash}")
    
    logger.info(f"introduced_commit: {introduced_commit}, fixed_commit: {fixed_commit}")
    
    return introduced_commit, fixed_commit