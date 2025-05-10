import requests
from pydantic import Field
import json
from typing import Optional
import os
from mcp.server.fastmcp import FastMCP



# curl -X POST --header 'Content-Type: application/json;charset=UTF-8'
# f"https://gitee.com/api/v5/repos/{owner}/issues"
# -d '{"access_token":"xxx","repo":"famfs","title":"d"}'

mcp = FastMCP("gitee_mcp")
access_tooken = os.environ["GITEE_PERSONAL_ACCESS_TOKEN"]

def gitee_issue_submit(title: str, desc: str, repo: str , owner: str):
    data = {
        "title": f"[LLM REVIEWER] {title}",
        "body": f"**这是一个LLM自动产生的issue：**\n{desc}",
        "labels": "FROM_LLM",
        "access_token": access_tooken,
        "repo": repo
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
    }
    url = f"https://gitee.com/api/v5/repos/{owner}/issues"
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 201:
        jsontext = json.loads(response.text)
        return jsontext['html_url']
    else:
        print(f"Error: {response.status_code} - {response.text}")
        return None

# def handle_issues(content):
#     if len(content["issues"]) == 0:
#         return
#     issue_urls = []
#     for idx, (issue_name, details) in enumerate(content['issues'].items(), 1):
#         file_desc = ""
#         file_desc = f"  问题行：{details['line']}\n"
#         file_desc += f"  描述：{details['problem']}\n"
#         file_desc += f"  风险等级：{details['level']}\n"
#         file_desc += f"  修改建议：{details['suggestion']}\n"
#         file_desc += f"  代码示例：\n```c\n  {details['fixcode']}\n```"
#         issue_url = gitee_issue_submit(f"函数：<{details['name']}> 问题：{details['title']}", file_desc)
#         issue_urls.append(issue_url)
#     return issue_urls

@mcp.tool()
def create_issue(
    content: dict = Field(..., description="the issue content"),
    owner: str = Field(..., description="the gitee repo owner"),
    repo: str = Field(..., description="the gitee repo name"),
) -> list:
    """
    解析content内容，并在gitee上创建issue

    Args:
        content: a josn  include the issue content
            {
                "issues": {
                    "issue1": {
                        "name": "函数名",
                        "line": [10,30],
                        "problem": "问题描述",
                        "level": "高",
                        "suggestion": "修改建议",
                        "fixcode": "修复代码示例"
                    }
                }
            }
        owner: the gitee repo owner
        repo: the gitee repo name
    Returns:
        issue_urls
    """
    if len(content["issues"]) == 0:
        return
    issue_urls = []
    for idx, (issue_name, details) in enumerate(content['issues'].items(), 1):
        file_desc = ""
        file_desc = f"  问题行：{details['line']}\n"
        file_desc += f"  描述：{details['problem']}\n"
        file_desc += f"  风险等级：{details['level']}\n"
        file_desc += f"  修改建议：{details['suggestion']}\n"
        file_desc += f"  代码示例：\n```c\n  {details['fixcode']}\n```"
        issue_url = gitee_issue_submit(f"函数：<{details['name']}> 问题：{details['title']}", file_desc, repo, owner)
        issue_urls.append(issue_url)
    return issue_urls

if __name__ == "__main__":
    # Run the server with stdio transport
    mcp.run()
