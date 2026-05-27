# Log Analyzer MCP Server

## Function Description

It provides the system log analysis function, including:

- Analyzing the log file /var/log/messages
- Querying systemd journal logs
- Providing log statistics

## Instructions

### Tools

1. `analyze_syslog` - analyzing system log files
   - Parameters:
     - `keyword`: searching keywords
     - `since`: start time
     - `until`: end time
     - `service`: service name

2. `query_journal` - querying journal logs
   - Parameters:
     - `unit`: systemd unit
     - `priority`: log level
     - `since`: start time
     - `until`: end time

### Resource List

1. `log_stats` - obtaining log statistics
   - Parameter:
     - `time_range`: time range (for example, "`1h`" or "`24h`")

## Dependencies

- System dependencies: rsyslog, systemd, and python3
- Python dependency: python3-mcp

## Installation

```bash
yum install mcp-log-analyzer
```

## Configuration

Add the following content to the MCP client configuration file:

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
