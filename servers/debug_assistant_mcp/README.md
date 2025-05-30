# Debug Assistant MCP Server

A FastMCP implementation providing debugging tools and utilities for MCP servers.

## Features

- Remote debugging session management
- Log analysis and pattern detection
- Basic performance monitoring

## Installation

```bash
# Install dependencies
pip install fastmcp debugpy psutil

# Run the server
python3 src/server.py
```

## Usage Examples

### Start a debug session
```json
{
  "tool": "start_debug_session",
  "arguments": {
    "session_id": "test_session",
    "port": 5678
  }
}
```

### Analyze logs
```json
{
  "tool": "analyze_logs", 
  "arguments": {
    "log_data": "ERROR: Failed to connect\nWARNING: Retrying..."
  }
}
```

### Get performance stats
```json
{
  "tool": "get_performance_stats",
  "arguments": {}
}
```

## RPM Package

Build RPM package using:
```bash
mcp-build debug_assistant_mcp