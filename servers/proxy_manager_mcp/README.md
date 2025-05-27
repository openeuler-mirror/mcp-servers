# Proxy Manager MCP Server

## 功能描述
提供代理设置管理功能，包括：
- 配置HTTP/HTTPS代理
- 管理squid代理服务
- 查看代理状态
- 重启代理服务

## 依赖要求
- 系统依赖: squid
- Python依赖: 参见src/requirements.txt

## 使用说明
1. 确保已安装squid服务
2. 通过MCP协议调用以下功能：
   - `set_proxy`: 设置代理配置
   - `get_proxy_status`: 获取代理状态
   - `restart_proxy`: 重启代理服务
   - `list_proxy_settings`: 列出当前代理设置

## 配置说明
编辑`mcp_config.json`可配置:
- 默认代理端口
- 允许的客户端IP
- 日志级别