# HTTP Test Tool MCP Server

## Function Description

It encapsulates HTTP request functions, supports common HTTP methods such as GET, POST, PUT, and DELETE, and provides simple APIs.

## Dependencies

- System dependencies: curl, httpie
- Python dependency: requests

## Installation Procedure

1. Ensure that dependencies have been installed.

    ```bash
    dnf install curl httpie python3-requests
    ```

2. Perform the installation through the MCP.

    ```bash
    mcp install http_test_tool_mcp
    ```

## Examples

```python
# Send a GET request.
response = mcp.http_test_tool.get("https://api.example.com/data")

# Send a POST request.
response = mcp.http_test_tool.post(
    "https://api.example.com/data",
    json={"key": "value"},
    headers={"Content-Type": "application/json"}
)
```

## APIs

- `get(url, params=None, headers=None)`: Send a GET request.
- `post(url, data=None, json=None, headers=None)`: Send a POST request.
- `put(url, data=None, json=None, headers=None)`: Send a PUT request.
- `delete(url, headers=None)`: Send a DELETE request.
- `request(method, url, **kwargs)`: Send a custom HTTP request.

All methods return a dictionary containing the following fields:

- `status_code`: HTTP status code
- `headers`: response header
- `content`: response content
- `elapsed`: request duration (s)
