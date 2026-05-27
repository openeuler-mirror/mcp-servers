# Hardware Information Query MCP Server

## Function Description

It provides the function of querying system hardware information, including:

- CPU information
- Memory information
- Disk information
- Network device information
- BIOS information

## Dependencies

- System dependencies: lshw and dmidecode
- Python dependencies: none

## Examples

```bash
# Query complete hardware information.
mcp-tool hardware_info_mcp get_hardware_info

# Query the CPU information.
mcp-tool hardware_info_mcp get_cpu_info

# Query the memory information.
mcp-tool hardware_info_mcp get_memory_info
```

## Precautions

1. The root permission is required to obtain complete hardware information.
2. Ensure that the lshw and dmidecode tools have been installed in the system.
3. Some information may vary depending on the hardware.
