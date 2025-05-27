# 内存分析工具MCP服务器

## 功能描述

本MCP服务器提供内存问题检测和分析功能，支持以下工具：

1. **valgrind** - 内存错误检测工具
   - 内存泄漏检测
   - 非法内存访问检测
   - 未初始化内存使用检测

2. **AddressSanitizer** - 内存错误检测工具
   - 堆/栈/全局缓冲区溢出检测
   - 释放后使用检测
   - 重复释放检测

3. **内存报告分析** - 分析内存检测报告
   - 生成结构化报告
   - 支持多种输出格式

## 安装要求

- Linux系统
- valgrind工具
- gcc (带address-sanitizer支持)
- Python 3.6+
- MCP Python SDK

## 使用方法

### 1. 使用valgrind检测内存问题

```json
{
  "tool": "valgrind_memcheck",
  "parameters": {
    "program": "/path/to/your/program",
    "args": "--your-args",
    "options": "--leak-check=full"
  }
}
```

### 2. 使用AddressSanitizer分析内存错误

```json
{
  "tool": "asan_analyze",
  "parameters": {
    "program": "/path/to/your/program",
    "args": "--your-args"
  }
}
```

### 3. 分析内存报告

```json
{
  "tool": "report_analyzer",
  "parameters": {
    "report_file": "/path/to/report.log",
    "output_format": "json"
  }
}
```

## 依赖安装

```bash
# 在openEuler上安装依赖
sudo yum install -y valgrind gcc libasan python3-mcp
```

## 构建RPM包

```bash
python3 generate-mcp-spec.py
rpmbuild -ba mcp-servers.spec