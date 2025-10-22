import re
import logging
import time
from .cache import get_cached_data, save_cache
from .patch import getUrlText, get_upstream_commit_from_url

logger = logging.getLogger(__name__)

def get_vulnerability_commits(cve_id: str, use_cache=True) -> tuple[str, str]:
    """
    获取漏洞相关的真实上游提交信息
    
    Args:
        cve_id: CVE ID
        use_cache: 是否使用缓存
    
    Returns:
        (introduced_commit, fixed_commit): 真实的上游引入提交和修复提交
    """
    from .cache import _get_cache_key, COMMITS_CACHE
    cache_key = _get_cache_key(cve_id)

    if use_cache:
        cached = get_cached_data(COMMITS_CACHE, cache_key)
        if cached and "introduced" in cached and "fixed" in cached:
            logger.debug(f"[缓存命中] CVE {cve_id}")
            return cached["introduced"], cached["fixed"]
    
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
    commit_hash_pattern = re.compile(r'commit (\w+)', re.I)
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
                line = line.lower()
                    
                if 'introduced' in line and not introduced_commit:
                    intro_pos = line.find('introduced')
                    hash_match = commit_hash_pattern.search(line, pos=intro_pos)
                    if hash_match:
                        commit_hash = hash_match.group(1)
                        commit_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={commit_hash}" 
                        introduced_commit = get_upstream_commit_from_url(commit_url)
            
                if 'fixed' in line and not fixed_commit:
                    fixed_pos = line.find('fixed')
                    hash_match = commit_hash_pattern.search(line, pos=fixed_pos)
                    if hash_match:
                        commit_hash = hash_match.group(1)
                        commit_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/commit/?id={commit_hash}"
                        fixed_commit = get_upstream_commit_from_url(commit_url)
    
    logger.info(f"introduced_commit: {introduced_commit}, fixed_commit: {fixed_commit}")
    
    if use_cache and introduced_commit and fixed_commit:
        save_cache(COMMITS_CACHE, cache_key, {
            "introduced": introduced_commit,
            "fixed": fixed_commit
        })

    return introduced_commit, fixed_commit