#!/usr/bin/env python3
import yaml
import os
import glob

def generate_spec_file():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    servers_dir = os.path.join(script_dir, "..", "servers")
    
    if not os.path.exists(servers_dir):
        raise FileNotFoundError(f"Servers directory not found at: {servers_dir}")
    
    spec_template = """Name:           mcp-servers
Version:        1.0.0
Release:        1
Summary:        openEuler MCP Servers collection
License:        MIT
URL:            https://gitee.com/openeuler/mcp-servers
Source0:        mcp-servers-%{{version}}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       python3
Requires:       uv
Requires:       python3-mcp

{package_definitions}

%description
Collection of openEuler MCP Servers providing various capabilities.

{package_descriptions}

%prep
%autosetup -n %{{name}}

%build

%install
mkdir -p %{{buildroot}}/opt/mcp-servers/servers

for server in {server_list}; do
    mkdir -p %{{buildroot}}/opt/mcp-servers/servers/$server/src
    cp -r servers/$server/src/* %{{buildroot}}/opt/mcp-servers/servers/$server/src/ || :
    cp servers/$server/mcp_config.json %{{buildroot}}/opt/mcp-servers/servers/$server/ || :
    cp servers/$server/src/requirements.txt %{{buildroot}}/opt/mcp-servers/servers/$server/src/ || :
done

%post
# 主包%post只处理公共目录权限设置
find /opt/mcp-servers -type d -exec chmod 755 {{}} \;

{package_posts}

%files
/opt/mcp-servers/servers/
%defattr(-,root,root,-)

{package_files}

%changelog
* {date} openEuler MCP Team <mcp@openeuler.org> - 1.0.0-1
- Initial package with all MCP servers
"""

    server_dirs = glob.glob(os.path.join(servers_dir, "*", "mcp-rpm.yaml"))
    if not server_dirs:
        raise FileNotFoundError(f"No mcp-rpm.yaml files found in {servers_dir} subdirectories")
    
    package_defs = []
    package_descs = []
    package_files = []
    package_posts = []
    server_names = []

    for yaml_file in server_dirs:
        with open(yaml_file, 'r') as f:
            config = yaml.safe_load(f)
            server_name = os.path.basename(os.path.dirname(yaml_file))
            server_names.append(server_name)
            
            pkg_def = [
                f"%package {config['name']}",
                f"Summary:        {config['summary']}",
                f"Requires:       %{{name}} = %{{version}}-%{{release}}"
            ]
            deps = config.get('dependencies', {})
            system_deps = deps.get('system', [])
            package_deps = deps.get('packages', [])
            pkg_def.extend(
                f"Requires:       {dep}"
                for dep in system_deps + package_deps
                if dep
            )
            
            # 简化的%post脚本
            pkg_post = [
                f"%post {config['name']}",
                f"# 为{config['name']}创建虚拟环境",
                f"uv venv /opt/mcp-servers/servers/{server_name}/.venv --python /bin/python3 --system-site-packages",
                f"chmod -R 755 /opt/mcp-servers/servers/{server_name}/.venv",
                f"",
                f"if [ -f /opt/mcp-servers/servers/{server_name}/src/requirements.txt ]; then",
                f"    /opt/mcp-servers/servers/{server_name}/.venv/bin/python -m pip install \\",
                f"        -r /opt/mcp-servers/servers/{server_name}/src/requirements.txt \\",
                f"        -i https://mirrors.huaweicloud.com/repository/pypi/simple",
                f"    ",
                f"    chmod -R 755 /opt/mcp-servers/servers/{server_name}/.venv",
                f"    find /opt/mcp-servers/servers/{server_name}/.venv -type d -exec chmod 755 {{}} \\;",
                f"    find /opt/mcp-servers/servers/{server_name}/.venv -type f -exec chmod 644 {{}} \\;",
                f"fi",
                f"",
                f"%postun {config['name']}",
                f"# 卸载时清理虚拟环境",
                f"rm -rf \"/opt/mcp-servers/servers/{server_name}/.venv\""
            ]
            
            package_defs.append("\n".join(pkg_def))
            package_posts.append("\n".join(pkg_post))
            
            package_descs.append(f"%description {config['name']}\n{config['description']}")
            
            pkg_files = f"%files {config['name']}\n"
            pkg_files += f"/opt/mcp-servers/servers/{server_name}/*\n"
            pkg_files += "%defattr(-,root,root,-)\n"
            package_files.append(pkg_files)

    from datetime import datetime
    template_vars = {
        "package_definitions": "\n".join(package_defs),
        "package_descriptions": "\n".join(package_descs),
        "package_files": "\n".join(package_files),
        "package_posts": "\n".join(package_posts),
        "server_list": " ".join(server_names),
        "date": datetime.now().strftime("%a %b %d %Y")
    }
    spec_content = spec_template.format(**template_vars)

    with open("mcp-servers.spec", "w") as f:
        f.write(spec_content)

if __name__ == "__main__":
    generate_spec_file()

