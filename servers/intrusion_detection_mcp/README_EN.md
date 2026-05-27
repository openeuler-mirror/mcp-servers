# Intrusion Detection System MCP Server

The MCP server of the intrusion detection system based on the Advanced Intrusion Detection Environment (AIDE) tool provides the system file integrity check and intrusion detection functions.

## Functions

- Checking the AIDE installation status
- Initializing the AIDE database
- Performing system scanning
- Updating the AIDE database
- Viewing the scanning result
- Configuring IDS rules

## Instructions

### 1. Installing Dependencies

```bash
yum install aide
```

### 2. Initializing the AIDE Database

Initialize the database before using it for the first time.

```bash
aide --init
```

### 3. Using MCP Functions

Invoke the following functions on the MCP client:

- `check_aide_installed`: Check whether the AIDE is installed.
- `initialize_aide`: Initialize the AIDE database.
- `perform_scan`: Perform scanning.
- `update_aide_db`: Update the database.
- `get_scan_results`: Obtain the scanning result.
- `configure_rule`: Configure IDS rules.

## Example

```json
{
  "tool": "perform_scan",
  "args": {}
}
```

## RPM Packaging

The MCP server has been configured with RPM packaging. You can use the packaging script in the project to build an RPM package.
