# Kernel Module Builder MCP Server

## Description
This MCP server provides tools for building and installing kernel modules using DKMS.

## Features
- Build kernel modules from source
- Install compiled modules
- Handle build errors and dependencies

## Dependencies
- kernel-devel
- gcc
- dkms
- python3-mcp

## Usage
```json
{
  "tool": "build_module",
  "parameters": {
    "source_path": "/path/to/module/source",
    "module_name": "module-name"
  }
}
```

## Example
```bash
# Build and install a kernel module
mcp kernel-module-builder build_module \
  --source_path /usr/src/my-module \
  --module_name my-module
```

## Notes
- Requires root privileges for module installation
- Source directory must contain valid DKMS configuration