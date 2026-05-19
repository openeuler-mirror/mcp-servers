# USB Device Monitoring MCP Server

## Function Description

It monitors the connection status of USB devices, calls the `lsusb` command to obtain USB device information, and returns the standardized result.

## Dependencies

- System dependency: usbutils
- Python dependency: no additional dependency (using the standard Python library)

## Installation

1. Ensure that usbutils has been installed.

   ```bash
   sudo dnf install usbutils
   ```

2. Use the RPM to install the MCP server.

   ```bash
   sudo rpm -ivh usb-monitor-mcp-1.0.0.rpm
   ```

## Examples

### Request

```json
{
  "method": "get_usb_devices"
}
```

### Response

```json
{
  "devices": [
    "Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub",
    "Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub"
  ]
}
```

## Error Handling

If an error occurs, the response contains the error field.

```json
{
  "error": "error description"
}
```

## Maintenance

- Version: 1.0.0
- Maintained by: openEuler community
