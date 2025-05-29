# 构建系统助手 MCP 服务

## 功能描述
封装CMake和Make构建命令，提供标准化的项目构建接口

## 依赖
- cmake
- make
- python3
- uv
- python3-mcp

## 使用方法

### 配置项目
```bash
mcp build_assistant_mcp configure /path/to/project [--build_type Debug|Release] [--build_dir build]
```

### 构建项目
```bash
mcp build_assistant_mcp build /path/to/project [--build_dir build] [--target target_name]
```

## 示例

1. 配置Debug版本:
```bash
mcp build_assistant_mcp configure ~/my_project --build_type Debug
```

2. 构建项目:
```bash
mcp build_assistant_mcp build ~/my_project
```

3. 构建特定目标:
```bash
mcp build_assistant_mcp build ~/my_project --target install