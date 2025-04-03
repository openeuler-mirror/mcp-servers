# oeGitExt MCP Server 使用说明

oeGitExt 提供了管理 openEuler 社区 issue、repos、PR 和 project 的 MCP 服务

## 1. 环境准备

安装 python 依赖。为了更加直观，当前示例使用 `pip` 安装到系统的 python 目录，实际上更加推荐 `uv` 安装到虚拟环境。

```bash
pip install pydantic mcp requests gitpython --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

确保已安装 oegitext 命令行工具并配置好 openEuler 社区账号

## 2. MCP 配置

在插件 Roo Code 中配置 MCP 服务器，编辑 MCP 配置文件 `mcp_settings.json`，在 `mcpServers` 中新增如下内容：

```json
{
  "mcpServers": {
    "oeGitExt": {
      "command": "uv",
      "args": [
        "--directory",
        "/your_path/mcp-servers/servers/oeGitExt/src",
        "run",
        "oegitext_mcp.py"
      ],
      "disabled": false,
      "alwaysAllow": [
        "get_my_openeuler_project"
      ]
    }
  }
}
```

配置完成后，可以在 MCP 列表上看到 `oeGitExt` 服务，且状态正常。

> 如果出现报错，请根据提示信息检查 python 组件依赖是否满足。

## 3. 功能说明

oeGitExt 提供以下工具函数：

1. `get_my_openeuler_issue()` - 统计我在 openEuler 社区所负责的 issue
2. `get_my_openeuler_project()` - 查找我在 openEuler 社区的项目
3. `get_my_openeuler_pr(repo_type, repo_name)` - 查找我在 openEuler 对应仓库下的 PR
4. `create_openeuler_pr(repo_type, repo_name, title, namespace, source_branch, base, body)` - 在 openEuler 社区仓库创建 PR

## 4. 使用示例

### 查询我的 openEuler issue

```
查询我在openEuler社区负责的issue
```

### 创建 PR

```
在openEuler社区创建PR：
- 仓库类型：src-openeuler 
- 仓库名：kernel 
- 标题：修复内核模块加载问题 
- 命名空间：your_namespace 
- 源分支：new-feature 
- 目标分支：master 
- 描述：版本新特性.. (可选)
```

MCP 会自动处理 PR 创建流程，包括检查源仓库是否存在、获取当前分支信息等。