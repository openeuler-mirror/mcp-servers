# Compile Diagnostic Tool MCP Server

## Function Description

It analyzes **gcc/clang** compilation errors and warnings, providing structured diagnostic information.

## Dependencies

- gcc
- clang
- Python 3
- uv

## Usage

1. Start the MCP server:

    ```bash
    uv --directory /opt/mcp-servers/servers/compile_diagnostic_mcp/src run server.py
    ```

2. Call the analysis interface:

    ```json
    {
      "tool": "compile_diagnostic_mcp",
      "action": "analyze_compile_log",
      "input": {
        "log": "Compilation log content or file path"
      }
    }
    ```

## Example Output

```json
{
  "errors": [
    {
      "file": "example.c",
      "line": 10,
      "column": 5,
      "message": "expected ';' before '}' token",
      "type": "error"
    }
  ],
  "warnings": [
    {
      "file": "example.c", 
      "line": 5,
      "column": 1,
      "message": "unused variable 'x'",
      "type": "warning"
    }
  ]
}
```
