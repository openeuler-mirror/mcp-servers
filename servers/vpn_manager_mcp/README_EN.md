# VPN Manager MCP Server

## Function Description

It manages VPN connections, including OpenVPN and StrongSwan VPN connections.

## Main Functions

- Listing available VPN configurations
- Starting or stopping a VPN connection
- Viewing the VPN connection status
- Managing VPN certificates

## System Dependencies

- openvpn
- strongswan
- python3
- uv

## Python Dependencies

- pydantic>=1.10.0
- mcp>=0.1.0

## Examples

```bash
# List available VPN configurations.
mcp vpn_manager_mcp list_vpns

# Start a VPN connection.
mcp vpn_manager_mcp start_vpn --config myvpn.ovpn

# View the VPN status.
mcp vpn_manager_mcp get_vpn_status

# Add a certificate.
mcp vpn_manager_mcp add_certificate --cert_path /tmp/ca.crt --cert_type ca
```

## Precautions

1. The root permission is required for performing VPN management operations.
2. The VPN configuration file must be stored in the **/etc/openvpn/client/** directory.
3. The StrongSwan configuration file is stored in the **/etc/ipsec.conf** and **/etc/ipsec.d/** directories.
