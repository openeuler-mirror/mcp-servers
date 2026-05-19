# File System Management MCP Service

## Function Description

It provides functions for creating, mounting, and managing file systems, and supports common file system types such as ext4 and xfs.

## Main Functions

- Creating a file system (mkfs)
- Mounting a file system (mount)
- Listing the mounted file system

## How to Use

1. Install dependencies.

    ```bash
    yum install e2fsprogs xfsprogs util-linux
    ```

2. Start the MCP service.

    ```bash
    uv --directory /path/to/filesystem_manager_mcp/src run server.py
    ```

3. Call the service through the MCP client.

    ```json
    {
      "tool": "create_filesystem",
      "parameters": {
        "device": "/dev/sdb1",
        "fstype": "ext4"
      }
    }
    ```

## Dependencies

- System dependencies: e2fsprogs, xfsprogs, util-linux
- Python dependency: mcp-server

## Precautions

The root permission is required for performing file system operations.
