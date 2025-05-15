# ccbMcp MCP Server 使用说明

ccbMcp 提供了管理 EulerMaker 构建系统的 MCP 服务，支持工程管理、构建任务管理、软件包下载等功能。

## 1. 环境准备

安装 Python 依赖：

```bash
uv pip install pydantic pyyaml --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

安装 ccb 命令行工具:

```
    git clone https://gitee.com/openeuler-customization/lkp-tests.git
    cd lkp-tests
    make install
    source ~/.${SHELL##*/}rc
```

确保以下命令可以执行：

```bash
ccb -h
```

## 2. MCP 配置

在插件 Roo Code 中配置 MCP 服务器，编辑 MCP 配置文件 `mcp_settings.json`，在 `mcpServers` 中新增如下内容，以对接 EulerMaker 社区环境的配置为例：

```json
{
  "mcpServers": {
    "ccbMcp": {
      "command": "python3",
      "args": [
        "/opt/mcp-servers/servers/ccb_mcp/src/ccb_mcp.py",
        "--HOME_DIR=${your_home_directory}",
        "--SRV_HTTP_REPOSITORIES_HOST=123.249.10.3",
        "--SRV_HTTP_REPOSITORIES_PORT=30108",
        "--SRV_HTTP_REPOSITORIES_PROTOCOL=http://",
        "--SRV_HTTP_RESULT_PROTOCOL=http://",
        "--SRV_HTTP_RESULT_HOST=123.249.10.3",
        "--SRV_HTTP_RESULT_PORT=30108",
        "--DAG_HOST=123.249.10.3",
        "--DAG_PORT=30108",
        "--GATEWAY_IP=123.249.10.3",
        "--GATEWAY_PORT=30108",
        "--GITEE_ID=${your_gitee_id}",
        "--GITEE_PASSWORD=${your_gitee_password}",
        "--ACCOUNT=${your_account}",
        "--PASSWORD=${your_password}",
        "--OAUTH_TOKEN_URL=https://omapi.osinfra.cn/oneid/oidc/token",
        "--OAUTH_REDIRECT_URL=https://eulermaker.compass-ci.openeuler.openatom.cn/oauth/",
        "--PUBLIC_KEY_URL=https://omapi.osinfra.cn/oneid/public/key?community=openeuler"
      ],
      "disabled": false
    }
  }
}
```
参数说明：HOME_DIR为环境上环境变量中的家目录，必填；网关GATEWAY_IP和GATEWAY_PORT必须配置; gitee账号GITEE_ID和GITEE_PASSWORD若不配置只能执行游客可执行的命令; SRV_HTTP_RESULT_HOST，SRV_HTTP_RESULT_PORT是存储job日志的微服务，和SRV_HTTP_RESULT_PROTOCOL仅用于ccb log子命令；SRV_HTTP_REPOSITORIES_HOST和SRV_HTTP_REPOSITORIES_PORT是repo源，和SRV_HTTP_REPOSITORIES_PROTOCOL仅用于ccb download子命令，若无下载需求，可以不配置。

## 3. 功能说明

ccbMcp 提供以下工具函数：

1. `select_projects(os_project, owner, fields, sort)` - 查询EulerMaker中的工程信息
2. `select_snapshots(os_project, snapshot_id, fields, sort)` - 查询指定工程的所有快照
3. `select_builds(build_id, os_project, fields)` - 查询EulerMaker中的构建任务
4. `create_project(project_name, json_config, description, spec_name, spec_url, spec_branch, os_variant, architecture)` - 创建EulerMaker工程
5. `update_project(project_name, json_config, package_name, package_url, package_branch, users_to_remove, users_to_add)` - 更新EulerMaker工程
6. `set_package_lock(project_name, package_name, action)` - 设置包的锁定状态
7. `build_single_package(os_project, package_name, json_config, os_variant, architecture)` - 执行单包构建，返回构建结果URL
8. `build(build_type, os_project, snapshot_id, build_targets, os_variant, architecture)` - 执行全量或增量构建，返回构建结果URL
9. `download_package(os_project, snapshot_id, packages, architecture, dest, source, debug, subpackages)` - 下载软件包
10. `cancel(build_id)` - 取消构建任务
11. `log(job_id)` - 查看job日志

## 4. 使用示例

### 4.1 核心场景

#### 创建工程

```
创建名为test-project的工程：
- 包名：gcc
- 包URL：https://gitee.com/src-openeuler/gcc.git
- 分支：master
- 构建环境：openEuler:24.03-LTS-SP1
- 架构：x86_64
```

#### 更新工程

```
向test-project工程添加以下包，每行信息分别为包名，url，分支名：
- gcc-for-openEuler，https://gitee.com/openeuler/gcc-for-openEuler.git，master
- fstrm，https://gitee.com/src-openeuler/fstrm.git，openEuler-20.03-LTS

同时添加用户权限：
- 添加用户：user1，角色：maintainer
- 删除用户：user2
```

#### 执行构建

```
全量构建test-project工程

或基于快照ce4e7a42-3167-11f0-bae2-02291c731353增量构建
```

#### 单包构建

```
构建test-project工程的python-flask包：
- 构建环境：openEuler:24.03-LTS-SP1
- 架构：x86_64,aarch64
```

#### 下载软件包

```
下载test-project工程的gcc包：
- 架构：aarch64
- 保存路径：/tmp/rpms
```

### 4.2 普通场景

#### 查询工程信息

```
查询test-project工程信息：
- 返回字段：os_project,users
- 排序：create_time:desc

查询所有owner为user1的工程
```

#### 查询快照

```
查询test-project工程的所有快照：
- 排序：create_time:desc

查询特定快照ID的详细信息
```

#### 查询构建任务

```
查询test-project工程的所有构建任务：
- 返回字段：build_id,build_type

查询特定构建ID的详细信息
```

#### 设置包锁定状态

```
锁定test-project工程的gcc包：
- 包名：gcc
- 操作：lock

解锁test-project工程的gcc包：
- 包名：gcc
- 操作：unlock
```

#### 取消构建

```
取消构建任务：
- 构建ID：cfa874d6-2f11-11f0-a00b-eaafa4f3ec35
```

#### 查看日志

```
查看job日志：
- job ID：cbs.67890
