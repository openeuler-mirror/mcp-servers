# Firewall Management MCP Server

## Function Overview

It provides the function of viewing and managing firewall rules, including:

- Viewing the firewall status
- Managing port rules (adding/deleting)
- Reloading the firewall configuration

## Instructions

### Obtaining the Firewall Status

```json
{
  "tool": "get_status"
}
```

### Listing Open Ports

```json
{
  "tool": "list_ports",
  "zone": "public" //optional parameter
}
```

### Adding a Port Rule

```json
{
  "tool": "add_port",
  "port": "8080",
  "protocol": "tcp",
  "zone": "public" //optional parameter
}
```

### Deleting a Port Rule

```json
{
  "tool": "remove_port", 
  "port": "8080",
  "protocol": "tcp",
  "zone": "public" //optional parameter
}
```

### Reloading the Configuration

```json
{
  "tool": "reload_firewall"
}
```

## Precautions

1. The firewalld service must be installed and run in the system.
2. The **--permanent** parameter is required for all modification operations.
3. After the modification, run the **reload_firewall** command for the modification to take effect.
4. The root permission is required for running the **firewall-cmd** command.
