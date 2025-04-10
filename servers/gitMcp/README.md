# gitMcp MCP Server 使用说明

gitMcp 提供了Git相关操作的MCP服务，包括仓库管理、分支操作、提交推送、差异比较等功能。

## 1. 环境准备

### 1.1 安装Python依赖

推荐使用 `uv` 安装到虚拟环境：

```bash
sudo pip3 install uv --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

安装其他必要依赖：

```bash
sudo pip install pydantic mcp gitpython inquirer --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

### 1.2 配置Git认证

确保已安装Git并配置好用户认证信息，且具备推送代码的权限。

如果使用SSH密钥认证，建议添加以下配置，避免首次连接时的交互式确认：

添加到 ~/.ssh/config（示例使用gitee.com）：

```plaintext
Host gitee.com
    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null
```

## 2. MCP 配置

当前示例使用 VScode 开发平台，在插件 Roo Code中配置了 DeepSeek-V3 的API。

打开 MCP 配置页面，编辑 MCP 配置文件 `mcp_settings.json`，在 `mcpServers` 中新增如下内容：


```json
{
  "mcpServers": {
    "gitMcp": {
      "command": "uv",
      "args": [
        "--directory",
        "YOUR_PATH/mcp-servers/servers/gitMcp/src",
        "run",
        "git_mcp.py"
      ],
      "disabled": false,
      "alwaysAllow": [
        "git_status"
      ]
    }
  }
}
```

配置完成后，可以在 MCP 列表上看到 `gitMcp` 服务。

## 3. 功能说明

gitMcp 提供以下工具函数：

### 基础操作
1. `git_status(repo_path)` - 获取Git仓库状态
   - repo_path: 仓库路径

2. `git_init(repo_path)` - 初始化Git仓库
   - repo_path: 仓库路径

3. `get_git_config(repo_path)` - 获取Git用户配置
   - repo_path: 仓库路径

### 提交管理
4. `add_commit_and_push(commit_message, user_name, user_email, repo_path, files)` - 添加、提交并推送更改
   - commit_message: 提交信息
   - user_name: Git用户名(可选)
   - user_email: Git邮箱(可选)
   - repo_path: 仓库路径
   - files: 要添加的文件列表(可选，不指定则添加所有修改)

5. `git_diff_unstaged(repo_path)` - 查看未暂存的变更
   - repo_path: 仓库路径

6. `git_diff_staged(repo_path)` - 查看已暂存的变更
   - repo_path: 仓库路径

7. `git_diff(repo_path, target)` - 对比分支或提交
   - repo_path: 仓库路径
   - target: 对比目标分支或提交

8. `git_reset(repo_path)` - 重置暂存区
   - repo_path: 仓库路径

### 分支管理
9. `create_branch(branch_name, repo_path)` - 创建新分支
   - branch_name: 新分支名称
   - repo_path: 仓库路径

10. `list_branches(repo_path)` - 列出所有分支
    - repo_path: 仓库路径

11. `git_checkout(branch_name, repo_path)` - 切换分支
    - branch_name: 分支名称
    - repo_path: 仓库路径

### 提交查看
12. `git_show(repo_path, revision)` - 查看提交详情
    - repo_path: 仓库路径
    - revision: 提交hash或分支名称

## 4. 使用示例

### 创建新分支并提交更改

```
创建名为feature/new-feature的新分支
添加文件file1.txt和file2.txt
提交信息为"实现新功能"
```

### 查看仓库状态和差异

```
查看当前仓库状态
查看未暂存的变更
查看与main分支的差异
```

### 选择性提交文件

```
只提交src/main.py和src/utils.py文件
提交信息为"优化核心功能"
```

### 把当前的所有修改提交到远端仓库

```
提交并推送本地仓库当前分支的所有修改
```

### 查看提交历史

```
查看最近的5个提交记录
查看特定提交的详细信息