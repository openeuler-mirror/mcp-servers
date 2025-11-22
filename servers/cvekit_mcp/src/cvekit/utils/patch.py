import requests
import logging
import curl_cffi
import re
import time
from urllib.parse import urlparse, parse_qs

from .http import get_with_retry

logger = logging.getLogger(__name__)


def get_cve_patch(patch_api_url: str) -> dict | None:
    """获取CVE补丁信息（优化版）
    
    Args:
        patch_api_url: 补丁API URL
    
    Returns:
        补丁信息字典 或 None（出错时）
    """
    try:
        logger.debug(f"请求补丁API: {patch_api_url}")
        response = get_with_retry(patch_api_url)
        response.raise_for_status()
        data = response.json()
        
        # 获取body中的非空字符串
        url_list = [item for item in data.get("body", []) if isinstance(item, str) and item.strip() != ""]
        
        # 优先查找.patch文件URL
        for url in url_list:
            if url.endswith('.patch'):
                # 从URL中提取commit hash
                commit_hash = url.split('/')[-1].replace('.patch', '')
                return {
                    "patch_url": url,
                    "hash": commit_hash
                }
        
        # 如果没有找到.patch文件，尝试从第一个URL获取commit hash
        if url_list:
            first_url = url_list[0]
            commit_hash = get_upstream_commit_from_url(first_url)
            if commit_hash:
                # 构造kernel.org的patch URL
                patch_url = f"https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/?id={commit_hash}"
                return {
                    "patch_url": patch_url,
                    "hash": commit_hash
                }
        
        logger.error("无法获取有效的补丁URL或commit hash")
        return None

    except Exception as e:
        logger.error(f"获取补丁信息失败: {str(e)}")
        return None

def getUrlText(url, max_retries=3, timeout=30):
    """Fetch URL text with retry and timeout handling"""
    for attempt in range(max_retries):
        try:
            proxies = {}
            r = curl_cffi.get(
                url,
                headers={"X-Requested-With": "XMLHttpRequest"},
                verify=False,
                proxies=proxies,
                timeout=timeout
            )
            return r.text
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {url}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"All attempts failed for {url}")
                return ""

def remove_leading_substring(s, substr):
    """移除字符串前面所有连续的指定子字符串"""
    if not s or not substr:
        return s
    substr_len = len(substr)
    while s.startswith(substr):
        s = s[substr_len:]
    return s

def read_commit_id_form_url(url):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    commit_hash = query_params.get('id', [None])[0]

    if not commit_hash:
        logger.warning(f"无法从URL提取commit ID: {url}")
        return None

    return commit_hash

def get_upstream_commit_from_url(commit_url, max_retries=3, timeout=30):
    """从commit URL获取真实的上游commit ID
    
    Args:
        commit_url: commit URL
        max_retries: 最大重试次数
        timeout: 超时时间（秒）
    
    Returns:
        真实的上游commit ID，如果网络请求失败则返回None，如果请求成功但没匹配到则返回URL中的commit ID
    """
    for attempt in range(max_retries):
        try:
            r = curl_cffi.get(
                commit_url,
                headers={"X-Requested-With": "XMLHttpRequest"},
                verify=False,
                proxies={},
                timeout=timeout
            )
            final_url = r.url
            commit_hash = None
            
            # 尝试第一种格式: commit <hash> upstream
            pattern1 = re.compile(r"<div class='commit-msg'>commit (?P<hash>.*?) upstream", re.S)
            match1 = pattern1.search(r.text)
            if match1:
                commit_hash = match1.group('hash').strip()
                logger.debug(f"从格式1提取到upstream commit: {commit_hash}")
                return commit_hash
            
            # 尝试第二种格式: [ Upstream commit <hash> ] 或 Upstream commit <hash>
            # 匹配带方括号或不带方括号的格式（方括号可选）
            pattern2 = re.compile(r"\[?\s*Upstream commit\s+(?P<hash>[0-9a-f]{12,40})\s*\]?", re.S | re.I)
            match2 = pattern2.search(r.text)
            if match2:
                commit_hash = match2.group('hash')
                logger.debug(f"从格式2提取到upstream commit: {commit_hash}")
                return commit_hash
            
            # 如果所有格式都没匹配到，说明这个commit可能本身就是upstream commit
            # 从URL中提取commit ID（这是正常情况，不是错误）
            url_commit_hash = read_commit_id_form_url(final_url)
            if url_commit_hash:
                logger.debug(f"无法从页面内容提取upstream commit，使用URL中的commit ID: {url_commit_hash}（可能本身就是upstream commit）")
                return url_commit_hash
            
            logger.warning(f"无法从URL提取commit ID: {commit_url}")
            return None
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是超时错误
            is_timeout = "timeout" in error_msg.lower() or "timed out" in error_msg.lower()
            
            logger.warning(f"处理commit URL失败 (尝试 {attempt+1}/{max_retries}): {commit_url}: {error_msg}")
            
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避
            else:
                # 最后一次尝试失败，如果是超时错误，返回None（不使用URL中的commit ID）
                if is_timeout:
                    logger.error(f"所有重试都失败（超时），无法获取upstream commit: {commit_url}")
                    return None
                else:
                    # 其他类型的错误，也返回None（不使用URL中的commit ID）
                    logger.error(f"所有重试都失败，无法获取upstream commit: {commit_url}")
                    return None
    
    return None