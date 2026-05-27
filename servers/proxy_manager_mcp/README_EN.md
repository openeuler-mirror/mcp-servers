# Proxy Manager MCP Server

## Function Description

It provides proxy management functions, including:

- Configuring HTTP/HTTPS proxies
- Managing Squid proxy services
- Viewing the proxy status
- Restarting the proxy service

## Dependency Requirements

- System dependencies: squid
- Python dependencies: see src/requirements.txt

## Usage Instructions

1. Ensure that the Squid service is installed.
2. Use the MCP protocol to call the following functions:
   - `set_proxy`: Set proxy configuration.
   - `get_proxy_status`: Get proxy status.
   - `restart_proxy`: Restart proxy services.
   - `list_proxy_settings`: List current proxy settings.

## Configuration Instructions

Edit `mcp_config.json` to configure:

- Default proxy port
- Allowed client IPs
- Log level
