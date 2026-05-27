# Kernel Driver Management MCP Server

## Function Description

The MCP server provides the following kernel module management functions:

- Listing loaded kernel modules
- Viewing kernel module details
- Loading/Unloading kernel modules

## Instructions

### 1. Listing Loaded Modules

```json
{"tool": "list_modules"}
```

### 2. Viewing Module Details

```json
{"tool": "module_info", "module": "module name"}
```

### 3. Loading a Module

```json
{"tool": "load_module", "module": "module name"}
```

### 4. Unloading a Module

```json
{"tool": "unload_module", "module": "module name"}
```

## Dependencies

- kmod
- dkms
- python3
- python3-mcp

## Installation

```bash
yum install kernel_driver_manager_mcp
