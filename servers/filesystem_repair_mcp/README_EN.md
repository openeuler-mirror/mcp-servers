# File System Repair MCP Server

## Function Description

It provides the file system repair function and supports the following operations:

- Detection and repair of damaged file systems
- Support for common file system types such as ext2/3/4 and xfs
- Support for forcible repair and interactive repair modes

## Dependencies

- e2fsprogs (providing the fsck tool)
- xfsprogs (providing the xfs_repair tool)

## How to Use

```json
{
  "type": "tool",
  "name": "fsck",
  "parameters": {
    "device": "/dev/sda1",
    "fs_type": "ext4",
    "force": true,
    "interactive": false
  }
}
```

## Parameter Description

| Parameter| Type| Mandatory| Description|
|--------|------|------|------|
| device | string | Yes| Path of the device to be repaired (for example, **/dev/sda1**)|
| fs_type | string | No| File system type (for example, **ext4** or **xfs**)|
| force | boolean | No| Whether to perform forcible repair (default: **false**)|
| interactive | boolean | No| Whether to perform interactive repair (default: **false**)|

## Returned Results

```json
{
  "success": true,
  "output": repair result output
  "error": error information
  "exit_code": 0
}
```

## Precautions

1. The root permission is required for performing the repair operation.
2. Forcible repair may cause data loss. Exercise caution when performing this operation.
