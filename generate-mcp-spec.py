#!/usr/bin/env python3
import yaml
import os
import glob

def generate_spec_file():
    spec_template = """Name:           mcp-servers
Version:        1.0.0
Release:        1
Summary:        openEuler MCP Servers collection
License:        MIT
URL:            https://gitee.com/openeuler/mcp-servers
Source0:        mcp-servers-%{{version}}.tar.gz
BuildArch:      noarch

# 公共依赖
BuildRequires:  python3-devel
BuildRequires:  python3-setuptools
Requires:       python3
Requires:       uv
Requires:       python3-mcp
Requires:       jq

{package_definitions}

%description
Collection of openEuler MCP Servers providing various capabilities.

{package_descriptions}

%prep
%autosetup -n %{{name}}

%build
# 不需要构建步骤

%install
mkdir -p %{{buildroot}}/opt/mcp-servers/servers

for server in {server_list}; do
    mkdir -p %{{buildroot}}/opt/mcp-servers/servers/$server/src
    cp -r servers/$server/src/* %{{buildroot}}/opt/mcp-servers/servers/$server/src/ || :
    cp servers/$server/mcp_config.json %{{buildroot}}/opt/mcp-servers/servers/$server/ || :
    cp servers/$server/src/requirements.txt %{{buildroot}}/opt/mcp-servers/servers/$server/src/ || :
done

%post
for server in {server_list}; do
    uv venv /opt/mcp-servers/servers/$server/.venv --python /bin/python3 --system-site-packages
    chmod -R 755 /opt/mcp-servers/servers/$server/.venv
    
    if [ -f /opt/mcp-servers/servers/$server/src/requirements.txt ]; then
        /opt/mcp-servers/servers/$server/.venv/bin/python -m pip install \\\n\
            -r /opt/mcp-servers/servers/$server/src/requirements.txt \\\n\
            -i https://mirrors.huaweicloud.com/repository/pypi/simple
        
        chmod -R 755 /opt/mcp-servers/servers/$server/.venv
        find /opt/mcp-servers/servers/$server/.venv -type d -exec chmod 755 {{}} \;
        find /opt/mcp-servers/servers/$server/.venv -type f -exec chmod 644 {{}} \;
    fi
done

# 合并所有MCP server配置
for server in {server_list}; do
    if [ -f /opt/mcp-servers/servers/$server/mcp_config.json ]; then
        MCP_CONFIG_PATH="/.config/VSCodium/User/globalStorage/rooveterinaryinc.roo-cline/settings/mcp_settings.json"
        
        mkdir -p "/root$(dirname $MCP_CONFIG_PATH)"
        if [ -f "/root$MCP_CONFIG_PATH" ]; then
            jq -s '.[0] * .[1]' "/root$MCP_CONFIG_PATH" \\\n\
                /opt/mcp-servers/servers/$server/mcp_config.json \\\n\
                > "/root$MCP_CONFIG_PATH.tmp" && \\\n\
            mv "/root$MCP_CONFIG_PATH.tmp" "/root$MCP_CONFIG_PATH"
        else
            cp /opt/mcp-servers/servers/$server/mcp_config.json "/root$MCP_CONFIG_PATH"
        fi
        
        for user_home in /home/*; do
            if [ -d "$user_home" ]; then
                username=$(basename "$user_home")
                mkdir -p "$user_home$(dirname $MCP_CONFIG_PATH)"
                if [ -f "$user_home$MCP_CONFIG_PATH" ]; then
                    jq -s '.[0] * .[1]' "$user_home$MCP_CONFIG_PATH" \\\n\
                        /opt/mcp-servers/servers/$server/mcp_config.json \\\n\
                        > "$user_home$MCP_CONFIG_PATH.tmp" && \\\n\
                    mv "$user_home$MCP_CONFIG_PATH.tmp" "$user_home$MCP_CONFIG_PATH"
                else
                    cp /opt/mcp-servers/servers/$server/mcp_config.json "$user_home$MCP_CONFIG_PATH"
                fi
                chown -R "$username:$username" "$user_home$(dirname $MCP_CONFIG_PATH)"
                chmod 755 "$user_home$(dirname $MCP_CONFIG_PATH)"
                chmod 644 "$user_home$MCP_CONFIG_PATH"
            fi
        done
    fi
done

%files
# 主包不包含具体文件，只包含子包

{package_files}

%changelog
* {date} openEuler MCP Team <mcp@openeuler.org> - 1.0.0-1
- Initial package with all MCP servers
"""

    server_dirs = glob.glob("servers/*/mcp-rpm.yaml")
    package_defs = []
    package_descs = []
    package_files = []
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
            pkg_def.extend(
                f"Requires:       {dep}"
                for dep in config['dependencies']['system'] + config['dependencies']['packages']
            )
            package_defs.append("\n".join(pkg_def))
            
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
        "server_list": " ".join(server_names),
        "date": datetime.now().strftime("%a %b %d %Y")
    }
    spec_content = spec_template.format(**template_vars)

    with open("mcp-servers.spec", "w") as f:
        f.write(spec_content)

if __name__ == "__main__":
    generate_spec_file()
