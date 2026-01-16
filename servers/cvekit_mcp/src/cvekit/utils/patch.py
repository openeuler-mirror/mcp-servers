import requests
import logging
import curl_cffi
import re
import time
import os
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
            # 先用 curl_cffi 请求
            r = curl_cffi.get(
                url,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    # 添加一个正常浏览器的 UA，避免被部分站点（如 lore.kernel.org）直接 403 拒绝
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
                verify=False,
                proxies=proxies,
                timeout=timeout
            )
            status = getattr(r, "status_code", None)
            if status and status != 200:
                logger.warning(f"curl_cffi 请求 {url} 返回非 200 状态码: {status}，尝试使用 requests 回退")
                # 使用 requests 再尝试一次，带浏览器 UA
                r2 = requests.get(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"
                        ),
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                    verify=False,
                    timeout=timeout,
                )
                r2.raise_for_status()
                return r2.text

            return r.text
        except Exception as e:
            logger.warning(f"Attempt {attempt+1} failed for {url}: {str(e)}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"All attempts failed for {url}")
                return ""


def ensure_patch_file(
    commit_hash: str,
    patch_path: str,
    clone_dir: str,
    patch_url: str | None = None,
) -> str:
    """
    通用的 patch 获取逻辑：
    1. 优先从本地 linux 仓库（clone_dir/linux）生成 patch；
    2. 如果本地生成失败或 linux 仓库不存在，则从网络获取 patch 文本；
    3. 对从网络获取的内容做简单校验，避免将 HTML 重定向页面当成 patch 使用。
    """
    image_dir = os.path.dirname(patch_path)
    linux_repo_path = os.path.join(clone_dir, "linux")

    # 1. 优先从本地 linux 仓库生成 patch
    if os.path.exists(linux_repo_path):
        try:
            logger.info(
                "ensure_patch_file: 从本地 linux 仓库生成 patch，"
                "执行 git format-patch -1 %s -o %s",
                commit_hash,
                image_dir,
            )
            import git  # 局部导入，避免循环依赖

            repo_linux = git.Repo(linux_repo_path)
            patch_file = repo_linux.git.format_patch(
                "-1",
                commit_hash,
                o=image_dir,
            )

            if patch_file:
                # format-patch 可能返回多行，这里取第一行文件名
                default_patch_name = patch_file.split("\n")[0].strip()
                default_patch_path = os.path.abspath(
                    os.path.join(image_dir, default_patch_name)
                )
                # 如果目标文件已存在且不是同一个文件，删除后再重命名
                if os.path.exists(patch_path) and default_patch_path != patch_path:
                    os.remove(patch_path)
                if default_patch_path != patch_path:
                    os.rename(default_patch_path, patch_path)
                logger.debug(
                    "ensure_patch_file: 已从本地 linux 仓库生成 patch 文件: %s",
                    patch_path,
                )
                return patch_path
            else:
                logger.warning(
                    "ensure_patch_file: git format-patch 没有生成文件，"
                    "尝试从网络获取补丁: %s",
                    commit_hash,
                )
        except Exception as e:
            logger.warning(
                "ensure_patch_file: 从本地 linux 仓库生成 patch 失败，将尝试从网络获取: %s",
                str(e),
            )

    # 2. 从网络获取 patch，并校验内容
    if patch_url is None:
        patch_url = (
            "https://git.kernel.org/pub/scm/linux/kernel/git/stable/linux.git/patch/"
            f"?id={commit_hash}"
        )

    logger.info("ensure_patch_file: 从网络获取补丁: %s", patch_url)
    patch_text = getUrlText(patch_url)

    if not patch_text:
        logger.error("ensure_patch_file: 从网络获取补丁失败或内容为空: %s", patch_url)
        raise RuntimeError("从网络获取补丁失败或内容为空")

    # 简单校验补丁内容是否看起来是有效的 patch
    first_non_empty_line = ""
    for line in patch_text.splitlines():
        if line.strip():
            first_non_empty_line = line
            break

    if not first_non_empty_line:
        logger.error("ensure_patch_file: 从网络获取的补丁内容只有空行")
        raise RuntimeError("网络获取的补丁内容无效（空内容）")

    if not (
        first_non_empty_line.startswith("From ")
        or first_non_empty_line.startswith("diff --git ")
    ):
        logger.error(
            "ensure_patch_file: 从网络获取的内容疑似不是有效 patch，首行: %s",
            first_non_empty_line[:200],
        )
        raise RuntimeError("网络获取的补丁内容不是有效 patch")

    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(patch_text)

    logger.debug("ensure_patch_file: 已从网络获取并写入 patch 文件: %s", patch_path)
    return patch_path

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

def get_upstream_commit_from_url(
    commit_url,
    max_retries=3,
    timeout=30,
    linux_repo_path: str | None = None,
):
    """从commit URL获取真实的上游commit ID
    
    Args:
        commit_url: commit URL
        max_retries: 最大重试次数
        timeout: 超时时间（秒）
    
    Returns:
        真实的上游commit ID，如果网络请求失败则返回None，如果请求成功但没匹配到则返回URL中的commit ID
    """
    # 尝试从 URL 中直接解析出 commit ID
    url_commit_hash = read_commit_id_form_url(commit_url)

    # 如果提供了本地 linux 仓库路径，且 URL 中带有 commit ID，
    # 优先在本地仓库中确认该 commit 是否存在，存在则直接视为 upstream commit，
    # 避免后续的网络请求和网页解析，提高性能。
    if linux_repo_path and url_commit_hash:
        try:
            if os.path.exists(linux_repo_path):
                import git  # 局部导入，避免循环依赖

                repo = git.Repo(linux_repo_path)
                repo.commit(url_commit_hash)  # 不存在会抛异常
                logger.debug(
                    "get_upstream_commit_from_url: 本地 linux 仓库中存在该 commit，直接视为 upstream: %s",
                    url_commit_hash,
                )
                return url_commit_hash
            else:
                logger.warning(
                    "get_upstream_commit_from_url: 本地 linux 仓库路径不存在，无法做本地 upstream 检查: %s",
                    linux_repo_path,
                )
        except Exception as e:
            logger.warning(
                "get_upstream_commit_from_url: 本地 linux 仓库中不存在该 commit 或检查失败，将尝试通过网络解析 upstream: %s",
                e,
            )

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
                logger.debug(
                    "无法从页面内容提取upstream commit，使用URL中的commit ID: %s（可能本身就是upstream commit）",
                    url_commit_hash,
                )
                return url_commit_hash
            
            logger.warning(f"无法从URL提取commit ID: {commit_url}")
            return None
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是超时错误
            is_timeout = "timeout" in error_msg.lower() or "timed out" in error_msg.lower()
            
            logger.warning(
                "处理commit URL失败 (尝试 %s/%s): %s: %s",
                attempt + 1,
                max_retries,
                commit_url,
                error_msg,
            )
            
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避
            else:
                # 最后一次尝试失败，如果是超时错误，返回None（不使用URL中的commit ID）
                if is_timeout:
                    logger.error(
                        "所有重试都失败（超时），无法获取upstream commit: %s",
                        commit_url,
                    )
                else:
                    # 其他类型的错误
                    logger.error(
                        "所有重试都失败，无法获取upstream commit: %s",
                        commit_url,
                    )

                break

    return None