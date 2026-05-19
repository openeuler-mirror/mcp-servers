# System Resource Limit MCP Server

## Function Description

It manages system resource limits by modifying the `/etc/security/limits.conf` file.

## Dependencies

- pam_limits
- python3
- uv
- python3-mcp

## How to Use

1. Ensure that all dependencies have been installed.
2. Start the MCP server.
3. Call the provided tool interfaces on the MCP client.

## Provided Tool Interfaces

- `get_limits()`: Obtain the current system resource limit configuration.
- `set_limits(domain, type, item, value)`: Set resource limits for a specified domain.
- `add_limit(domain, type, item, value)`: Add new resource limits.
- `remove_limit(domain, item)`: Remove resource limits of a specified domain.

## Parameter Description

- `domain`: user/group name. The asterisk (*) indicates all users, and "root" indicates the root user.
- `type`: limit type, which can be **hard** or **soft**.
- `item`: limit item, such as **nofile** (number of file descriptors) and **nproc** (number of processes)
- `value`: limit value

## Precautions

1. The root permission is required for modifying the **limits.conf** file.
2. A backup file `limits.conf.bak` is automatically created before each modification.
3. After the modification, you need to log in again or restart the service for the modification to take effect.
