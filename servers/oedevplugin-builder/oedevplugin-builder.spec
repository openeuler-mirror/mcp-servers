Name:           oedevplugin-builder
Version:        1.0.0
Release:        1
Summary:        MCP server for building oeDevPlugin RPM packages

License:        MIT
URL:            https://gitee.com/openeuler/mcp-servers
BuildRequires:  python3-devel

Source0:        src/server.py
Source1:        mcp_config.json
Source2:        src/requirements.txt
BuildRequires:  python3-setuptools
Requires:       python3
Requires:       uv
Requires:       python3-mcp

%description
MCP server that provides tools for building oeDevPlugin RPM packages.

%build
# Nothing to build for Python script

%install
mkdir -p %{buildroot}/opt/mcp-servers/servers/oedevplugin-builder/src
mkdir -p %{buildroot}/opt/mcp-servers/servers/oedevplugin-builder

install -m 755 %{SOURCE0} %{buildroot}/opt/mcp-servers/servers/oedevplugin-builder/src/server.py
install -m 644 %{SOURCE1} %{buildroot}/opt/mcp-servers/servers/oedevplugin-builder/mcp_config.json
install -m 644 %{SOURCE2} %{buildroot}/opt/mcp-servers/servers/oedevplugin-builder/src/requirements.txt

%files
/opt/mcp-servers/servers/oedevplugin-builder/src/server.py
/opt/mcp-servers/servers/oedevplugin-builder/mcp_config.json
/opt/mcp-servers/servers/oedevplugin-builder/src/requirements.txt

%post
# 创建venv并安装依赖
uv venv /opt/mcp-servers/servers/oedevplugin-builder/.venv --python /bin/python3
source /opt/mcp-servers/servers/oedevplugin-builder/.venv/bin/activate

# skip install dependencies
# uv pip install -r /opt/mcp-servers/servers/oedevplugin-builder/src/requirements.txt

# 为root用户合并配置
mkdir -p /root/.roo
if [ -f /root/.roo/mcp.json ]; then
    jq -s '.[0] * .[1]' /root/.roo/mcp.json /opt/mcp-servers/servers/oedevplugin-builder/mcp_config.json > /root/.roo/mcp.json.tmp && mv /root/.roo/mcp.json.tmp /root/.roo/mcp.json
else
    cp /opt/mcp-servers/servers/oedevplugin-builder/mcp_config.json /root/.roo/mcp.json
fi

# 为所有普通用户合并配置
for user_home in /home/*; do
    if [ -d "$user_home" ]; then
        mkdir -p "$user_home/.roo"
        if [ -f "$user_home/.roo/mcp.json" ]; then
            jq -s '.[0] * .[1]' "$user_home/.roo/mcp.json" /opt/mcp-servers/servers/oedevplugin-builder/mcp_config.json > "$user_home/.roo/mcp.json.tmp" && mv "$user_home/.roo/mcp.json.tmp" "$user_home/.roo/mcp.json"
        else
            cp /opt/mcp-servers/servers/oedevplugin-builder/mcp_config.json "$user_home/.roo/mcp.json"
        fi
    fi
done

%changelog
* Wed Apr 16 2025 Your Name <your.email@example.com> - 1.0.0-1
- Initial package
