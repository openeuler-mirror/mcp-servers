# Network Monitoring MCP Server

## Function Description

It provides the network traffic monitoring function, including:

- Real-time network traffic monitoring (based on iftop)
- Network connection status check (based on nethogs)
- Bandwidth usage statistics

## Installation Requirements

```bash
yum install -y iftop nethogs
```

## How to Use

1. Ensure that the iftop and nethogs tools have been installed.
2. Call the following functions on the MCP client:

```python
# Monitor the traffic of the eth0 interface.
monitor_traffic(interface="eth0")

# View the current network connection.
show_connections()

# Obtain the bandwidth usage of the eth0 interface.
get_bandwidth(interface="eth0")
```

## Precautions

1. The root permission is required to run iftop and nethogs.
2. By default, the eth0 interface is monitored. You can specify other network interfaces.
3. The real-time monitoring function returns the result after one second.
