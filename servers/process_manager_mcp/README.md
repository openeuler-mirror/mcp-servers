# 进程管理MCP服务器

## 功能
- 查看系统进程列表
- 监控进程状态
- 终止指定进程

## 依赖
- procps-ng (提供ps/top/kill命令)
- python3-mcp

## 使用方法
1. 安装MCP服务器：
```bash
yum install process_manager_mcp
```

2. 在MCP客户端配置中添加：
```json
{
  "process_manager_mcp": {
    "command": "uv",
    "args": [
      "--directory",
      "/opt/mcp-servers/servers/process_manager_mcp/src",
      "run",
      "server.py"
    ]
  }
}
```

3. 调用功能：
- 查看进程列表：`list_processes()`
- 监控进程：`monitor_processes()`
- 终止进程：`kill_process(pid)`

## 示例
```python
# 查看所有进程
processes = list_processes()

# 监控进程
monitor = monitor_processes()

# 终止进程
result = kill_process(1234)