# 性能剖析工具MCP服务器

## 功能描述

本MCP服务器提供代码性能剖析功能，支持以下工具：

1. **perf** - Linux性能分析工具
   - CPU性能分析
   - 函数调用分析
   - 热点函数识别

2. **valgrind** - 内存分析工具
   - 内存泄漏检测
   - 内存访问错误检测
   - 缓存使用分析

## 安装要求

- Linux系统
- perf工具 (通常包含在linux-tools包中)
- valgrind工具
- Python 3.6+
- MCP Python SDK

## 使用方法

### 1. 使用perf进行性能分析

```json
{
  "tool": "perf_profile",
  "parameters": {
    "program": "/path/to/your/program",
    "duration": 10
  }
}
```

### 2. 使用valgrind进行内存分析

```json
{
  "tool": "valgrind_profile", 
  "parameters": {
    "program": "/path/to/your/program",
    "args": "--your-args"
  }
}
```

## 依赖安装

```bash
# 在openEuler上安装依赖
sudo yum install -y perf valgrind python3-mcp
```

## 构建RPM包

```bash
python3 generate-mcp-spec.py
rpmbuild -ba mcp-servers.spec