# VPN Manager MCP Server

## 功能描述
提供VPN连接管理功能，支持OpenVPN和StrongSwan VPN的管理操作。

## 主要功能
- 列出可用VPN配置
- 启动/停止VPN连接
- 查看VPN连接状态
- 管理VPN证书

## 系统依赖
- openvpn
- strongswan
- python3
- uv

## Python依赖
- pydantic>=1.10.0
- mcp>=0.1.0

## 使用示例
```bash
# 列出可用VPN配置
mcp vpn_manager_mcp list_vpns

# 启动VPN连接
mcp vpn_manager_mcp start_vpn --config myvpn.ovpn

# 查看VPN状态
mcp vpn_manager_mcp get_vpn_status

# 添加证书
mcp vpn_manager_mcp add_certificate --cert_path /tmp/ca.crt --cert_type ca
```

## 注意事项
1. 需要root权限执行VPN管理操作
2. VPN配置文件应放在/etc/openvpn/client/目录下
3. StrongSwan配置文件在/etc/ipsec.conf和/etc/ipsec.d/目录