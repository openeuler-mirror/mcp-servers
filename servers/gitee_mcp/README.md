# Gitee Mcp使用说明

Gitee Mcp提供对Gitee的基本操作

## Tools

1. create_issues
   - 解析content内容，并在gitee上创建issue
   - input:
     - content: json,  include the issue content

       ```json
       {
           "issues": {
               "issue1": {
                   "name": "函数名",
                   "line": "line no", # [10,30]
                   "problem": "问题描述",
                   "level": "问题等级", # 高，中，低 
                   "suggestion": "修改建议",
                   "fixcode": "修复代码示例"
               }
           }
       }
       ```

     - owner: string, the gitee repo owner
     - repo: string, the gitee repo name
   - Returns: list, issue_urls