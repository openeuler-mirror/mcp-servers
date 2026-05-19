# codeReview MCP

codeReview MCP provides code-reading capabilities for C-language projects and triggers a large model to perform code inspection, returning detected issues.

## Tools

review_code

- Reads and extracts specific code elements from a project. You only need to list the elements you want to query.
- Input parameters:
  - **project_path**: The absolute path to the project to be reviewed. *Note: This must be the project root directory, not the path to a file containing the type name.*
  - **query_type**: one of [--func, --struct, --macro, --globalvar]
              "--func": {"type": "string", "description": "function name"},
              "--struct": {"type": "string", "description": "struct name"},
              "--macro": {"type": "string", "description": "macro name"},
              "--globalvar": {"type": "string", "description": "global variable name"},
              "--enum": {"type": "string", "description": "enum name"}
  - **query_name**: specific name to inspect
- Returns: list, code content, and review prompt
