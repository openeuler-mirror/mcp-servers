# Memory Analyzer Tool MCP Server

## Function Description

The MCP server provides memory issue detection and analysis functions. The following tools are supported:

1. **valgrind** - memory error detection tool
   - Memory leakage detection
   - Detection of unauthorized memory access
   - Detection of the use of uninitialized memory

2. **AddressSanitizer** - memory error detection tool
   - Detection of heap/stack/global buffer overflow
   - Usage detection after release
   - Detection of repeated releases

3. **Memory report analysis** - analyzing memory detection reports
   - Generating structured reports
   - Multiple output formats

## Installation Requirements

- Linux
- Valgrind
- gcc (with the support for address-sanitizer)
- Python 3.6+
- MCP Python SDK

## How to Use

### 1. Using Valgrind to Detect Memory Issues

```json
{
  "tool": "valgrind_memcheck",
  "parameters": {
    "program": "/path/to/your/program",
    "args": "--your-args",
    "options": "--leak-check=full"
  }
}
```

### 2. Using AddressSanitizer to Analyze Memory Errors

```json
{
  "tool": "asan_analyze",
  "parameters": {
    "program": "/path/to/your/program",
    "args": "--your-args"
  }
}
```

### 3. Analyzing the Memory Report

```json
{
  "tool": "report_analyzer",
  "parameters": {
    "report_file": "/path/to/report.log",
    "output_format": "json"
  }
}
```

## Installing Dependencies

```bash
# Install dependencies on openEuler.
sudo yum install -y valgrind gcc libasan python3-mcp
```

## Building RPM Packages

```bash
python3 generate-mcp-spec.py
rpmbuild -ba mcp-servers.spec
