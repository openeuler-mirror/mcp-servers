# oeGitExt MCP Server Usage Guide

oeGitExt provides the MCP service for managing issues, repos, PRs, and projects in the openEuler community.

## 1. Environment Setup

Install the Python dependency. For better visualization, the current example uses `uv` to install the dependency in a virtual environment.

```bash
uv pip install pydantic mcp requests gitpython --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

Ensure that the oegitext command line tool has been installed.

```bash
oegitext --version
0.0.1
```

## 2. MCP Configuration

Configure the MCP server in the Roo Code plugin, edit the MCP configuration file `mcp_settings.json`, and add the following content to `mcpServers`:

```json
{
  "mcpServers": {
    "Manage issues, repos, PRs, and my projects in the openEuler community": {
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

> **About the --token Parameter:** 
> This is the personal access token of Gitee, which is used by oeGitExt to call the Gitee API for authentication. 
> You need to create a token in the Gitee account settings and grant it the repo and user_info permissions. 
> The token must be kept confidential and should not be directly committed to the code repository.

After the configuration is complete, you can view `oeGitExt` in the MCP list and its status is normal.

> If an error is reported, check whether the Python component dependencies meet the requirements as prompted.

## 3. Function Description

oeGitExt provides the following tool functions:

1. `get_my_openeuler_issue()` - Collect statistics on the issues I am responsible for in the openEuler community.
2. `get_my_openeuler_project()` - Search for my projects in the openEuler community.
3. `get_my_openeuler_pr(repo_type, repo_name)` - Search for my PRs in the corresponding repository in the openEuler community.
   - `repo_type`: repository attribute. The value can be src-openeuler (artifact repository) or openeuler (source repository).
   - `repo_name`: repository name
4. `create_openeuler_pr(repo_type, repo_name, title, namespace, source_branch, base, body)` - Create a PR in the openEuler community repository.
   - <idp:inline displayname="code" id="code8579151017309">repo_type</idp:inline>: repository attribute. The value can be src-openeuler (artifact repository) or openeuler (source repository).
   - `repo_name`: repository name If not specified, the value is the same as the local repository name by default.
   - `title`: PR title
   - `namespace`: source namespace (generally the Git user name) used for submitting the pull request
   - `source_branch`: source branch submitted by the pull request
   - `base`: name of the target branch to which the pull request is submitted
   - `body`: PR description (optional)

## 4. Examples

### Querying My openEuler Issues

```text
Query issues that I am responsible for in the openEuler community.
```

### Creating a PR

```text
Create a PR in the openEuler community.
- Repository type: src-openeuler
- Repository name: kernel
- Title: Fixing the kernel module loading issue
- Namespace: your_namespace
- Source branch: new-feature
- Target branch: master
- Description: new features of the version (optional)
```

## 5. Test Notes

The project includes unit tests to ensure the correctness of functions and achieve a statement coverage rate of over 60%.

### Running Test

```bash
cd src
# Use the image source in China to install the coverage.
pip install coverage -i https://pypi.tuna.tsinghua.edu.cn/simple
coverage run -m unittest test_oegitext_mcp.py
coverage report --show-missing --fail-under=60
```

### Test Coverage

- All tool functions (get_my_openeuler_issue, get_my_openeuler_project, get_my_openeuler_pr, create_openeuler_pr)
- Parameter verification and error handling
- External command execution simulation
- Token configuration logic
