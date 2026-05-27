# Container Orchestration Tool MCP Server

## Function Description

It provides container orchestration and management capabilities based on docker-compose, including:

- Starting and stopping container services
- Managing docker-compose configurations

## Dependencies

- Docker Engine
- docker-compose
- Python 3.6+

## Usage

1. Install dependencies:

    ```bash
    pip install -r src/requirements.txt
    ```

2. Start the service:

    ```bash
    python src/server.py
    ```

## APIs

### Start a Service

`POST /compose/up`

```json
{
  "compose_file": "docker-compose.yml"
}
```

### Stop a Service

`POST /compose/down`

```json
{
  "compose_file": "docker-compose.yml"
}
```

## Packaging Instructions

This MCP server supports RPM packaging. You can generate an RPM package directly using the packaging script in the project root directory.
