# System Build Assistant MCP Service

## Function Description

This service provides a standardized project-build interface by wrapping CMake and Make build commands.

## Dependencies

- cmake
- make
- python3
- uv
- python3-mcp

## Usage

### Configure a Project

```bash
mcp build_assistant_mcp configure /path/to/project [--build_type Debug|Release] [--build_dir build]
```

### Build a Project

```bash
mcp build_assistant_mcp build /path/to/project [--build_dir build] [--target target_name]
```

## Examples

1. Configure a Debug build:

        ```bash
        mcp build_assistant_mcp configure ~/my_project --build_type Debug
        ```

2. Build the project:

        ```bash
        mcp build_assistant_mcp build ~/my_project
        ```

3. Build a specific target:

        ```bash
        mcp build_assistant_mcp build ~/my_project --target install
        ```
