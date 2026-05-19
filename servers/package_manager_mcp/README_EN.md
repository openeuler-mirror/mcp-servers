# Software Package Management MCP Server

## Function Description

It provides software package management functions, including:

- Querying software package information (`dnf list/search`)
- Installing a software package (`dnf install`)
- Uninstalling a software package (`dnf remove`)

## How to Use

Call the following tools on the MCP client:

- `query_packages`: Query software packages.
- `install_package`: Install a software package.
- `remove_package`: Uninstall a software package.

## Dependencies

- dnf
- rpm
- python3-mcp
