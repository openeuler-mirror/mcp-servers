# Code Review Assistant MCP Server

## Function Description

It provides automated code review capabilities with static analysis support for the following languages:

- C/C++ (via cppcheck)
- Python (via pylint)

## Dependencies

```bash
yum install cppcheck pylint python3-pylint
```

## Usage

1. Configure the service through an MCP client:

```json
{
  "mcpServers": {
    "code_review_assistant": {
      "command": "python3",
      "args": ["src/server.py"],
      "disabled": false
    }
  }
}
```

1. Call the code review interface:

```python
# Review a single file.
result = mcp.call("code_review_assistant", "analyze_code", {"file_path": "/path/to/file"})

# Review an entire directory.
result = mcp.call("code_review_assistant", "analyze_directory", {"dir_path": "/path/to/dir"})
```

## Output Format

Returns analysis results in JSON format, including:

- Issue type
- Issue description
- Severity level
- Location information

## Example Output

```json
{
  "issues": [
    {
      "type": "warning",
      "message": "Unused variable 'x'",
      "severity": "medium",
      "location": "file.py:10"
    }
  ]
}
```
