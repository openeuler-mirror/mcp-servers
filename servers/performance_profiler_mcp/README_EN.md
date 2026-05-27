# Performance Profiling Tool MCP Server

## Function Description

This MCP server provides code performance profiling capabilities, supporting the following tools:

1. **perf** - Linux performance analysis tool
   - CPU performance analysis
   - Function call analysis
   - Hotspot function identification

2. **valgrind** - Memory analysis tool
   - Memory leak detection
   - Memory access error detection
   - Cache usage analysis

## Installation Requirements

- Linux system
- perf tool (usually included in the linux-tools package)
- valgrind tool
- Python 3.6+
- MCP Python SDK

## Usage

### 1. Using perf for Performance Analysis

```json
{
  "tool": "perf_profile",
  "parameters": {
    "program": "/path/to/your/program",
    "duration": 10
  }
}
```

### 2. Using valgrind for Memory Analysis

```json
{
  "tool": "valgrind_profile", 
  "parameters": {
    "program": "/path/to/your/program",
    "args": "--your-args"
  }
}
```

## Dependency Installation

```bash
# Install dependencies on openEuler.
sudo yum install -y perf valgrind python3-mcp
```

## Building RPM Packages

```bash
python3 generate-mcp-spec.py
rpmbuild -ba mcp-servers.spec
```
