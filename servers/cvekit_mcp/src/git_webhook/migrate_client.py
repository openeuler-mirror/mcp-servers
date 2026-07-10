import re
from typing import List, Dict, Any
from urllib.parse import urlparse


# ---- 错误类型 ----
class MigrateError(Exception):
    def __init__(self, error_type: str, message: str, conflict_files: List[str] | None = None):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.conflict_files = conflict_files or []


# ---- PR URL 解析 ----
def parse_pr_url(pr_url: str) -> Dict[str, str]:
    """
    解析 PR 或仓库 URL，从路径中提取 owner/repo。
    支持任意平台（Gitee / GitCode / AtomGit / kernel.org 等）。
    返回 {"platform": "...", "owner": "...", "repo": "...", "pr_number": "..."}。
    """
    if not pr_url:
        raise MigrateError("INVALID_PR_URL", "PR URL 不能为空")

    parsed = urlparse(pr_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/").replace(".git", "")

    # 尝试匹配 /owner/repo/pulls/number
    m = re.search(r"/([^/]+)/([^/]+)/pulls?/(\d+)$", path)
    if m:
        return {
            "platform": host,
            "owner": m.group(1),
            "repo": m.group(2),
            "pr_number": m.group(3),
        }

    # 没有 PR 编号时，取路径最后两段作为 owner/repo
    m = re.search(r"/([^/]+)/([^/]+)$", path)
    if m:
        return {
            "platform": host,
            "owner": m.group(1),
            "repo": m.group(2),
            "pr_number": "",
        }

    raise MigrateError("INVALID_PR_URL", f"URL 格式无法解析 owner/repo: {pr_url}")


def parse_target_repo_url(target_url: str) -> Dict[str, str]:
    """
    解析目标仓库 URL，从路径中提取 owner/repo，支持任意平台。
    支持 HTTPS 和 SSH 格式。
    """
    target_url = target_url.strip()

    # SSH 格式: git@host:owner/repo.git
    m_ssh = re.match(r"^git@([^:]+):(.+?)(?:\.git)?$", target_url)
    if m_ssh:
        host = m_ssh.group(1).lower()
        path = m_ssh.group(2).rstrip("/")
        parts = path.split("/")
        if len(parts) < 2:
            raise MigrateError("INVALID_PR_URL", f"目标仓库 URL 格式不正确: {target_url}")
        return {"platform": host, "owner": parts[0], "repo": parts[1], "url": target_url}

    # HTTPS 格式: https://host/.../owner/repo.git
    parsed = urlparse(target_url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/").replace(".git", "")

    m = re.search(r"/([^/]+)/([^/]+)$", path)
    if not m:
        raise MigrateError("INVALID_PR_URL", f"目标仓库 URL 格式无法解析 owner/repo: {target_url}")

    return {"platform": host, "owner": m.group(1), "repo": m.group(2), "url": target_url}


# ---- 输入校验 ----
def validate_email(email: str) -> bool:
    """校验邮箱格式。"""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


def validate_commit_id(commit_id: str) -> bool:
    """校验 Commit SHA 格式（40 位十六进制）。"""
    return bool(re.match(r"^[0-9a-fA-F]{40}$", commit_id))


def validate_migrate_params(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """校验迁移请求参数，返回错误列表。"""
    errors: List[Dict[str, str]] = []

    source_pr_url = (data.get("source_pr_url") or "").strip()
    if not source_pr_url:
        errors.append({"field": "source_pr_url", "message": "source_pr_url 不能为空"})
    else:
        try:
            parse_pr_url(source_pr_url)
        except MigrateError as e:
            errors.append({"field": "source_pr_url", "message": e.message})

    commit_id = (data.get("commit_id") or "").strip()
    if not commit_id:
        errors.append({"field": "commit_id", "message": "commit_id 不能为空"})
    elif not validate_commit_id(commit_id):
        errors.append({"field": "commit_id", "message": "commit_id 格式不正确，应为 40 位十六进制字符串"})

    signer_name = (data.get("signer_name") or "").strip()
    if not signer_name:
        errors.append({"field": "signer_name", "message": "signer_name 不能为空"})

    signer_email = (data.get("signer_email") or "").strip()
    if not signer_email:
        errors.append({"field": "signer_email", "message": "signer_email 不能为空"})
    elif not validate_email(signer_email):
        errors.append({"field": "signer_email", "message": "邮箱格式不正确"})

    target_repo_url = (data.get("target_repo_url") or "").strip()
    if not target_repo_url:
        errors.append({"field": "target_repo_url", "message": "target_repo_url 不能为空"})
    else:
        try:
            parse_target_repo_url(target_repo_url)
        except MigrateError as e:
            errors.append({"field": "target_repo_url", "message": e.message})

    return errors
