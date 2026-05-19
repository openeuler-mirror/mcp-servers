# LTO Analysis Tool MCP Server

The MCP server based on the **lto-dump** command provides the link-time optimization (LTO) analysis function.

## Functions

- Displaying LTO summary
- Listing the symbol table
- Displaying the IR code
- Analyzing optimization information

## Installation

1. Ensure that the LLVM toolchain has been installed.

   ```bash
   sudo yum install llvm
   ```

2. Install dependencies for Python.

   ```bash
   pip install -r src/requirements.txt
   ```

## Examples

```bash
# Displaying LTO summary
mcp lto-dump-mcp show_lto_summary --input_file /path/to/file.o

# List the symbol table.
mcp lto-dump-mcp list_symbols --input_file /path/to/file.o

# Display the IR code.
mcp lto-dump-mcp show_ir_code --input_file /path/to/file.o

# Analyze optimization information.
mcp lto-dump-mcp analyze_optimizations --input_file /path/to/file.o
```

## Tool Function Description

- `show_lto_summary(input_file)`: Display the LTO summary.
- `list_symbols(input_file)`: List the LTO symbol table.
- `show_ir_code(input_file)`: Display the LTO IR code.
- `analyze_optimizations(input_file)`: Analyze LTO optimization information.
