# ISO Tailoring Tool MCP Server

## Introduction to the Project

This is an MCP-based ISO image tailoring tool server that provides the following functions:

- Listing available ISO files
- Customizing ISO image tailoring
- Generating the Kickstart configuration file
- Managing ISO and temporary file directories

## Function Description

### Available Tools

1. `get_path_config`: Get the ISO and temporary file directory configuration.
2. `list_available_isos`: List available basic ISO files.
3. `customize_iso`: Tailor ISO images.
4. `generate_ks_config`: Generate a Kickstart configuration file.

## How to Use

1. Start the server.

    ```bash
    python3 server.py
    ```

2. Connect to and use the tool through the MCP client.

## Dependencies

- Python 3.6+
- isocut tool
- fastmcp repository

## File Structure

- `msrc/`: Store source code.
  - `server.py`: main service program
  - `mcp_config.json`: MCP server configuration
