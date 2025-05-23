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

3. `add_remote(remote_name, remote_url, repo_path)` - 添加远程Git仓库
    - remote_name: 远程仓库名称(必填)
    - remote_url: 远程仓库URL(必填)
    - repo_path: 仓库路径(可选)

4. `git_pull(repo_path, remote_name, branch_name)` - 从远程仓库拉取代码
    - repo_path: 仓库路径(可选)
    - remote_name: 远程名称(可选，默认为"origin")
    - branch_name: 分支名称(可选，默认为当前分支)

5. `get_git_config(repo_path)` - 获取Git用户配置
   - repo_path: 仓库路径

### 提交管理
6. `add_commit_and_push(commit_message, user_name, user_email, repo_path, files)` - 添加、提交并推送更改
   - commit_message: 提交信息(可选，默认为"auto commit")
   - user_name: Git用户名(可选)
   - user_email: Git邮箱(可选)
   - repo_path: 仓库路径(可选)
   - files: 要添加的文件列表(可选，不指定则添加所有修改)

7. `git_diff_unstaged(repo_path)` - 查看未暂存的变更
   - repo_path: 仓库路径

8. `git_diff_staged(repo_path)` - 查看已暂存的变更
   - repo_path: 仓库路径

9. `git_diff(repo_path, target)` - 对比分支或提交
   - repo_path: 仓库路径(必填)
   - target: 对比目标分支或提交(必填)

10. `git_reset(repo_path)` - 重置暂存区
    - repo_path: 仓库路径

11. `git_show(repo_path, revision)` - 查看提交详情
    - repo_path: 仓库路径(必填)
    - revision: 提交hash或分支名称(必填)

### 分支管理
12. `create_branch(branch_name, repo_path)` - 创建新分支
    - branch_name: 新分支名称(必填)
    - repo_path: 仓库路径(可选)

13. `list_branches(repo_path)` - 列出所有分支
    - repo_path: 仓库路径(可选)

### Patch管理
14. `cherry_pick_to_patch(repo_path, commit_hash, patch_path, patch_filename)` - 为指定commit生成patch文件
    - repo_path: 仓库路径(必填)
    - commit_hash: 要生成patch的commit hash(必填)
    - patch_path: 生成的patch文件路径(可选，默认为当前目录)
    - patch_filename: patch文件名(不含扩展名)(可选)

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
```

### 为指定的单个commit生成patch文件

指定文件名和保存目录：

```
将/home/xxrepo仓库的commit a359xxxx打成patch文件，命名为xxx.patch，保存到/xx目录
```

不指定文件名，使用git format-patch默认生成的文件名0001-<提交信息标题>.patch，默认保存到当前目录：

```
将/home/xxrepo仓库的commit a359xxxx打成patch文件
```

