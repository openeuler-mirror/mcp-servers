# Process Management MCP Server

## Functions

- Viewing system process lists
- Monitoring process status
- Killing specified processes

## Dependencies

- procps-ng (provides `ps/top/kill` commands)
- python3-mcp

## Usage

1. Install MCP server:

    ```bash
    yum install process_manager_mcp
    ```

2. Add the following to MCP client configurations:

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

3. Call functions:

- List processes: `list_processes()`
- Monitor processes: `monitor_processes()`
- Kill process: `kill_process(pid)`

## Examples

```python
# List all processes.
processes = list_processes()

# Monitor processes.
monitor = monitor_processes()

# Kill a process.
result = kill_process(1234)
```
