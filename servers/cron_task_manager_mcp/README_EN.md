# Cron Task Management MCP Server

## Function Description

It provides an MCP tool for managing cron scheduled tasks, including adding, removing, listing, and editing cron jobs.

## Dependencies

- cronie
- python3
- python3-mcp
- uv

## Available Tools

### add_cron_job

Adds a new cron task.

Parameters:

- `schedule`: cron time expression (e.g., `"* * * * *"`)
- `command`: command to execute
- `user`: username (default: `root`)

### remove_cron_job

Removes cron tasks matching a pattern.

Parameters:

- `command_pattern`: pattern of the command to remove
- `user`: username (default: `root`)

### list_cron_jobs

Lists all cron tasks.

Parameter:

`user`: username (default: `root`)

### edit_cron_job

Edits an existing cron task.

Parameters:

- `old_pattern`: pattern of the old command to replace
- `new_schedule`: new cron time expression
- `new_command`: new command
- `user`: username (default: `root`)

## Example

```python
from mcp.client import MCPClient

client = MCPClient()
# Add a backup task that runs every day at 3 am.
client.cron_task_manager_mcp.add_cron_job(
    "0 3 * * *",
    "/usr/bin/backup.sh"
)
# List all tasks.
print(client.cron_task_manager_mcp.list_cron_jobs())
```
