# User Management MCP Server

## Function

- Adding a user
- Deleting a user
- Changing user information

## Dependencies

- shadow-utils (providing the **useradd**, **userdel**, and **usermod** commands)
- python3-mcp

## Instructions

### 1. Installation

```bash
yum install mcp-user-manager
```

### 2. Configuration

Add the following content to the MCP client configuration file:

```json
{
  "user_manager_mcp": {
    "command": "uv",
    "args": [
      "--directory",
      "/opt/mcp-servers/servers/user_manager_mcp/src",
      "run",
      "server.py"
    ]
  }
}
```

### 3. Examples

- Adding a user

  ```python
  add_user("testuser", "password123")
  ```

- Deleting a user

  ```python 
  delete_user("testuser")
  ```

- Modifying a user

  ```python
  modify_user("testuser", new_name="newuser", password="newpass")
  ```

## Precautions

- The sudo permission is required for performing user management operations.
- Interactive input is required for password change.
