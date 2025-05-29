# Dependency Analyzer MCP Server

## 功能说明

提供项目依赖关系分析工具，支持以下功能：

- 分析RPM/DNF包依赖关系
- 分析Python pip包依赖关系
- 生成依赖关系树

## 使用方法

### 分析RPM包依赖

```json
{
  "tool": "dependency_analyzer_mcp",
  "function": "analyze_rpm_deps",
  "args": {
    "package": "package-name"
  }
}
```

### 分析pip包依赖

```json
{
  "tool": "dependency_analyzer_mcp",
  "function": "analyze_pip_deps",
  "args": {
    "package": "package-name"
  }
}
```

## 依赖要求

- rpm
- dnf
- python3-pip