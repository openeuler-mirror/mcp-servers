# Git Assistant MCP Server

Git操作辅助工具，提供常用Git命令的封装和辅助功能。

## 功能特性

- 仓库管理：clone/init/remote操作
- 分支管理：创建/切换/合并分支
- 提交操作：add/commit/push
- 状态查看：status/log/diff
- 差异比较：文件/分支对比

## 快速开始

1. 安装依赖：
```bash
pip install gitpython
```

2. 启动服务：
```bash
python src/server.py
```

## 使用示例

```python
from mcp.client import MCPClient

client = MCPClient("git_assistant_mcp")

# 克隆仓库
result = client.git_clone(
    repo_url="https://github.com/example/repo.git",
    local_path="./repo"
)

# 创建分支
result = client.create_branch(
    branch_name="feature/new-feature"
)

# 提交更改
result = client.add_commit_and_push(
    commit_message="Add new feature"
)
```

## 依赖

- Python >= 3.6
- gitpython >= 3.1.0
- git >= 2.0