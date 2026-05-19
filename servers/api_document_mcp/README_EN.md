# API Documentation Generation MCP Service

## Features

The service provides tools for generating API documentation, supporting the following formats:

- Doxygen (supports C/C++/Python, etc.)
- Sphinx (supports Python documentation)

## Usage

1. Call the `generate_docs` tool through an MCP client:

    ```json
    {
      "tool": "generate_docs",
      "project_path": "/path/to/project",
      "doc_type": "doxygen|sphinx"
    }
    ```

2. Run directly:

    ```bash
    uv --directory /path/to/api_document_mcp/src run server.py
    ```

## Dependencies

- doxygen
- sphinx
- python3-sphinx

## Installation Using the RPM Package

```bash
yum install mcp-api-document
```

The MCP service is automatically registered after installation.
