# 文件系统管理MCP服务

## 功能说明
提供文件系统创建、挂载和管理功能，支持ext4/xfs等常见文件系统类型。

## 主要功能
- 创建文件系统 (mkfs)
- 挂载文件系统 (mount)
- 列出已挂载文件系统

## 使用方法
1. 安装依赖:
```bash
yum install e2fsprogs xfsprogs util-linux
```

2. 启动MCP服务:
```bash
uv --directory /path/to/filesystem_manager_mcp/src run server.py
```

3. 通过MCP客户端调用:
```json
{
  "tool": "create_filesystem",
  "parameters": {
    "device": "/dev/sdb1",
    "fstype": "ext4"
  }
}
```

## 依赖
- 系统依赖: e2fsprogs, xfsprogs, util-linux
- Python依赖: mcp-server

## 注意事项
需要root权限执行文件系统操作