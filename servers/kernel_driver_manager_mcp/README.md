# 内核驱动管理MCP服务器

## 功能描述

本MCP服务器提供内核模块的管理功能，包括：

- 列出已加载的内核模块
- 查看内核模块详细信息
- 加载/卸载内核模块

## 使用说明

### 1. 列出已加载模块
```json
{"tool": "list_modules"}
```

### 2. 查看模块详情
```json
{"tool": "module_info", "module": "模块名称"}
```

### 3. 加载模块
```json
{"tool": "load_module", "module": "模块名称"}
```

### 4. 卸载模块
```json
{"tool": "unload_module", "module": "模块名称"}
```

## 依赖

- kmod
- dkms
- python3
- python3-mcp

## 安装

```bash
yum install kernel_driver_manager_mcp