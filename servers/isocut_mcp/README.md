# ISO 裁剪工具 MCP 服务器

## 项目简介
这是一个基于 MCP 协议的 ISO 镜像裁剪工具服务器，提供以下功能：
- 列出可用 ISO 文件
- 自定义 ISO 镜像裁剪
- 生成 Kickstart 配置文件
- 管理 ISO 和临时文件目录

## 功能说明
### 可用工具
1. `get_path_config`: 获取 ISO 和临时文件目录配置
2. `list_available_isos`: 列出可用的基础 ISO 文件
3. `customize_iso`: 裁剪 ISO 镜像
4. `generate_ks_config`: 生成 Kickstart 配置文件

## 使用方法
1. 启动服务器:
```bash
python3 server.py
```

2. 通过 MCP 客户端连接并使用工具

## 依赖
- Python 3.6+
- isocut 工具
- fastmcp 库

## 文件结构
- `msrc/`: 存放源代码
  - `server.py`: 主服务程序
  - `mcp_config.json`: MCP 服务器配置