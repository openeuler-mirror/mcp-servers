# System Monitoring MCP Server

## Function

It monitors system resource usage, including:

- CPU usage
- Memory usage
- Disk usage

## Dependencies

- System dependencies: sysstat, htop
- Python dependencies: See **src/requirements.txt**.

## Instructions

### Available Commands

- `cpu_usage`: Obtain the CPU usage.
- `memory_usage`: Obtain the memory usage.
- `disk_usage`: Obtain the disk usage.

### Example

```json
{
  "command": "cpu_usage",
  "args": {}
}
```

## Building Description

For details, see [MCP-Server-RPM Packaging Guide](../doc/MCP-Server-RPM Packaging Guide.md) in the root directory of the project.
