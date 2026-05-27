# Kernel Tuner MCP Server

## Function Description

It provides the capability of adjusting kernel running parameters through the MCP interface based on the **sysctl** command.

## Dependencies

- procps (including the **sysctl** command)
- Python 3.6+
- Flask

## APIs

### Obtaining Parameter Values

- Path: `/get_param`
- Method: POST
- Parameter:

  ```json
  {
    "param": "kernel.hostname"
  }
  ```

- Response:

  ```json
  {
    "value": "myhost"
  }
  ```

### Setting Parameters

- Path: `/set_param`
- Method: POST
- Parameter:

  ```json
  {
    "param": "vm.swappiness",
    "value": "10"
  }
  ```

- Response:

  ```json
  {
    "status": "success"
  }
  ```

### Listing All Parameters

- Path: `/list_params`
- Method: GET
- Response:

  ```json
  {
    "params": [
      "kernel.hostname",
      "vm.swappiness",
      "..."
    ]
  }
  ```

## Precautions

1. The root permission is required to modify kernel parameters.
2. Modifying some parameters may cause system instability.
3. The parameter name must comply with the regular expression `^[a-zA-Z0-9_.-]+$`.
