# File Integrity Check MCP Server

## 功能描述
提供系统文件完整性检查功能，基于AIDE和Tripwire实现：
- 初始化文件完整性数据库
- 执行文件完整性检查
- 查看检查报告
- 更新数据库

## 依赖
- aide
- tripwire
- python3
- uv
- python3-mcp

## 使用方法
1. 确保已安装所有依赖
2. 初始化数据库: `init_database`
3. 运行检查: `run_check`
4. 查看报告: `view_report`
5. 更新数据库: `update_database`

## 配置
配置文件位于`mcp_config.json`，可配置以下功能权限：
- init_database
- run_check
- view_report
- update_database