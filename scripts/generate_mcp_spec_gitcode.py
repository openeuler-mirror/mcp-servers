#!/usr/bin/env python3
"""
用途:
  扫描 MCP 服务器目录，为每个子目录生成 RPM spec 文件，并在需要时生成
  mcp-rpm.yaml；同时打包源码为 tar.gz 并清理目录，只保留 tar.gz 与 .spec。

使用方法:
  1) 配置可选的 GitCode Token（用于补全仓库描述、许可证、话题等信息）:
     export GITCODE_TOKEN=xxxx
  2) 执行当前代码

注意事项:
  - 该脚本会删除每个服务器目录中的 .git/.venv/.env 等文件，并在最后清理
    目录，仅保留生成的 .spec 与 .tar.gz；请先备份或在副本目录上运行。
  - 处理目录由 run() 内的 servers_dir 变量指定。
"""
import argparse
import os
import glob
import yaml
from datetime import datetime
import subprocess
import requests
from typing import Dict, Optional
from dotenv import load_dotenv
import logging
from string import Template
import tarfile
import shutil
from pathlib import Path


SPEC_TEMPLATE = Template(r"""Name:           $pkg_name
Version:        $version
Release:        1
Summary:        $summary
License:        $license
URL:            $url
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       python3
Requires:       uv
Requires:       python3-mcp
$extra_requires

%description
$description

%prep
%setup -q -n %{name}-%{version}

%build

%install
mkdir -p %{buildroot}/opt/mcp-servers/servers/$server_name
mkdir -p %{buildroot}/opt/mcp-servers/servers/$server_name/src
cp -r src/* %{buildroot}/opt/mcp-servers/servers/$server_name/src/ || :
cp README.md %{buildroot}/opt/mcp-servers/servers/$server_name/README.md || :
cp mcp_config.json %{buildroot}/opt/mcp-servers/servers/$server_name/ || :
cp pyproject.toml %{buildroot}/opt/mcp-servers/servers/$server_name/ || :   
cp requirements.txt %{buildroot}/opt/mcp-servers/servers/$server_name/ || :                                 
                         
%post
SERVER_DIR="/opt/mcp-servers/servers/$server_name"
VENV_DIR="$${SERVER_DIR}/.venv"
PYPROJECT_FILE="$${SERVER_DIR}/pyproject.toml"
REQUIREMENTS_FILE="$${SERVER_DIR}/requirements.txt"
PYPI_MIRROR="https://mirrors.aliyun.com/pypi/simple/"

CREATE_VENV=0

if [ -f "$${PYPROJECT_FILE}" ]; then
    cd "$${SERVER_DIR}"
    CREATE_VENV=1
    uv venv "$${VENV_DIR}" --python /bin/python3 --system-site-packages || {
        echo "ERROR: 虚拟环境创建失败（pyproject.toml 路径：$${PYPROJECT_FILE}）" >&2
        exit 1
    }
    . "$${VENV_DIR}/bin/activate"
    uv sync --index "$${PYPI_MIRROR}" --frozen || {
        echo "WARNING: UV 依赖同步失败，尝试用 pip 降级安装" >&2
        "$${VENV_DIR}/bin/python" -m pip install . -i "$${PYPI_MIRROR}" || exit 1
    }

elif [ -f "$${REQUIREMENTS_FILE}" ]; then
    cd "$${SERVER_DIR}"
    CREATE_VENV=1
    uv venv "$${VENV_DIR}" --python /bin/python3 --system-site-packages || {
        echo "ERROR: 虚拟环境创建失败（requirements.txt 路径：$${REQUIREMENTS_FILE}）" >&2
        exit 1
    }
    . "$${VENV_DIR}/bin/activate"
    "$${VENV_DIR}/bin/python" -m pip install --upgrade pip -i "$${PYPI_MIRROR}" || exit 1
    "$${VENV_DIR}/bin/python" -m pip install -r "$${REQUIREMENTS_FILE}" -i "$${PYPI_MIRROR}" || {
        echo "ERROR: requirements.txt 依赖安装失败" >&2
        exit 1
    }
fi
if [ "$${CREATE_VENV}" -eq 1 ]; then
    find "$${VENV_DIR}" -type d -exec chmod 755 {} \;
    find "$${VENV_DIR}" -type f ! -path "$${VENV_DIR}/bin/*" -exec chmod 644 {} \;
    find "$${VENV_DIR}/bin" -type f -exec chmod 755 {} \;
    
    chown -R root:root "$${VENV_DIR}"
fi

if [ "$${CREATE_VENV}" -eq 0 ]; then
    echo "INFO: 未检测到 pyproject.toml 或 requirements.txt，跳过虚拟环境创建" >&2
fi

%postun
rm -rf "/opt/mcp-servers/servers/$server_name/.venv"

%files
%defattr(-,root,root,-)
/opt/mcp-servers/servers/$server_name/

%changelog
* $date openEuler MCP Team <mcp@openeuler.org> - $version-1
- Initial package for $pkg_name
""")

def _fmt_requires(config: dict) -> str:
    deps = config.get("dependencies", {}) or {}
    system_deps = deps.get("system", []) or []
    package_deps = deps.get("packages", []) or []
    all_deps = [d for d in (system_deps + package_deps) if d]
    if not all_deps:
        return []
    return all_deps

def process_folder(server_dir, pkg_version, pkg_name=None):
    server_dir = Path(server_dir)
    server_dir = server_dir.resolve()  
    server_name = server_dir.name
    package_name = pkg_name or server_name
    tarball = server_dir / f"{package_name}-{pkg_version}.tar.gz"
    inner_top_dir = f"{package_name}-{pkg_version}"
    
    print("=" * 40)
    print(f"开始处理服务器：{server_name}")
    print("-" * 40)

    print("1. 清理临时文件...")
    for temp_file in ["uv.lock", ".venv", ".env", ".git", ".gitignore", ".gitattributes", "mcp-test-results"]:
        temp_path = server_dir / temp_file
        try:
            if temp_path.is_file():
                temp_path.unlink()  # 删除文件
            elif temp_path.is_dir():
                shutil.rmtree(temp_path)  # 删除目录
        except FileNotFoundError:
            pass  # 无文件则跳过
    print("   ✅ 已清理 uv.lock/.venv/.env（无则忽略）")

    print(f"2. 开始打包（压缩包内顶层目录：{inner_top_dir}）...")
    # 收集要打包的文件（仅当前目录，不递归）
    final_pack_files = []
    for item in server_dir.iterdir():
        # 排除tar包和spec文件
        if item == tarball or item.suffix == ".spec":
            continue
        final_pack_files.append(item)
    
    # 创建压缩包（容错空文件）
    if not final_pack_files:
        print("   ⚠️ 该目录下无可用文件，创建空压缩包...")
        # 创建空tar包
        with tarfile.open(tarball, "w:gz") as tar:
            pass
    else:
        # 写入压缩包，添加顶层目录前缀
        with tarfile.open(tarball, "w:gz") as tar:
            for file_path in final_pack_files:
                # 压缩包内路径：顶层目录/文件名
                arcname = os.path.join(inner_top_dir, file_path.name)
                tar.add(str(file_path), arcname=arcname)
    print(f"   ✅ 压缩包生成完成：{tarball}")

    # 验证压缩包内路径（容错空包）
    print("   📌 压缩包内路径示例：")
    try:
        with tarfile.open(tarball, "r:gz") as tar:
            # 打印前5个文件
            for idx, member in enumerate(tar.getmembers()):
                if idx >= 5:
                    break
                print(f"      {member.name}")
    except:
        print("      (空压缩包)")

    # 第三步：清理冗余文件，仅保留tar包和spec文件
    print("3. 清理冗余文件，仅保留tar包和spec文件...")
    # 收集要保留的文件
    keep_files = [tarball]
    keep_files.extend(server_dir.glob("*.spec"))  # 所有spec文件
    
    # 遍历目录，删除非保留文件
    for item in server_dir.iterdir():
        if item in keep_files:
            continue  # 保留文件跳过
        try:
            if item.is_file():
                item.unlink()
            elif item.is_dir():
                shutil.rmtree(item)
        except:
            pass  # 删不掉就跳过
    
    # 列出保留的文件
    print("   ✅ 清理完成，当前目录仅保留：")
    has_files = False
    for item in server_dir.iterdir():
        has_files = True
        print(f"      {item.name}")
    if not has_files:
        print("      (目录仅保留空tar包)")

def generate_specs(server_dir,process_flag=False):
    server_name = os.path.basename(server_dir)
    logging.info(f"Processing server: {server_name} (dir: {server_dir})")

    yaml_file = os.path.join(server_dir, "mcp-rpm.yaml")
    if not os.path.exists(yaml_file):
        logging.warning(f"mcp-rpm.yaml not found in {server_dir}, use default config")
        config = {}
    else:
        with open(yaml_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

    pkg_name = config.get("name", server_name)
    version = config.get("version", "1.0.0")
    summary = config.get("summary", f"MCP server: {server_name}")
    description = config.get("description", summary)
    license_ = config.get("license", "MIT")
    url = config.get("url", "https://gitcode.com/mcp-servers/%s"%(server_name))

    
    extra_requires_pkgs = [pk for pk in _fmt_requires(config) if pk not in ["python3-devel", "python3-setuptools", "python3", "uv", "python3-mcp"]]
    if extra_requires_pkgs:
        extra_requires = "\n".join([f"Requires:       {d}" for d in extra_requires_pkgs])
    spec_text = SPEC_TEMPLATE.substitute(
        pkg_name=pkg_name,
        version=version,
        summary=summary,
        description=description,
        license=license_,
        url=url,
        server_name=server_name,
        extra_requires=extra_requires,
        date=datetime.now().strftime("%a %b %d %Y"),
    )

    out_path = os.path.join(server_dir, f"{pkg_name}.spec")
    with open(out_path, "w", encoding="utf-8") as outf:
        outf.write(spec_text)

    logging.info(f"Generated spec file: {out_path}")

    if process_flag:
        process_folder(server_dir, pkg_version=version, pkg_name=pkg_name)



def get_github_repo_api_url(server_dir: str) -> str:
    """
    从 Git 仓库目录解析 GitHub API 地址
    :param server_dir: Git 仓库本地目录路径
    :return: GitHub Repo API 地址（如 https://api.github.com/repos/user/repo）
    :raises: subprocess.CalledProcessError (git命令执行失败)、ValueError (URL格式不支持)
    """
    try:
        cmd = ['git', '-C', server_dir, 'remote', 'get-url', 'origin']
        remote_url = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"执行git命令失败: {e.output.strip()}") from e
    
    part: str = ""
    if remote_url.startswith('git@github.com:'):
        part = remote_url[len('git@github.com:'):]
    elif remote_url.startswith('https://github.com/'):
        part = remote_url[len('https://github.com/'):]
    else:
        raise ValueError(f"不支持的 GitHub URL 格式: {remote_url}（仅支持 git@github.com: 或 https://github.com/ 开头）")
    
    if part.endswith('.git'):
        part = part[:-4]
    
    api_url = f'https://api.github.com/repos/{part}'
    return api_url

def get_repo_info(server_dir: str) -> Dict[str, any]:
    """
    获取 GitHub 仓库的详细信息（描述、地址、许可证、星数、话题等）
    :param server_dir: Git 仓库本地目录路径
    :return: 仓库信息字典
    :raises: RuntimeError (API 请求失败)
    """
    api_url = get_github_repo_api_url(server_dir)
    
    token: Optional[str] = os.getenv('GITCODE_TOKEN')
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"  # 指定 API 版本（避免兼容性问题）
    }
    if token:
        headers['Authorization'] = f'token {token}'
    
    try:
        resp = requests.get(api_url, headers=headers, timeout=15)
        resp.raise_for_status()  # 触发 HTTP 错误（4xx/5xx）
        data = resp.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"获取仓库基础信息失败: {str(e)}") from e
    
    topics = []
    topics_api_url = f"{api_url}/topics"
    try:
        resp_topics = requests.get(topics_api_url, headers=headers, timeout=15)
        if resp_topics.status_code == 200:
            topics = resp_topics.json().get('names', [])
        else:
            print(f"警告：获取话题失败（状态码 {resp_topics.status_code}），跳过")
    except requests.exceptions.RequestException as e:
        print(f"警告：获取话题时网络异常: {str(e)}，跳过")
    
    info = {
        'description': data.get('description', 'No description provided'),
        'html_url': data.get('html_url', ''),
        'license': (data.get('license') or {}).get('name', 'MIT'),  # 无许可证时默认 MIT
        'stargazers_count': data.get('stargazers_count', 0),
        'topics': topics,
    }
    return info

def create_mcp_yaml(server_dir):
    dir_name = os.path.basename(os.path.abspath(server_dir))
    mcp_yaml = {
        'name': dir_name,
        'summary': f'MCP server for {dir_name}',
        'version': '1.0.0',
        'release': '1',
        'dependencies': {
            'system': ['python3', 'uv', 'python3-mcp', 'jq'],
            'packages': [],
        },
        'files': {
            'required': ['mcp_config.json'],
            'optional': [],
        },
        'install_scripts': {
            'pre': [],
            'post': [],
            'preun': [],
            'postun': [],
        }
    }
    gitdir = os.path.join(server_dir, '.git')
    if os.path.isdir(gitdir):
        repo_info = get_repo_info(server_dir)
        mcp_yaml['description'] = f"{repo_info['description']}\nGitHub: {repo_info['html_url']}"
        mcp_yaml['license'] = repo_info.get('license', 'MIT')
    else:
        mcp_yaml['description'] = f"MCP tools for {dir_name}"
        mcp_yaml['license'] = 'MIT'
    with open(os.path.join(server_dir, 'mcp-rpm.yaml'), 'w') as f:
        yaml.safe_dump(mcp_yaml, f, sort_keys=False, allow_unicode=True)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Generate MCP RPM spec files and tarballs"
    )
    parser.add_argument(
        "--servers-dir",
        default=None,
        help="Directory containing MCP server subdirectories.",
    )
    parser.add_argument(
        "--server-dir",
        default=None,
        help="Single MCP server directory to process.",
    )
    parser.add_argument(
        "--work-dir",
        required=True,
        help="Working directory to copy servers into before processing.",
    )
    return parser


def run(servers_dir: str | None, server_dir: str | None, work_dir: str):
    load_dotenv()
    
    if bool(servers_dir) == bool(server_dir):
        raise ValueError("Provide exactly one of --servers-dir or --server-dir")
    source_dirs = []
    if servers_dir:
        if not os.path.exists(servers_dir):
            raise FileNotFoundError(f"Target directory not found at: {servers_dir}")
        if os.path.abspath(servers_dir) == os.path.abspath(work_dir):
            raise ValueError("work-dir must be different from servers-dir")
        source_dirs = [
            d for d in glob.glob(os.path.join(servers_dir, "*")) 
            if os.path.isdir(d)
        ]
        if not source_dirs:
            raise FileNotFoundError(f"No subdirectories found in {servers_dir}")
        logging.info(f"Found {len(source_dirs)} subdirectories to process")
    else:
        if not os.path.exists(server_dir):
            raise FileNotFoundError(f"Target directory not found at: {server_dir}")
        if os.path.abspath(server_dir) == os.path.abspath(work_dir):
            raise ValueError("work-dir must be different from server-dir")
        source_dirs = [server_dir]
        logging.info("Processing single server dir: %s", server_dir)

    os.makedirs(work_dir, exist_ok=True)

    server_subdirs = []
    for src_dir in source_dirs:
        dst_dir = os.path.join(work_dir, os.path.basename(src_dir))
        if os.path.exists(dst_dir):
            raise FileExistsError(f"work-dir already has: {dst_dir}")
        shutil.copytree(src_dir, dst_dir)
        server_subdirs.append(dst_dir)

    for server_dir in server_subdirs:
        if not os.path.exists(os.path.join(server_dir,"mcp-rpm.yaml")):
            create_mcp_yaml(server_dir)
        generate_specs(server_dir, process_flag=True)

if __name__ == "__main__":
    try:
        parser = build_parser()
        args = parser.parse_args()
        run(args.servers_dir, args.server_dir, args.work_dir)
    except Exception as e:
        logging.error(f"Script failed: {str(e)}", exc_info=True)
        exit(1)
