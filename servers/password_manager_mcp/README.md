# Password Manager MCP Server

## Description
This MCP server provides password management capabilities using the `pass` password manager.

## Features
- List all stored passwords
- Retrieve specific passwords
- Store new passwords securely

## Requirements
- pass (password store) installed and initialized
- GnuPG configured for pass

## Usage
1. Ensure the MCP server is running
2. Use the following API endpoints:
   - `GET /list_passwords` - List all password entries
   - `POST /get_password` - Get a specific password (requires "name" parameter)
   - `POST /store_password` - Store a new password (requires "name" and "value" parameters)

## Configuration
Edit `mcp_config.json` to modify server settings and permissions.