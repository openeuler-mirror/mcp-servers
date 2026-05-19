# Middleware Manager MCP Server

## Introduction

The Middleware Manager MCP Server provides the function of managing common middleware in the system, including status monitoring, service starting/stopping/restarting, and viewing configuration files and logs.

## Supported Middleware

- Redis
- Kafka
- RabbitMQ
- MySQL
- PostgreSQL
- MongoDB
- Elasticsearch
- Nginx
- Apache2
- Memcached

## Functions

### 1. Listing Middleware

- **Function**: List common middleware in the system and their statuses.
- **Method**: `list_middleware`
- **Parameter**: None
- **Return**: middleware list and status

### 2. Obtaining the Middleware Status

- **Function**: Obtain the status of a specified middleware.
- **Method**: `get_middleware_status`
- **Parameter**
  - `middleware_name`: middleware name
- **Return**: middleware status

### 3. Starting the Middleware

- **Function**: Start a specified middleware service.
- **Method**: `start_middleware`
- **Parameter**
  - <idp:inline displayname="code" id="code115091242102214">middleware_name</idp:inline>: middleware name
- **Return**: startup result

### 4. Stopping the Middleware

- **Function**: Stop a specified middleware service.
- **Method**: `stop_middleware`
- **Parameter**
  - <idp:inline displayname="code" id="code05101642202218">middleware_name</idp:inline>: middleware name
- **Return**: stop result

### 5. Restarting the Middleware

- **Function**: Restart a specified middleware service.
- **Method**: `restart_middleware`
- **Parameter**
  - <idp:inline displayname="code" id="code5510642192216">middleware_name</idp:inline>: middleware name
- **Return**: restart result

### 6. Obtaining Middleware Information

- **Function**: Obtain details about a specified middleware, including the version and configuration file location.
- **Method**: `get_middleware_info`
- **Parameter**
  - <idp:inline displayname="code" id="code151119420225">middleware_name</idp:inline>: middleware name
- **Return**: middleware details (in JSON format)

### 7. Viewing Middleware Configurations

- **Function**: View the content of the middleware configuration file.
- **Method**: `view_middleware_config`
- **Parameter**
  - <idp:inline displayname="code" id="code15512042162214">middleware_name</idp:inline>: middleware name
  - `config_path`: configuration file path (optional)
- **Return**: configuration file content

### 8. Viewing Middleware Logs

- **Function**: View the log file of the middleware.
- **Method**: `get_middleware_logs`
- **Parameter**
  - <idp:inline displayname="code" id="code135126421226">middleware_name</idp:inline>: middleware name
  - `lines`: number of log lines to be viewed (50 by default)
- **Return**: log content

## Installation and Configuration

1. Ensure that Python 3.6+ and uv have been installed in the system.
2. Install the dependency: `pip install -r src/requirements.txt`
3. Configure the **mcp_config.json** file.
4. Add the service to the MCP service list.

## Examples

### Example 1: Listing All Middleware and Their Statuses

```python
from mcp.client import MCPClient

client = MCPClient()
result = client.call("middleware_manager_mcp", "list_middleware")
print(result)
```

### Example 2: Starting the Redis Service

```python
from mcp.client import MCPClient

client = MCPClient()
result = client.call("middleware_manager_mcp", "start_middleware", middleware_name="redis")
print(result)
```

### Example 3: Viewing the Nginx Configuration File

```python
from mcp.client import MCPClient

client = MCPClient()
result = client.call("middleware_manager_mcp", "view_middleware_config", middleware_name="nginx")
print(result)
```

## Precautions

1. Some operations may require the administrator or root permission.
2. Service management commands may vary depending on the OS (Windows/Linux).
3. Ensure that the middleware has been correctly installed in the system.
4. The paths of configuration files and log files may vary depending on the system.
