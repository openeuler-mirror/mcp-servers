# ccbMcp MCP Server

The **ccbMcp** service provides MCP-based management capabilities for the EulerMaker build system, supporting project management, build task management, package downloads, and more.

## 1. Environment Preparation

Install Python dependencies:

```bash
uv pip install pydantic pyyaml --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

Install the **ccb** command-line tool:

Use the openEuler community repository for openEuler-24.03-LTS-SP2 or later and install ccb:

```bash
yum install ccb
```

Verify that the command works:

```bash
ccb -h
```

## 2. MCP Configuration

Configure the MCP server in the **Roo Code** plugin. Edit the MCP configuration file `mcp_settings.json` and add the following entry under `mcpServers`. The example below connects to the EulerMaker community environment:

```json
{
  "mcpServers": {
    "ccbMcp": {
      "command": "python3",
      "args": [
        "/opt/mcp-servers/servers/ccb_mcp/src/ccb_mcp.py",
        "--HOME_DIR=${your_home_directory}",
        "--SRV_HTTP_REPOSITORIES_HOST=eulermaker.compass-ci.openeuler.openatom.cn",
        "--SRV_HTTP_REPOSITORIES_PORT=443",
        "--SRV_HTTP_REPOSITORIES_PROTOCOL=https://",
        "--SRV_HTTP_RESULT_PROTOCOL=https://",
        "--SRV_HTTP_RESULT_HOST=eulermaker.compass-ci.openeuler.openatom.cn",
        "--SRV_HTTP_RESULT_PORT=443",
        "--DAG_HOST=eulermaker.compass-ci.openeuler.openatom.cn",
        "--DAG_PORT=443",
        "--GATEWAY_IP=eulermaker.compass-ci.openeuler.openatom.cn",
        "--GATEWAY_PORT=443",
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

### Parameter Notes

- **HOME_DIR**: Required. Must be set to the user's home directory.
- **GATEWAY_IP / GATEWAY_PORT**: Required.
- **GITEE_ID / GITEE_PASSWORD**: Optional. Without them, only guest-level commands can be executed.
- **SRV_HTTP_RESULT_HOST / SRV_HTTP_RESULT_PORT / SRV_HTTP_RESULT_PROTOCOL**: Used only for the `ccb log` command (job log service).
- **SRV_HTTP_REPOSITORIES_HOST / SRV_HTTP_REPOSITORIES_PORT / SRV_HTTP_REPOSITORIES_PROTOCOL**: Used only for the `ccb download` command. If downloads are not needed, these can be omitted.

## 3. Function Overview

ccbMcp provides the following tool functions:

1. `select_projects(os_project, owner, fields, sort)` - Query project information in EulerMaker.
2. `select_snapshots(os_project, snapshot_id, fields, sort)` - Query all snapshots of a project.
3. `select_builds(build_id, os_project, fields)` - Query build tasks in EulerMaker.
4. `create_project(project_name, json_config, description, spec_name, spec_url, spec_branch, os_variant, architecture)` - Create a EulerMaker project.
5. `update_project(project_name, json_config, package_name, package_url, package_branch, users_to_remove, users_to_add)` - Update a EulerMaker project.
6. `set_package_lock(project_name, package_name, action)` - Lock or unlock a package.
7. `build_single_package(os_project, package_name, json_config, os_variant, architecture)` - Build a single package and return the build result URL.
8. `build(build_type, os_project, snapshot_id, build_targets, os_variant, architecture)` - Perform a full or incremental build and return the build result URL.
9. `download_package(os_project, snapshot_id, packages, architecture, dest, source, debug, subpackages)` - Download packages.
10. `cancel(build_id)` - Cancel a build task.
11. `log(job_id)` - View job logs.

## 4. Usage Examples

### 4.1 Core Scenarios

#### Create a Project

```bash
Create a project named test-project:
- Package name: gcc
- Package URL: https://gitee.com/src-openeuler/gcc.git
- Branch: master
- Build environment: openEuler:24.03-LTS-SP1
- Architecture: x86_64
```

#### Update a Project

```bash
Add the following packages to test-project (each line of information is in the format of package name, URL, branch name):
- gcc-for-openEuler, https://gitee.com/openeuler/gcc-for-openEuler.git, master
- fstrm, https://gitee.com/src-openeuler/fstrm.git, openEuler-20.03-LTS

Modify user permissions:
- Add user: user1, role: maintainer
- Delete user: user2
```

#### Execute a Build

```bash
Perform a full build of test-project.

Or perform an incremental build based on snapshot ce4e7a42-3167-11f0-bae2-02291c731353
```

#### Build a Single Package

```bash
Build the python-flask package in test-project:
- Build environment: openEuler:24.03-LTS-SP1
- Architectures: x86_64, aarch64
```

#### Download Packages

```bash
Download the gcc package from test-project:
- Architecture: aarch64
- Save path: /tmp/rpms
```

### 4.2 General Scenarios

#### Query Project Information

```bash
Query test-project information:
- Return fields: os_project, users
- Sort: create_time:desc

Query all projects owned by user1.
```

#### Query Snapshots

```bash
Query all snapshots of test-project:
- Sort: create_time:desc

Query details of a specific snapshot ID.
```

#### Query Build Tasks

```bash
Query all build tasks of test-project:
- Return fields: build_id,build_type

Query details of a specific build ID.
```

#### Lock or Unlock a Package

```bash
Lock the gcc package in test-project:
- Package name: gcc
- Action: lock

Unlock the gcc package in test-project:
- Package name: gcc
- Action: unlock
```

#### Cancel a Build

```bash
Cancel a build task:
- Build ID: cfa874d6-2f11-11f0-a00b-eaafa4f3ec35
```

#### View Logs

```bash
View job logs:
- Job ID: cbs.67890

```
