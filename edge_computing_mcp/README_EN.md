# Edge Computing Management MCP Service

## Introduction

The edge computing management MCP service provides management capabilities for edge devices and edge applications. It supports device registration, configuration, monitoring, and maintenance, as well as application deployment and management on edge nodes.

## Features

- List all edge devices
- Add an edge device
- Remove an edge device
- Get edge device information
- Update edge device configurations
- Restart an edge device
- Deploy applications on an edge device
- List applications running on an edge device
- Get edge network status

## Installation

1. Clone the repository.
2. Enter the `edge_computing_mcp` directory.
3. Install dependencies:

   ```bash
   pip install -r src/requirements.txt
   ```

4. Start the service:

   ```bash
   python src/server.py
   ```

## Usage

### List all edge devices

```bash
mcp call edge_computing_mcp list_edge_devices
```

### Add an edge device

```bash
mcp call edge_computing_mcp add_edge_device --name "New Edge Gateway" --device_type "Gateway" --location "Factory Floor 3" --config '{"ip_range": "192.168.1.101/24", "gateway": "192.168.1.1"}'
```

### Remove an edge device

```bash
mcp call edge_computing_mcp remove_edge_device --device_id "edge-004"
```

### Get edge device information

```bash
mcp call edge_computing_mcp get_edge_device_info --device_id "edge-001"
```

### Update edge device configurations

```bash
mcp call edge_computing_mcp update_edge_device_config --device_id "edge-001" --config '{"ip_range": "192.168.1.100/24", "gateway": "192.168.1.1"}'
```

### Restart an edge device

```bash
mcp call edge_computing_mcp restart_edge_device --device_id "edge-001"
```

### Deploy applications on an edge device

```bash
mcp call edge_computing_mcp deploy_edge_application --device_id "edge-001" --app_name "Temperature Monitor" --version "1.0.0" --config '{"interval": 60, "threshold": 30}'
```

### List applications running on an edge device

```bash
mcp call edge_computing_mcp list_edge_applications --device_id "edge-001"
```

### Get edge network status

```bash
mcp call edge_computing_mcp get_edge_network_status
```

## Configuration File

The service configuration file is `mcp_config.json`, which defines the basic service information and commands.

## Packaging and Deployment

Use the `mcp-rpm.yaml` file to build an RPM package for deployment.
