# Cache Management Tool MCP Server

## Function Description

It provides management capabilities for Redis and Memcached cache systems, supporting the execution of various cache operation commands.

## Dependencies

- Redis service installed and running
- Memcached service installed and running
- Python 3.6+

## Usage

### Execute Redis Commands

```json
{
  "tool": "redis",
  "parameters": {
    "command": "get key_name"
  }
}
```

### Execute Memcached Commands

```json
{
  "tool": "memcached", 
  "parameters": {
    "command": "stats"
  }
}
```

## Example Commands

- Set a value in Redis: `SET mykey "Hello"`
- Get a value from Redis: `GET mykey`
- Set a value in Memcached: `set mykey 0 0 5\r\nHello`
- Get Memcached status: `stats`

## Notes

1. Ensure Redis and Memcached services are running.
2. Wrap complex commands in quotes.
3. Connect to the local service (127.0.0.1) by default.
