# Code Search Tool MCP Server

## Function Description

It provides fast code-search capabilities powered by **ripgrep (rg)**.

## Usage

```json
{
  "tool": "code_search_mcp",
  "function": "search_code",
  "params": {
    "search_term": "content to search for",
    "path": "search path (optional, defaults to current directory)",
    "file_type": "file type filtering (optional, e.g., .py, .js)"
  }
}
```

## Example

Search for `"import"` statements in all Python files under the current directory:

```json
{
  "tool": "code_search_mcp",
  "function": "search_code",
  "params": {
    "search_term": "import",
    "file_type": "py"
  }
}
```

## Dependencies

- **ripgrep (rg)** — required
- **ack** — optional (not yet implemented)

## Installation

```bash
# Install ripgrep.
sudo dnf install ripgrep
```
