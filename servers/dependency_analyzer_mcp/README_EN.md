# Dependency Analyzer MCP Server

## Function Description

It provides a project dependency analysis tool that supports the following functions:

- Analyzing RPM/DNF package dependencies
- Analyzing Python pip package dependencies
- Generating a dependency tree

## How to Use

### Analyzing RPM Package Dependencies

```json
{
  "tool": "dependency_analyzer_mcp",
  "function": "analyze_rpm_deps",
  "args": {
    "package": "package-name"
  }
}
```

### Analyzing pip Package Dependencies

```json
{
  "tool": "dependency_analyzer_mcp",
  "function": "analyze_pip_deps",
  "args": {
    "package": "package-name"
  }
}
```

## Dependencies

- rpm
- dnf
- python3-pip
