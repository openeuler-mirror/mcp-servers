# Gitee MCP Usage Description

Gitee MCP provides basic operations on Gitee.

## Tools

1. create_issues
   - Parse the content and create an issue on Gitee.
   - input:
     - content: json, include the issue content

       ```json
       {
           "issues": {
               "issue1": {
                   "name": "function name"
                   "line": "line no", # [10,30]
                   "problem": "problem description"
                   "level": "problem level", # high, medium, low
                   "suggestion": "modification suggestion"
                   "fixcode": "code fixing example"
               }
           }
       }
       ```

     - owner: string, the gitee repo owner
     - repo: string, the gitee repo name
   - Returns: list, issue_urls
