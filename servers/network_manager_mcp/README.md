# Network Manager MCP Server

Provides network interface configuration capabilities using NetworkManager and iproute2 commands.

## Features

- List all network interfaces
- Get interface status
- Configure IP addresses
- Manage connection states
- Toggle interface up/down

## Tools

- `list_interfaces`: List all network interfaces
- `get_interface_status`: Get status of a specific interface
- `configure_ip_address`: Configure IP address on an interface
- `show_connections`: Show all NetworkManager connections
- `toggle_interface`: Bring interface up or down

## Dependencies

- NetworkManager
- iproute2
- Python 3
- mcp package

## Installation

This server is packaged as an RPM and will be installed as part of the mcp-servers package.