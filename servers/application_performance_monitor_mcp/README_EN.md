# Application Performance Monitoring MCP Server

## Function Description

This MCP server provides application performance monitoring capabilities, integrating Prometheus and Grafana to deliver:

- Real-time performance metric collection
- Visual monitoring dashboards
- Historical data queries

## Dependencies

- Prometheus service
- Grafana service
- Python 3.6+

## Usage

1. Ensure Prometheus and Grafana are installed and running.
2. Start the MCP server:

```bash
python3 src/server.py
```

## Tool Description

### get_metrics

Gets application performance metrics:

```json
{
  "app_name": "your_application",
  "time_range": "5m"
}
```

### setup_monitoring

Configures monitoring for an application:

```json
{
  "app_name": "your_application", 
  "port": 9090
}
```

## Configuration

Modify `mcp_config.json` to adjust:

- Types of metrics to monitor
- Default time range
- Prometheus/Grafana connection addresses
