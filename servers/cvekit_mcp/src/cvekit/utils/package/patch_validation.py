import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile

logger = logging.getLogger(__name__)


def _collect_missing_files(patch_text, source_dir):
    """收集补丁中引用但在源码目录不存在的路径列表"""
    missing_files = []
    for line in patch_text.splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            path = line[4:].strip()
            if path == "/dev/null":
                continue
            if path.startswith("a/") or path.startswith("b/"):
                path = path[2:]
            if not path:
                continue
            full_path = os.path.join(source_dir, path)
            if not os.path.exists(full_path):
                missing_files.append(path)
    return missing_files

def validate_patch_paths(patch_text, source_dir):
    """校验补丁路径是否在给定源码目录中存在"""
    missing_files = _collect_missing_files(patch_text, source_dir)
    if missing_files:
        logger.error("ensure_patch_file: 补丁文件包含源代码不存在的路径: %s", ", ".join(missing_files))
        return False
    return True

def validate_patch_paths_in_tarball(patch_text, tarball_path):
    """解压tarball后在源码目录中校验补丁路径是否存在"""
    temp_dir = tempfile.mkdtemp(prefix="cvekit-src-")
    try:
        _safe_extract_tarball(tarball_path, temp_dir)
        source_root = _detect_source_root(temp_dir)
        missing_files = _collect_missing_files(patch_text, source_root)
        if missing_files:
            logger.error(
                "ensure_patch_file: 补丁文件包含源代码不存在的路径（tarball）: %s",
                ", ".join(missing_files),
            )
            return False
        return True
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

def ensure_source0_tarball(source_dir, rpm_name=None):
    """解析spec中的Source0并确认本地tarball是否存在"""
    spec_path = _find_spec_file(source_dir, rpm_name=rpm_name)
    if not spec_path:
        logger.error("ensure_patch_file: 未找到spec文件，无法进行Source0校验: %s", source_dir)
        raise RuntimeError(f"未找到RPM spec文件，请确保目录 {source_dir} 中包含正确的spec文件")

    source0_url = _parse_source0_url(spec_path)
    if not source0_url:
        logger.error("ensure_patch_file: 未解析到Source0，无法进行校验: %s", spec_path)
        raise RuntimeError(f"无法从spec文件 {spec_path} 中解析Source0 URL，请检查spec文件格式")

    source0_name = os.path.basename(source0_url.split("?", 1)[0])
    expected_path = os.path.join(source_dir, source0_name)
    if os.path.exists(expected_path):
        return expected_path

    tarballs = _list_tarballs(source_dir)
    if tarballs:
        logger.error(
            "ensure_patch_file: Source0指向%r，但本地tarball不匹配，现有: %s",
            source0_url,
            ", ".join(tarballs),
        )
    else:
        logger.error(
            "ensure_patch_file: Source0指向%r，但本地未找到任何tarball",
            source0_url,
        )
    raise RuntimeError("Source0上游tarball缺失或不匹配")

def _find_spec_file(source_dir, rpm_name=None):
    """在源码目录中查找RPM spec文件"""
    if rpm_name:
        candidate = os.path.join(source_dir, f"{rpm_name}.spec")
        if os.path.isfile(candidate):
            return candidate
    try:
        for entry in os.listdir(source_dir):
            if entry.endswith(".spec"):
                return os.path.join(source_dir, entry)
    except OSError:
        return None
    return None

def _parse_source0_url(spec_path):
    """解析spec中的Source0并展开基本宏"""
    try:
        with open(spec_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except OSError:
        return None

    name = _match_first(text, r"^\s*Name:\s*(\S+)")
    version = _match_first(text, r"^\s*Version:\s*(\S+)")
    rcstr = _match_first(text, r"^\s*%(?:global|define)\s+rcstr\s+(\S+)")
    source0_raw = _match_first(text, r"^\s*Source0:\s*(\S+)")
    if not source0_raw:
        return None

    macros = {
        "%{name}": name or "",
        "%{Name}": name or "",
        "%{version}": version or "",
        "%{Version}": version or "",
        "%{?rcstr}": rcstr or "",
    }
    for key, val in macros.items():
        source0_raw = source0_raw.replace(key, val)
    source0_raw = re.sub(r"%{\?[^}]+}", "", source0_raw)
    source0_raw = re.sub(r"%{[^}]+}", "", source0_raw)
    return source0_raw

def _match_first(text, pattern):
    """返回正则的第一个匹配分组"""
    match = re.search(pattern, text, flags=re.M)
    return match.group(1) if match else None

def _list_tarballs(source_dir):
    """列出源码目录下的tarball文件"""
    tarballs = []
    try:
        for entry in os.listdir(source_dir):
            if re.search(r"\.tar\.(gz|xz|bz2|zst)$", entry) or entry.endswith(".tgz"):
                tarballs.append(entry)
    except OSError:
        return []
    return tarballs

def _safe_extract_tarball(tarball_path, dest_dir):
    """安全解压tarball到目标目录"""
    try:
        with tarfile.open(tarball_path, "r:*") as tf:
            for member in tf.getmembers():
                member_path = os.path.join(dest_dir, member.name)
                if not os.path.realpath(member_path).startswith(os.path.realpath(dest_dir) + os.sep):
                    raise RuntimeError("tarball包含不安全路径")
            tf.extractall(dest_dir)
    except tarfile.ReadError:
        if _maybe_pull_lfs_tarball(tarball_path):
            with tarfile.open(tarball_path, "r:*") as tf:
                for member in tf.getmembers():
                    member_path = os.path.join(dest_dir, member.name)
                    if not os.path.realpath(member_path).startswith(os.path.realpath(dest_dir) + os.sep):
                        raise RuntimeError("tarball包含不安全路径")
                tf.extractall(dest_dir)
            return
        raise

def _maybe_pull_lfs_tarball(tarball_path):
    """如果tarball是LFS指针文件，则尝试在仓库内拉取并checkout"""
    if not _is_lfs_pointer_file(tarball_path):
        return False

    repo_dir = os.path.dirname(tarball_path)
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        repo_dir = result.stdout.strip() or repo_dir
    except (OSError, subprocess.CalledProcessError):
        logger.warning("ensure_patch_file: tarball为LFS指针，但未检测到git仓库: %s", repo_dir)
        return False

    logger.info("ensure_patch_file: tarball为LFS指针，尝试拉取LFS对象: %s", tarball_path)
    try:
        subprocess.run(
            ["git", "-C", repo_dir, "lfs", "fetch"],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", repo_dir, "lfs", "checkout"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("ensure_patch_file: LFS拉取/checkout失败: %s, err=%s", repo_dir, exc)
        return False

    return not _is_lfs_pointer_file(tarball_path)

def _is_lfs_pointer_file(path):
    """判断文件是否为Git LFS指针"""
    try:
        with open(path, "rb") as f:
            head = f.read(200)
    except OSError:
        return False
    return b"version https://git-lfs.github.com/spec/v1" in head

def _detect_source_root(extract_dir):
    """识别解压后的源码根目录"""
    try:
        entries = [e for e in os.listdir(extract_dir) if not e.startswith(".")]
    except OSError:
        return extract_dir
    if len(entries) == 1:
        only_entry = os.path.join(extract_dir, entries[0])
        if os.path.isdir(only_entry):
            return only_entry
    return extract_dir
