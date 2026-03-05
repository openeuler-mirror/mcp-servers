import logging
import os
import re
import shutil
import tempfile
import subprocess
from cvekit.utils.patch import getUrlText, read_commit_id_form_url
from cvekit.utils.gitee import setup_repository
from .patch_validation import ensure_source0_tarball, validate_patch_paths, validate_patch_paths_in_tarball
from cvekit.utils.env_loader import get_gitee_token
logger = logging.getLogger(__name__)


def download_package_patch(
    commit_url,
    patch_dir,
    cve_id,
    clone_dir=None,
    rpm_name=None,
    branch="master",
    repo_url_template=None,
):
    """下载并校验补丁文件，并基于源码仓库或tarball做路径校验"""
    # Lazy import to ensure cve_tracking_reuse path is configured before use.
    from core.download.save import _patch_url, _file

    out_files = []
    failed_commits = []

    # 对src-openeuler中的软件包内容进行下载，默认路径是"https://gitcode.com/src-openeuler/{rpm}.git"，可以通过修改repo_url_template修改路径
    repo_url_template = repo_url_template or "https://gitcode.com/src-openeuler/{rpm}.git"
    if "{rpm}" in repo_url_template:
        repo_url = repo_url_template.format(rpm=rpm_name)
    else:
        repo_url = repo_url_template

    if clone_dir and rpm_name:
        setup_repository(fork_repo_url=repo_url,
                          gitee_token=get_gitee_token(), 
                          clone_dir=clone_dir, 
                          branch_name=branch, 
                          force_refresh=True)

    # src-openeuler中的软件包内容包含源代码压缩包、spec文件以及已经修复的漏洞的patch文件
    # 为了验证当前找到的patch文件是否适用于当前软件包的源代码，需要先获取源代码压缩包，并解压
    # 源代码压缩包往往记录在下载目录中的spec文件的Source0字段中
    source0_tarball = None
    source_root = os.path.join(clone_dir, rpm_name)
    if source_root:
        source0_tarball = ensure_source0_tarball(source_root, rpm_name=rpm_name)

    def _validate_patch_text(patch_text: str, patch_path: str = "") -> bool:
        """
        检查patch内容是否与源代码路径匹配
        """     
        if source0_tarball:
            ok = validate_patch_paths_in_tarball(patch_text, source0_tarball)
        elif source_root:
            ok = validate_patch_paths(patch_text, source_root)
        else:
            ok = False
        if not ok:
            logger.warning(f"ensure_patch_file: 补丁文件{patch_path}与源代码路径不匹配")
            if patch_path and os.path.exists(patch_path):
                os.remove(patch_path)
            return False
        return True
    
    raw_commit_url = commit_url.get("url") if isinstance(commit_url, dict) else commit_url
    if not raw_commit_url:
        logger.warning("ensure_patch_file: commit url 为空，无法下载 patch")
        failed_commits.append(raw_commit_url)
        return out_files, failed_commits

    patch_url = _patch_url(raw_commit_url) or raw_commit_url
    patch_path = _file(cve_id, patch_dir)

    # 1. 从网络获取补丁内容
    patch_text = getUrlText(url=patch_url)

    # 2. 校验补丁内容不为空
    if not patch_text:
        logger.warning("ensure_patch_file: 从网络获取补丁失败或内容为空，尝试本地生成: %s", patch_url)
        # 如果补丁内容为空，转为本地生成patch
        try:
            local_patch = generate_patch_from_commit_url(raw_commit_url, output_dir=patch_dir, cve_id=cve_id)
            with open(local_patch, "r", encoding="utf-8") as f:
                local_patch_text = f.read()
            # 校验patch内容是否与源代码路径匹配
            if not _validate_patch_text(local_patch_text, local_patch):
                logger.warning("ensure_patch_file: 本地生成 patch 校验失败: %s", raw_commit_url)
                failed_commits.append(raw_commit_url)
                return out_files, failed_commits
            out_files.append(local_patch)
        except Exception as exc:
            logger.warning("ensure_patch_file: 本地生成 patch 失败: %s, err=%s", raw_commit_url, exc)
            failed_commits.append(raw_commit_url)
        return out_files, failed_commits

    first_non_empty_line = ""
    for line in patch_text.splitlines():
        if line.strip():
            first_non_empty_line = line
            break
    if not first_non_empty_line:
        logger.warning("ensure_patch_file: 从网络获取的补丁内容只有空行，尝试本地生成: %s", patch_url)
        try:
            local_patch = generate_patch_from_commit_url(raw_commit_url, output_dir=patch_dir, cve_id=cve_id)
            with open(local_patch, "r", encoding="utf-8") as f:
                local_patch_text = f.read()
            if not _validate_patch_text(local_patch_text, local_patch):
                logger.warning("ensure_patch_file: 本地生成 patch 校验失败: %s", raw_commit_url)
                failed_commits.append(raw_commit_url)
                return out_files, failed_commits
            out_files.append(local_patch)
        except Exception as exc:
            logger.warning("ensure_patch_file: 本地生成 patch 失败: %s, err=%s", raw_commit_url, exc)
            failed_commits.append(raw_commit_url)
        return out_files, failed_commits
        
    # 3. 校验补丁内容首行是否满足格式"From xxx"或者"diff --git "
    if not (
        first_non_empty_line.startswith("From ")
        or first_non_empty_line.startswith("diff --git ")
    ):
        logger.error(
            "ensure_patch_file: 从网络获取的内容疑似不是有效 patch，首行: %s",
            first_non_empty_line[:200],
        )
        # 如果补丁内容为空，转为本地生成patch
        try:
            local_patch = generate_patch_from_commit_url(raw_commit_url, output_dir=patch_dir, cve_id=cve_id)
            with open(local_patch, "r", encoding="utf-8") as f:
                local_patch_text = f.read()
            # 校验patch内容是否与源代码路径匹配
            if not _validate_patch_text(local_patch_text, local_patch):
                logger.warning("ensure_patch_file: 本地生成 patch 校验失败: %s", raw_commit_url)
                failed_commits.append(raw_commit_url)
                return out_files, failed_commits
            out_files.append(local_patch)
        except Exception as exc:
            logger.warning("ensure_patch_file: 本地生成 patch 失败: %s, err=%s", raw_commit_url, exc)
            failed_commits.append(raw_commit_url)
        return out_files, failed_commits

    logger.info("ensure_patch_file: 从网络获取到有效 patch 内容: %s", patch_url)

    # 校验网络获取的patch内容是否与源代码路径匹配
    if not _validate_patch_text(patch_text):
        logger.warning("ensure_patch_file: 网络 patch 校验失败: %s", raw_commit_url)
        failed_commits.append(raw_commit_url)
        return out_files, failed_commits

    with open(patch_path, "w", encoding="utf-8") as f:
        f.write(patch_text)
    out_files.append(patch_path)

    logger.info("ensure_patch_file: 已从网络获取并写入 patch 文件: %s", patch_path)
    return out_files, failed_commits

def generate_patch_from_commit_url(commit_url: str, output_dir: str = ".", cve_id: str = "") -> str:
    """
    基于commit URL克隆仓库并生成patch文件，完成后清理临时仓库。
    生成的文件名为 fix-cve-{commit-id}.patch
    """
    patch_dir = os.path.join(output_dir, cve_id)
    commit_hash = read_commit_id_form_url(commit_url)
    if not commit_hash:
        match = re.search(r"/commit/([0-9a-f]{7,40})", commit_url)
        if match:
            commit_hash = match.group(1)
    if not commit_hash:
        raise RuntimeError(f"无法从URL提取commit ID: {commit_url}")

    # 处理各种类型的commit url，提取仓库url
    if "/commit/" in commit_url:
        repo_url = commit_url.split("/commit/")[0]
    else:
        repo_url = commit_url.split("?", 1)[0].rstrip("/")
        if repo_url.endswith("/commit"):
            repo_url = repo_url[: -len("/commit")]

    if not repo_url.endswith(".git") and ".git/" in repo_url:
        repo_url = repo_url.split(".git/")[0] + ".git"

    temp_dir = tempfile.mkdtemp(prefix="cvekit-repo-")
    repo_dir = os.path.join(temp_dir, "repo")
    patch_path = os.path.abspath(os.path.join(patch_dir, f"fix-cve-{commit_hash}.patch"))

    try:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, repo_dir],
                check=True,
                capture_output=True,
                text=True,
                timeout=300
            )
            logger.info("generate_patch_from_commit_url: 已从 %s 克隆仓库到 %s", repo_url, repo_dir)
            # 拉取目标 commit，确保本地有该提交对象
            subprocess.run(
                ["git", "-C", repo_dir, "fetch", "--depth", "1", "origin", commit_hash],
                check=False,
                capture_output=True,
                text=True,
                timeout=120
            )
            logger.info("generate_patch_from_commit_url: 已从 %s 提取 commit %s", repo_url, commit_hash)
            # 对指定 commit 生成 patch 文件
            subprocess.run(
                ["git", "-C", repo_dir, "format-patch", "-1", commit_hash, "-o", temp_dir],
                check=True,
                capture_output=True,
                text=True,
                timeout=120
            )
            logger.info("generate_patch_from_commit_url: 已在 %s 生成 patch 文件: %s", temp_dir, patch_files[0])
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or "").strip()
            stdout = (exc.stdout or "").strip()
            logger.error(
                "generate_patch_from_commit_url: 本地生成 patch 失败，cmd=%s, rc=%s, stderr=%s, stdout=%s",
                exc.cmd,
                exc.returncode,
                stderr[:500],
                stdout[:500],
            )
            raise
        patch_files = [f for f in os.listdir(temp_dir) if f.endswith(".patch")]
        if not patch_files:
            raise RuntimeError("未生成patch文件")
        generated_patch = os.path.join(temp_dir, patch_files[0])
        os.makedirs(patch_dir, exist_ok=True)
        if os.path.exists(patch_path):
            os.remove(patch_path)
        shutil.move(generated_patch, patch_path)
        logger.info("generate_patch_from_commit_url: 已在本地生成 patch 文件: %s", patch_path)
        return patch_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
