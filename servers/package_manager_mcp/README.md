# 软件包管理MCP服务器

## 功能描述
提供软件包管理功能，包括：
- 查询软件包信息 (`dnf list/search`)
- 安装软件包 (`dnf install`)
- 卸载软件包 (`dnf remove`)

## 使用方法
1. 通过MCP客户端调用以下工具：
   - `query_packages`: 查询软件包
   - `install_package`: 安装软件包
   - `remove_package`: 卸载软件包

## 依赖
- dnf
- rpm
- python3-mcp