# oeGitExt MCP Server 使用说明

oeGitExt 提供了管理 openEuler 社区 issue、repos、PR 和 project 的 MCP 服务

## 1. 环境准备

安装 python 依赖。为了更加直观，当前示例使用 `uv` 安装到虚拟环境：

```bash
uv pip install pydantic mcp requests gitpython --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

确保已安装 oegitext 命令行工具：

```bash
oegitext --version
0.0.1
```

## 2. MCP 配置

在插件 Roo Code 中配置 MCP 服务器，编辑 MCP 配置文件 `mcp_settings.json`，在 `mcpServers` 中新增如下内容：

```json
{
  "mcpServers": {
    "管理openEuler社区的issue,repos,pr,以及我的project": {
      "command": "uv",
      "args": [
        "--directory",
        "YOUR_PATH/mcp-servers/servers/oeGitExt/src",
        "run",
        "oegitext_mcp.py",
        "--token=YOUR_GITEE_TOKEN"
      ],
      "disabled": false,
      "alwaysAllow": [
        "get_my_openeuler_project"
      ]
    }
  }
}
```

> **关于--token参数**：  
> 这是Gitee的私人访问令牌(Personal Access Token)，用于oeGitExt调用Gitee API进行认证。  
> 需要先在Gitee账号设置中创建令牌，并授予repo和user_info权限。  
> 令牌需要保密，不要直接提交到代码仓库中。

配置完成后，可以在 MCP 列表上看到 `oeGitExt` 服务，且状态正常。

> 如果出现报错，请根据提示信息检查 python 组件依赖是否满足。

## 3. 功能说明

oeGitExt 提供以下工具函数：

1. `get_my_openeuler_issue()` - 统计我在 openEuler 社区所负责的 issue
2. `get_my_openeuler_project()` - 查找我在 openEuler 社区的项目
3. `get_my_openeuler_pr(repo_type, repo_name)` - 查找我在 openEuler 对应仓库下的 PR
   - `repo_type`: 仓库属性，有两种：制品仓：src-openeuler，源码仓：openeuler
   - `repo_name`: 仓库名
4. `create_openeuler_pr(repo_type, repo_name, title, namespace, source_branch, base, body)` - 在 openEuler 社区仓库创建 PR
   - `repo_type`: 仓库属性，有两种：制品仓：src-openeuler，源码仓：openeuler
   - `repo_name`: 仓库名。如果未指定，则默认和本地仓库名相同
   - `title`: PR标题
   - `namespace`: Pull Request提交使用的源命名空间(一般是git用户名)
   - `source_branch`: Pull Request提交的源分支
   - `base`: Pull Request提交目标分支的名称
   - `body`: PR描述(可选)

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

## 5. 测试说明

项目包含单元测试，确保功能正确性并达到60%以上的语句覆盖率。

### 运行测试
```bash
cd src
# 使用国内镜像源安装 coverage
pip install coverage -i https://pypi.tuna.tsinghua.edu.cn/simple
coverage run -m unittest test_oegitext_mcp.py
coverage report --show-missing --fail-under=60
```

### 测试覆盖
- 所有工具函数（get_my_openeuler_issue, get_my_openeuler_project, get_my_openeuler_pr, create_openeuler_pr）
- 参数验证和错误处理
- 外部命令执行模拟
- token配置逻辑
