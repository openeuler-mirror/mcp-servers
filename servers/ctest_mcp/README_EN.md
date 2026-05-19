# CMake Testing Tool MCP Server

An MCP server based on the **ctest** command, providing management capabilities for CMake test suites.

## Features

- Run CMake test suites
- List all available tests
- Generate test coverage reports
- Support parallel test execution
- Support test filtering and timeout settings

## Installation

1. Ensure CMake and ctest are installed:

   ```bash
   sudo yum install cmake
   ```

2. Install Python dependencies:

   ```bash
   pip install -r src/requirements.txt
   ```

## Usage Examples

```bash
# Run all tests.
mcp ctest-mcp run_tests --build_dir /path/to/build_dir

# Run specific tests.
mcp ctest-mcp run_tests --build_dir /path/to/build_dir --tests test1 test2

# Run tests in parallel.
mcp ctest-mcp run_tests --build_dir /path/to/build_dir --parallel 4

# List all tests.
mcp ctest-mcp list_tests --build_dir /path/to/build_dir

# Generate a coverage report.
mcp ctest-mcp test_coverage --build_dir /path/to/build_dir
```

## Tool Function Description

- `run_tests(build_dir, tests=None, parallel=None, output_on_failure=True, verbose=False, timeout=None)`: Run the CMake test suite.
- `list_tests(build_dir, verbose=False)`: List all available tests.
- `test_coverage(build_dir, output_file=None)`: Generate a test coverage report.
