# File Integrity Check MCP Server

## Function Description

It provides the system file integrity check function based on AIDE and Tripwire.

- Initializing the file integrity database
- Checking file integrity
- Viewing the report
- Updating the database

## Dependencies

- aide
- tripwire
- python3
- uv
- python3-mcp

## How to Use

1. Ensure that all dependencies have been installed.
2. Initialize the database: `init_database`
3. Perform the check: `run_check`
4. View the report: `view_report`
5. Update the database: `update_database`

## Configuration

The configuration file is stored in `mcp_config.json`. You can configure the following function permissions:

- init_database
- run_check
- view_report
- update_database
