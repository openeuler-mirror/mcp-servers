# Log Analyzer MCP Server

## 功能描述

提供系统日志分析功能，包括：
- 分析/var/log/messages日志文件
- 查询systemd journal日志
- 提供日志统计信息

## 使用说明

### 工具列表

1. **analyze_syslog** - 分析系统日志文件
   - 参数:
     - keyword: 搜索关键词
     - since: 起始时间
     - until: 结束时间 
     - service: 服务名称

2. **query_journal** - 查询journal日志
   - 参数:
     - unit: systemd单元
     - priority: 日志级别
     - since: 起始时间
     - until: 结束时间

### 资源列表

1. **log_stats** - 获取日志统计信息
   - 参数:
     - time_range: 时间范围(如"1h","24h")

## 依赖

- 系统依赖: rsyslog, systemd, python3
- Python依赖: python3-mcp

## 安装

```bash
yum install mcp-log-analyzer
```

## 配置

在MCP客户端配置文件中添加:

```json
{
  "log_analyzer_mcp": {
    "command": "/usr/bin/uv",
    "args": [
      "--directory",
      "/usr/lib/mcp-servers/log_analyzer_mcp",
      "run",
      "--python",
      "/usr/bin/python3",
      "server.py"
    ]
  }
}