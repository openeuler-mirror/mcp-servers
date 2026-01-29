#!/usr/bin/env bash
set -euo pipefail

# 获取系统架构（动态选择镜像版本）
ARCH="$(uname -m)"
if [ "${ARCH}" == "x86_64" ]; then
    ARCH="x86_64"
elif [ "${ARCH}" == "aarch64" ] || [ "${ARCH}" == "arm64" ]; then
    ARCH="aarch64"
else
    die "不支持的架构: ${ARCH}"
fi

# =============================================================================
# 该脚本会启动 3 个容器服务：
# 1) linux-cve-announce-mirror：public-inbox 镜像，提供 CVE 公告镜像服务（8080）
# 2) cve-app-server：CVE 处理服务（A2A 客户端使用，9991）
# 3) gitee-webhook：Gitee WebHook 转发服务（6001 -> 9991）
# =============================================================================

# ===== 1) 可按需修改的配置（集中在此处，去除运行时参数）=====
# 必填项（请替换为真实值）：
# - API_KEY / LLM_PROVIDER / MODEL_NAME / BASE_URL
# - GITEE_TOKEN / GITEE_ACCESS_TOKEN / GITCODE_ACCESS_TOKEN / GITCODE_WEBHOOK_TOKEN
# - TARGET_REPO_URL / FORK_REPO_URL / DEFAULT_CLONE_PATH
# Gitee WebHook 密钥（示例：YOUR_GITEE_WEBHOOK_TOKEN_123）
GITEE_WEBHOOK_TOKEN="YOUR_GITEE_WEBHOOK_TOKEN"
# Gitcode WebHook 密钥（示例：YOUR_GITCODE_WEBHOOK_TOKEN_123）
GITCODE_WEBHOOK_TOKEN="YOUR_GITCODE_WEBHOOK_TOKEN"
# Gitee Access Token（示例：gitee_pat_xxxxxxxxxxxxx）
GITEE_ACCESS_TOKEN="YOUR_GITEE_ACCESS_TOKEN"
GITCODE_ACCESS_TOKEN="YOUR_GITCODE_ACCESS_TOKEN"
# Gitee Token（示例：gitee_token_xxxxxxxxxxxxx）
GITEE_TOKEN="YOUR_GITEE_TOKEN"
# 目标仓库地址（示例：https://atomgit.com/openeuler/kernel）
TARGET_REPO_URL="https://atomgit.com/openeuler/kernel"
# Fork 仓库地址（示例：https://atomgit.com/devstation-robot/kernel）
FORK_REPO_URL="https://atomgit.com/devstation-robot/kernel"

# LLM / 应用相关配置
# LLM 提供商标识（示例：minimax）
LLM_PROVIDER="minimax"
# 模型名称（示例：MiniMax-M2.1）
MODEL_NAME="MiniMax-M2.1"
# API 密钥（示例：sk-xxxxxxxxxxxxxxxx）
API_KEY="YOUR_LLM_API_KEY"
# LLM API 基础地址（示例：https://api.minimaxi.com/v1）
BASE_URL="https://api.minimaxi.com/v1"
# 是否仅使用本地缓存：Linux 仓库拉取耗时且依赖稳定网络，
# 实际上无需频繁更新，离线/受限环境可直接使用本地镜像。
# 示例：1 表示仅用本地缓存，0 表示允许联网更新。
LINUX_REPO_USE_CACHE_ONLY="1"

# 兼容旧配置项（仍保留但不接受运行时参数）
# 旧版模型类型（示例：MiniMax-M2.1）
DEFAULT_MODEL_TYPE="MiniMax-M2.1"
# 旧版 MCP 配置文件名（示例：mcp_settings.json）
DEFAULT_LOCAL_CONFIG="mcp_settings.json"
# 旧版代码克隆路径（示例：/path/to/Image）
# 也是容器挂载的本地 Linux/kernel 仓库存放目录
DEFAULT_CLONE_PATH="/path/to/Image"
# Linux 主线仓库地址（示例：https://git.kernel.org/.../linux.git）
LINUX_REPO_URL="https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"
# openEuler kernel 仓库地址（默认与目标仓库一致）
KERNEL_REPO_URL="${TARGET_REPO_URL}"
# 旧版目标仓库（示例：https://atomgit.com/openeuler/kernel）
DEFAULT_TARGET_REPO="https://atomgit.com/openeuler/kernel"
# 旧版 Fork 仓库（示例：https://atomgit.com/devstation-robot/kernel）
DEFAULT_FORK_REPO="https://atomgit.com/devstation-robot/kernel"
# 旧版分支列表（示例：OLK-6.6, OLK-5.10, openEuler-1.0-LTS）
DEFAULT_BRANCHES="OLK-6.6, OLK-5.10, openEuler-1.0-LTS"
# 超时时间（秒）（示例：3600）
TIMEOUT="3600"
# ==============================

# public-inbox 镜像名（示例：linux-cve-announce-mirror:latest）
PUBLIC_INBOX_IMAGE="linux-cve-announce-mirror:latest"
# cve-app-server 镜像名（示例：cve-app-server:latest）
APP_IMAGE="cve-app-server:latest"
# gitee-webhook 镜像名（示例：gitee-webhook:latest）
WEBHOOK_IMAGE="gitee-webhook:latest"
# 脚本所在目录（默认自动获取，用作 Dockerfile 构建上下文）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Dockerfile 所在目录路径（与脚本同目录）
ROOT_DIR="${SCRIPT_DIR}"
# MCP 配置文件输出路径（脚本会覆盖写入）
MCP_SETTINGS_JSON="${ROOT_DIR}/cve_service/mcp_settings.json"
# cve_service 环境变量文件输出路径（脚本会覆盖写入）
CVE_SERVICE_ENV="${ROOT_DIR}/cve_service/.env"
# 日志输出路径
APP_WORK_DIR="${ROOT_DIR}/cve_service"
APP_CLIENT_LOG="${ROOT_DIR}/cve_service/app_client.log"
# public-inbox 仓库本地路径（用于同步与打包进镜像）
PUBLIC_INBOX_REPO="${ROOT_DIR}/public-inbox/linux-cve-announce/git/0.git"
# public-inbox 压缩包本地路径（如存在则解压）
PUBLIC_INBOX_TAR="${ROOT_DIR}/public-inbox.tar"
# public-inbox 压缩包下载地址（为空则不下载）
PUBLIC_INBOX_TAR_URL=""
# openEuler.repo 模板文件来源（可选，示例：/path/to/openEuler.repo）
OPENEULER_REPO_SRC=""
# openEuler.repo 输出路径（用于 Dockerfile COPY）
OPENEULER_REPO_FILE="${ROOT_DIR}/openEuler.repo"
# RPM 构建目录（用于准备 ctags/oegitext 等包）
RPMBUILD_DIR="${ROOT_DIR}/rpmbuild"
# RPM 构建输出目录（Dockerfile 会 COPY 该目录）
RPMBUILD_RPMS_DIR="${RPMBUILD_DIR}/RPMS"
# ctags SRPM 下载地址（示例：Fedora SRPM 链接）
CTAGS_SRPM_URL="https://dl.fedoraproject.org/pub/fedora/linux/releases/42/Everything/source/tree/Packages/c/ctags-6.1.0-2.fc42.src.rpm"
# ctags SRPM 本地保存路径
CTAGS_SRPM_FILE="${ROOT_DIR}/_downloads/ctags.src.rpm"
# openEuler 基础镜像 tar 包下载地址（根据架构动态选择）
OPENEULER_BASE_TAR_URL="https://mirrors.aliyun.com/openeuler/openEuler-24.03-LTS-SP1/docker_img/${ARCH}/openEuler-docker.${ARCH}.tar.xz"
# openEuler 基础镜像 tar 包本地保存路径
OPENEULER_BASE_TAR_FILE="${ROOT_DIR}/_downloads/openEuler-docker.${ARCH}.tar.xz"
# Fedora 基础镜像 tar 包下载地址（根据架构动态选择）
FEDORA_BASE_TAR_URL="http://mirror.etf.bg.ac.rs/fedora/releases/41/Container/${ARCH}/images/Fedora-Container-Base-Generic-41-1.4.${ARCH}.oci.tar.xz"
# Fedora 基础镜像 tar 包本地保存路径
FEDORA_BASE_TAR_FILE="${ROOT_DIR}/_downloads/Fedora-Container-Base-Generic-41-1.4.${ARCH}.oci.tar.xz"
# 是否自动导入基础镜像（示例：1 开启，0 关闭）
AUTO_LOAD_BASE_IMAGE="1"

# ===== 2) 工具函数 =====

if [[ "${API_KEY}" == "YOUR_LLM_API_KEY" || -z "${API_KEY}" ]]; then
  echo "ERROR: 未设置 API_KEY。请在脚本顶部配置为真实值。"
  exit 1
fi

log() { echo "==> $*"; }
warn() { echo "WARN: $*"; }
die() { echo "ERROR: $*" >&2; exit 1; }

warn_if_placeholder() {
  local name="$1"
  local value="$2"
  local placeholder="$3"
  if [[ "${value}" == "${placeholder}" || -z "${value}" ]]; then
    warn "配置未替换：${name}=${placeholder}"
  fi
}

print_service_overview() {
  echo
  echo "==> 将启动的容器服务（共 3 个）："
  echo "  1) linux-cve-announce-mirror：public-inbox 镜像，提供 CVE 公告镜像服务（端口 8080）"
  echo "  2) cve-app-server：CVE 处理服务（A2A 客户端使用，端口 9991）"
  echo "  3) gitee-webhook：Gitee WebHook 转发服务（端口 6001 -> 9991）"
  echo
  echo "==> 需要你补充的关键配置（脚本顶部）："
  echo "  - LLM：API_KEY / LLM_PROVIDER / MODEL_NAME / BASE_URL"
  echo "  - Gitee：GITEE_TOKEN / GITEE_ACCESS_TOKEN / GITCODE_ACCESS_TOKEN / GITCODE_WEBHOOK_TOKEN"
  echo "  - 仓库与路径：TARGET_REPO_URL / FORK_REPO_URL / DEFAULT_CLONE_PATH"
  echo
}

ensure_dir() {
  mkdir -p "$1"
}

download_file() {
  local url="$1"
  local dest="$2"

  if command -v curl >/dev/null 2>&1; then
    curl -L -o "${dest}" "${url}"
    return 0
  fi

  if command -v wget >/dev/null 2>&1; then
    wget -O "${dest}" "${url}"
    return 0
  fi

  die "未找到 curl 或 wget，无法下载：${url}"
}

clone_repo_if_missing() {
  local name="$1"
  local url="$2"
  local dir="$3"

  if [ -d "${dir}/.git" ]; then
    log "${name} 仓库已存在，跳过克隆：${dir}"
    return 0
  fi

  if [ -e "${dir}" ]; then
    warn "${name} 路径已存在但不是 Git 仓库，跳过克隆：${dir}"
    return 0
  fi

  log "克隆 ${name} 仓库：${url}"
  git clone "${url}" "${dir}"
}

prepare_openEuler_repo() {
  if [ -f "${OPENEULER_REPO_FILE}" ]; then
    return 0
  fi

  if [ -n "${OPENEULER_REPO_SRC}" ] && [ -f "${OPENEULER_REPO_SRC}" ]; then
    log "复制 openEuler.repo：${OPENEULER_REPO_SRC}"
    cp -f "${OPENEULER_REPO_SRC}" "${OPENEULER_REPO_FILE}"
    return 0
  fi

  log "生成默认 openEuler.repo：${OPENEULER_REPO_FILE}"
  cat > "${OPENEULER_REPO_FILE}" <<'EOF'
#generic-repos is licensed under the Mulan PSL v2.
#You can use this software according to the terms and conditions of the Mulan PSL v2.
#You may obtain a copy of Mulan PSL v2 at:
#    http://license.coscl.org.cn/MulanPSL2
#THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR
#IMPLIED, INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY OR FIT FOR A PARTICULAR
#PURPOSE.
#See the Mulan PSL v2 for more details.

[OS]
name=OS
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/OS/$basearch/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/OS/$basearch/RPM-GPG-KEY-openEuler

[everything]
name=everything
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/everything/$basearch/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/everything/$basearch/RPM-GPG-KEY-openEuler

[EPOL]
name=EPOL
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/EPOL/main/$basearch/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/OS/$basearch/RPM-GPG-KEY-openEuler

[debuginfo]
name=debuginfo
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/debuginfo/$basearch/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/debuginfo/$basearch/RPM-GPG-KEY-openEuler

[source]
name=source
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/source/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/source/RPM-GPG-KEY-openEuler

[update]
name=update
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/update/$basearch/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/OS/$basearch/RPM-GPG-KEY-openEuler

[update-source]
name=update-source
baseurl=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/update/source/
enabled=1
gpgcheck=1
gpgkey=https://mirrors.huaweicloud.com/openeuler/openEuler-24.03-LTS-SP2/source/RPM-GPG-KEY-openEuler
EOF
}

prepare_public_inbox() {
  if [ -d "${PUBLIC_INBOX_REPO}" ]; then
    log "同步 public-inbox 仓库..."
    git -C "${PUBLIC_INBOX_REPO}" fetch --all --prune || true
    return 0
  fi

  if [ -f "${PUBLIC_INBOX_TAR}" ]; then
    log "解压 public-inbox 压缩包：${PUBLIC_INBOX_TAR}"
    tar -xf "${PUBLIC_INBOX_TAR}" -C "${ROOT_DIR}"
  elif [ -n "${PUBLIC_INBOX_TAR_URL}" ]; then
    log "下载 public-inbox 压缩包：${PUBLIC_INBOX_TAR_URL}"
    ensure_dir "$(dirname "${PUBLIC_INBOX_TAR}")"
    download_file "${PUBLIC_INBOX_TAR_URL}" "${PUBLIC_INBOX_TAR}"
    tar -xf "${PUBLIC_INBOX_TAR}" -C "${ROOT_DIR}"
  else
    warn "public-inbox 仓库与压缩包均不存在，稍后将跳过 public-inbox 镜像构建。"
    return 1
  fi

  if [ -d "${PUBLIC_INBOX_REPO}" ]; then
    log "同步 public-inbox 仓库..."
    git -C "${PUBLIC_INBOX_REPO}" fetch --all --prune || true
    return 0
  fi

  warn "public-inbox 解压后仍未找到仓库路径：${PUBLIC_INBOX_REPO}"
  return 1
}

prepare_rpms() {
  if [ "${AUTO_PREPARE_RPMS}" != "1" ]; then
    warn "已关闭 RPM 自动准备，跳过。"
    return 0
  fi

  if ls "${RPMBUILD_RPMS_DIR}"/*/*.rpm >/dev/null 2>&1; then
    log "RPM 包已存在，跳过构建：${RPMBUILD_RPMS_DIR}"
    return 0
  fi

  if ! command -v rpmbuild >/dev/null 2>&1; then
    die "未安装 rpmbuild，请先安装或准备好 ${RPMBUILD_RPMS_DIR} 目录。"
  fi

  log "准备 RPM 构建目录：${RPMBUILD_DIR}"
  ensure_dir "${RPMBUILD_DIR}/"{BUILD,RPMS,SOURCES,SPECS,SRPMS}

  if [ -n "${CTAGS_SRPM_URL}" ] && [ ! -f "${CTAGS_SRPM_FILE}" ]; then
    log "下载 ctags SRPM：${CTAGS_SRPM_URL}"
    ensure_dir "$(dirname "${CTAGS_SRPM_FILE}")"
    download_file "${CTAGS_SRPM_URL}" "${CTAGS_SRPM_FILE}"
  fi

  if [ -f "${CTAGS_SRPM_FILE}" ]; then
    log "构建 ctags RPM（SRPM）：${CTAGS_SRPM_FILE}"
    rpmbuild --rebuild "${CTAGS_SRPM_FILE}" --define "_topdir ${RPMBUILD_DIR}"
  elif [ -f "${RPMBUILD_DIR}/SOURCES/ctags.spec" ]; then
    log "构建 ctags RPM（spec）：${RPMBUILD_DIR}/SOURCES/ctags.spec"
    rpmbuild -ba "${RPMBUILD_DIR}/SOURCES/ctags.spec" --define "_topdir ${RPMBUILD_DIR}"
  else
    warn "未找到 ctags SRPM/spec，跳过 ctags 构建。"
  fi

  if [ -f "${RPMBUILD_DIR}/SOURCES/oeGitExt.spec" ]; then
    log "构建 oegitext RPM：${RPMBUILD_DIR}/SOURCES/oeGitExt.spec"
    rpmbuild -ba "${RPMBUILD_DIR}/SOURCES/oeGitExt.spec" --define "_topdir ${RPMBUILD_DIR}"
  fi
}

prepare_base_image() {
  if [ "${AUTO_LOAD_BASE_IMAGE}" != "1" ]; then
    warn "已关闭基础镜像自动导入，跳过。"
    return 0
  fi

  if [ -z "${OPENEULER_BASE_TAR_URL}" ] && [ ! -f "${OPENEULER_BASE_TAR_FILE}" ]; then
    warn "未提供基础镜像下载地址且本地文件不存在，跳过导入。"
    return 0
  fi

  if [ ! -f "${OPENEULER_BASE_TAR_FILE}" ] && [ -n "${OPENEULER_BASE_TAR_URL}" ]; then
    log "下载 openEuler 基础镜像：${OPENEULER_BASE_TAR_URL}"
    ensure_dir "$(dirname "${OPENEULER_BASE_TAR_FILE}")"
    download_file "${OPENEULER_BASE_TAR_URL}" "${OPENEULER_BASE_TAR_FILE}"
  fi

  if [ -f "${OPENEULER_BASE_TAR_FILE}" ]; then
    log "导入 openEuler 基础镜像：${OPENEULER_BASE_TAR_FILE}"
    if command -v podman >/dev/null 2>&1; then
      podman load -i "${OPENEULER_BASE_TAR_FILE}"
    elif command -v docker >/dev/null 2>&1; then
      docker load -i "${OPENEULER_BASE_TAR_FILE}"
    else
      die "未找到 podman 或 docker，无法导入基础镜像。"
    fi
  fi
}

prepare_fedora_base_image() {
  if [ "${AUTO_LOAD_BASE_IMAGE}" != "1" ]; then
    warn "已关闭基础镜像自动导入，跳过 Fedora。"
    return 0
  fi

  if [ -z "${FEDORA_BASE_TAR_URL}" ] && [ ! -f "${FEDORA_BASE_TAR_FILE}" ]; then
    warn "未提供 Fedora 基础镜像下载地址且本地文件不存在，跳过导入。"
    return 0
  fi

  if [ ! -f "${FEDORA_BASE_TAR_FILE}" ] && [ -n "${FEDORA_BASE_TAR_URL}" ]; then
    log "下载 Fedora 基础镜像：${FEDORA_BASE_TAR_URL}"
    ensure_dir "$(dirname "${FEDORA_BASE_TAR_FILE}")"
    download_file "${FEDORA_BASE_TAR_URL}" "${FEDORA_BASE_TAR_FILE}"
  fi

  if [ -f "${FEDORA_BASE_TAR_FILE}" ]; then
    log "导入 Fedora 基础镜像：${FEDORA_BASE_TAR_FILE}"
    if command -v podman >/dev/null 2>&1; then
      podman load -i "${FEDORA_BASE_TAR_FILE}"
    elif command -v docker >/dev/null 2>&1; then
      docker load -i "${FEDORA_BASE_TAR_FILE}"
    else
      die "未找到 podman 或 docker，无法导入 Fedora 基础镜像。"
    fi
  fi
}

# ===== 3) 依赖准备 =====
warn_if_placeholder "GITEE_TOKEN" "${GITEE_TOKEN}" "YOUR_GITEE_TOKEN"	 
warn_if_placeholder "GITEE_ACCESS_TOKEN" "${GITEE_ACCESS_TOKEN}" "YOUR_GITEE_ACCESS_TOKEN"	 
warn_if_placeholder "GITCODE_ACCESS_TOKEN" "${GITCODE_ACCESS_TOKEN}" "YOUR_GITCODE_ACCESS_TOKEN"
warn_if_placeholder "GITCODE_WEBHOOK_TOKEN" "${GITCODE_WEBHOOK_TOKEN}" "YOUR_GITCODE_WEBHOOK_TOKEN"	 
warn_if_placeholder "TARGET_REPO_URL" "${TARGET_REPO_URL}" "https://atomgit.com/openeuler/kernel"	 
warn_if_placeholder "FORK_REPO_URL" "${FORK_REPO_URL}" "https://atomgit.com/devstation-robot/kernel"	 
warn_if_placeholder "DEFAULT_CLONE_PATH" "${DEFAULT_CLONE_PATH}" "/path/to/Image"
print_service_overview

log "准备 Linux/kernel 仓库..."
ensure_dir "${DEFAULT_CLONE_PATH}"
clone_repo_if_missing "linux" "${LINUX_REPO_URL}" "${DEFAULT_CLONE_PATH}/linux"
clone_repo_if_missing "kernel" "${KERNEL_REPO_URL}" "${DEFAULT_CLONE_PATH}/kernel"

# ===== 4) Dockerfile 依赖文件 =====
log "准备 Dockerfile 依赖文件..."
prepare_openEuler_repo
prepare_rpms
prepare_public_inbox
prepare_base_image
prepare_fedora_base_image

# ===== 5) 生成运行时配置 =====
echo "==> 写入 MCP 配置..."
cat > "${MCP_SETTINGS_JSON}" <<EOF
{
  "mcpServers": {
    "cvekit_mcp": {
      "command": "python3",
      "env": {
        "LANG": "en_CN.UTF-8",
        "PYTHONPATH": "${ROOT_DIR}",
        "MODEL_NAME": "${MODEL_NAME}",
        "API_KEY": "${API_KEY}",
        "LLM_PROVIDER": "${LLM_PROVIDER}",
        "LINUX_REPO_USE_CACHE_ONLY": "${LINUX_REPO_USE_CACHE_ONLY}"
      },
      "args": [
        "${ROOT_DIR}/server.py",
        "--gitee-token",
        "${GITEE_TOKEN}",
        "--llm-provider",
        "${LLM_PROVIDER}",
        "--api-key",
        "${API_KEY}"
      ],
      "disabled": false,
      "alwaysAllow": [],
      "description": "Gitee代码仓CVE补丁处理服务",
      "timeout": "${TIMEOUT}"
    }
  }
}
EOF

echo "==> 写入 cve_service 环境文件..."
cat > "${CVE_SERVICE_ENV}" <<EOF
LLM_PROVIDER=${LLM_PROVIDER}
MODEL_NAME=${MODEL_NAME}
API_KEY=${API_KEY}
BASE_URL=${BASE_URL}
LINUX_REPO_USE_CACHE_ONLY=${LINUX_REPO_USE_CACHE_ONLY}
GITEE_TOKEN=${GITEE_TOKEN}
GITEE_ACCESS_TOKEN=${GITEE_ACCESS_TOKEN}
GITCODE_ACCESS_TOKEN=${GITCODE_ACCESS_TOKEN}
GITCODE_WEBHOOK_TOKEN=${GITCODE_WEBHOOK_TOKEN}
DEFAULT_MODEL_TYPE=${DEFAULT_MODEL_TYPE}
DEFAULT_LOCAL_CONFIG=${DEFAULT_LOCAL_CONFIG}
DEFAULT_CLONE_PATH=${DEFAULT_CLONE_PATH}
DEFAULT_TARGET_REPO=${DEFAULT_TARGET_REPO}
DEFAULT_FORK_REPO=${DEFAULT_FORK_REPO}
DEFAULT_BRANCHES=${DEFAULT_BRANCHES}
TIMEOUT=${TIMEOUT}
EOF

# ===== 6) 构建镜像 =====
if [ -d "${PUBLIC_INBOX_REPO}" ]; then
  log "构建 linux-cve-announce public-inbox 镜像..."
  podman build --network=host \
    -f "${ROOT_DIR}/Dockerfile.public_inbox" \
    -t "${PUBLIC_INBOX_IMAGE}" \
    "${ROOT_DIR}"
else
  warn "未找到 public-inbox 仓库，跳过 public-inbox 镜像构建。"
fi

log "构建 cve-app-server 镜像..."
podman build --network=host \
  -f "${ROOT_DIR}/Dockerfile.app_server" \
  --build-arg CLONE_PATH="${DEFAULT_CLONE_PATH}" \
  -t "${APP_IMAGE}" \
  "${ROOT_DIR}"

log "构建 gitee-webhook 镜像..."
podman build --network=host \
  -f "${ROOT_DIR}/Dockerfile.webhook" \
  -t "${WEBHOOK_IMAGE}" \
  "${ROOT_DIR}"

# ===== 7) 启停容器 =====
echo "==> 停止并删除旧容器（如存在）..."
for c in linux-cve-announce-mirror cve-app-server gitee-webhook; do
  podman stop "$c" >/dev/null 2>&1 || true
  podman rm   "$c" >/dev/null 2>&1 || true
done

echo "==> 启动 linux-cve-announce public-inbox 容器（提供 8080 端口）..."
podman run -d \
  --name linux-cve-announce-mirror \
  --network host \
  "${PUBLIC_INBOX_IMAGE}"

echo "==> 启动 cve-app-server 容器（提供 9991 端口给 A2A 客户端使用）..."
# 挂载本地 Linux kernel 仓库存放目录（即 DEFAULT_CLONE_PATH），便于离线环境读取/应用补丁
# 该目录同时供目标仓库与 fork 仓库复用，避免重复拉取
podman run -d \
  --name cve-app-server \
  --network host \
  -p 9991:9991 \
  -v "${DEFAULT_CLONE_PATH}:${DEFAULT_CLONE_PATH}:Z" \
  -e TARGET_REPO_URL="${TARGET_REPO_URL}" \
  -e FORK_REPO_URL="${FORK_REPO_URL}" \
  -e GITEE_TOKEN="${GITEE_TOKEN}" \
  -e LLM_PROVIDER="${LLM_PROVIDER}" \
  -e DEFAULT_MODEL_TYPE="${DEFAULT_MODEL_TYPE}" \
  -e MODEL_NAME="${MODEL_NAME}" \
  -e API_KEY="${API_KEY}" \
  -e LINUX_REPO_USE_CACHE_ONLY="${LINUX_REPO_USE_CACHE_ONLY}" \
  -e DEFAULT_LOCAL_CONFIG="${DEFAULT_LOCAL_CONFIG}" \
  -e DEFAULT_CLONE_PATH="${DEFAULT_CLONE_PATH}" \
  -e DEFAULT_TARGET_REPO="${DEFAULT_TARGET_REPO}" \
  -e DEFAULT_FORK_REPO="${DEFAULT_FORK_REPO}" \
  -e DEFAULT_BRANCHES="${DEFAULT_BRANCHES}" \
  -e TIMEOUT="${TIMEOUT}" \
  "${APP_IMAGE}"

echo "==> 启动 gitee-webhook 容器（监听宿主机 6001 端口，调用 http://localhost:9991）..."
podman run -d --name gitee-webhook --network host \
  -e GITCODE_WEBHOOK_TOKEN="${GITCODE_WEBHOOK_TOKEN}" \
  -e GITEE_ACCESS_TOKEN="${GITEE_ACCESS_TOKEN}" \
  -e GITCODE_ACCESS_TOKEN="${GITCODE_ACCESS_TOKEN}" \
  -e APP_CLIENT_LOG="${APP_CLIENT_LOG}" \
  -e APP_WORK_DIR="${APP_WORK_DIR}" \
  "${WEBHOOK_IMAGE}"

echo
echo "当前容器状态："
podman ps --filter name=linux-cve-announce-mirror --filter name=cve-app-server --filter name=gitee-webhook
echo
echo "提示：在 Gitee WebHook 中配置回调 URL 为 http://<宿主机IP>:6001/gitee/webhook"
