# Git Assistant MCP Server

Git operation assistant tool, which provides the encapsulation and auxiliary functions of common Git commands.

## Functions and Features

- Repository management: clone/init/remote operations
- Branch management: creating/switching/merging branches
- Commit operations: add/commit/push
- Status viewing: status/log/diff
- Differences comparison: file/branch comparison

## Quick Start

1. Install dependencies.

        ```bash
        pip install gitpython
        ```

2. Start the services.

        ```bash
        python src/server.py
        ```

## Examples

```python
from mcp.client import MCPClient

client = MCPClient("git_assistant_mcp")

# Clone a repository.
result = client.git_clone(
    repo_url="https://github.com/example/repo.git",
    local_path="./repo"
)

# Create a branch.
result = client.create_branch(
    branch_name="feature/new-feature"
)

# Commit changes.
result = client.add_commit_and_push(
    commit_message="Add new feature"
)
```

## Dependencies

- Python >= 3.6
- gitpython >= 3.1.0
- git >= 2.0
