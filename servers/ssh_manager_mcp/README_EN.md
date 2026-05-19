# SSH Manager MCP

## Function Description

An MCP server providing SSH connection management and SCP file transfer functionalities.

## Main Functions

- Establish SSH connections
- Perform SCP file transfer.
- Support key-based authentication.
- Support custom ports.

## Usage

### SSH Connection

```json
{
  "action": "ssh_connect",
  "host": "example.com",
  "username": "user",
  "port": 22,
  "key_path": "/path/to/key.pem"
}
```

### SCP File Transfer

```json
{
  "action": "scp_transfer",
  "source": "local/file.txt",
  "destination": "user@remote:/path/to/dest",
  "recursive": false
}
```

## Dependencies

- openssh-client
- sshpass (optional, for password authentication)
