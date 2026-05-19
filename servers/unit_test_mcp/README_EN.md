# Unit Test MCP Server

## Function Description

It provides unit test execution and result analysis functions. The following test frameworks are supported:

- Google Test (gtest)
- Python pytest
- JUnit

## How to Use

1. Ensure that the MCP client (such as Roo Code) has been installed.
2. Add the MCP server to the client configuration.
3. Call the following tools:

### run_gtest

Execute the gtest and return the result.

Parameter:
`test_binary`: path to the gtest executable file

Example:

```json
{
  "tool": "run_gtest",
  "params": {
    "test_binary": "/path/to/test_binary"
  }
}
```

### run_pytest

Execute the pytest and return the result.

Parameter:
`test_dir`: path to the directory that contains the pytest

Example:

```json
{
  "tool": "run_pytest", 
  "params": {
    "test_dir": "/path/to/tests"
  }
}
```

### run_junit

Execute the JUnit and return the result.

Parameters:

- `test_command`: command for executing the test
- `xml_output`: path to the JUnit XML output file

Example:

```json
{
  "tool": "run_junit",
  "params": {
    "test_command": "mvn test",
    "xml_output": "target/surefire-reports/TEST-*.xml"
  }
}
```

## Dependencies

- gtest-devel
- python3-pytest
- junit
- python3-mcp

## RPM Packaging

The MCP server has been configured to be packaged as an RPM package.

```bash
python3 generate-mcp-spec.py
rpmbuild -ba mcp-servers.spec
```
