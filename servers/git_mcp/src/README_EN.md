# gitMcp MCP Server Usage Guide

gitMcp provides MCP services related to Git operations, including repository management, branch operations, commit and push, and difference comparison.

## 1. Environment Setup

### 1.1 Installing Dependencies for Python

You are advised to use `uv` to install it in a virtual environment.

```bash
sudo pip3 install uv --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

Install other necessary dependencies:

```bash
sudo pip install pydantic mcp gitpython inquirer --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

### 1.2 Configuring Git Authentication

Ensure that Git has been installed, user authentication information has been configured, and you have the permission to push codes.

If SSH key authentication is used, you are advised to add the following configuration to avoid interactive confirmation during the first connection:

Add the following to **~/.ssh/config** (gitee.com is used as an example):

```plaintext
Host gitee.com
    StrictHostKeyChecking no
    UserKnownHostsFile=/dev/null
```

## 2. MCP Configuration

In this example, the VS Code development platform is used, and the DeepSeek-V3 API is configured in the Roo Code plugin.

Open the MCP configuration page, edit the MCP configuration file `mcp_settings.json`, and add the following content to `mcpServers`:

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

After the configuration is complete, you can view the `gitMcp` service in the MCP list.

## 3. Function Description

gitMcp provides the following tool functions:

### Basic Operations

1. `git_status(repo_path)` - Obtain the Git repository status.
   - repo_path: repository path

2. `git_init(repo_path)` - Initialize the Git repository.
    - repo_path: repository path

3. `add_remote(remote_name, remote_url, repo_path)` - Add a remote Git repository.
    - remote_name: remote repository name (mandatory)
    - remote_url: remote repository URL (mandatory)
    - repo_path: repository path (optional)

4. `git_pull(repo_path, remote_name, branch_name)` - Pull code from a remote repository.
    - repo_path: repository path (optional)
    - remote_name: remote name (optional; "origin" by default)
    - branch_name: branch name (optional; current branch by default)

5. `get_git_config(repo_path)` - Obtain Git user configuration.
   - repo_path: repository path

### Commit Management

1. `add_commit_and_push(commit_message, user_name, user_email, repo_path, files)` - Add, commit, and push changes.
   - commit_message: commit message (optional; "auto commit" by default)
   - user_name: Git username (optional)
   - user_email: Git email address (optional)
   - repo_path: repository path (optional)
   - files: list of files to be added (optional; if not specified, all changes will be added)

2. `git_diff_unstaged(repo_path)` - View un-staged changes.
   - repo_path: repository path

3. `git_diff_staged(repo_path)` - View staged changes.
   - repo_path: repository path

4. `git_diff(repo_path, target)` - Compare branches or commits.
   - repo_path: repository path (mandatory)
   - target: target branch or commit to compare (mandatory)

5. `git_reset(repo_path)` - Reset the staging area.
    - repo_path: repository path

6. `git_show(repo_path, revision)` - View commit details.
    - repo_path: repository path (mandatory)
    - revision: commit hash or branch name (mandatory)

### Branch Management

1. `create_branch(branch_name, repo_path)` - Create a branch.
    - branch_name: new branch name (mandatory)
    - repo_path: repository path (optional)

2. `list_branches(repo_path)` - List all branches.
    - repo_path: repository path (optional)

### Patch Management

1. `cherry_pick_to_patch(repo_path, commit_hash, patch_path, patch_filename)` - Generate a patch file for a specified commit.
    - repo_path: repository path (mandatory)
    - commit_hash: commit hash of the patch to be generated (mandatory)
    - patch_path: path of the generated patch file (optional; the current directory is used by default.)
    - patch_filename: patch file name (excluding the file name extension) (optional)

## 4. Examples

### Creating a Branch and Committing Changes

```text
Creating a Branch Named feature/new-feature
Add files file1.txt and file2.txt.
Commit the message "Implement new functions".
```

### Viewing the Repository Status and Differences

```text
Viewing the Current Repository Status
View un-staged changes.
View the differences with the main branch.
```

### Committing Files Selectively

```text
Commit only the **src/main.py** and **src/utils.py** files.
Commit the message "Optimize core functions".
```

### Committing All Current Changes to the Remote Repository

```text
Commit and push all changes of the current branch in the local repository.
```

### Viewing the Commit History

```text
View the latest five commit records.
View the details of a specific commit.
```

### Generating a Patch File for a Specified Commit

Specify the file name and save the directory:

```text
Pack the commit a359*xxxx* of the /home/*xx*repo repository into a patch file, name it *xxx*.patch, and save it to the **/*xx*** directory.
```

Do not specify the file name. Use the default file name 0001-< commit message title >.patch generated by git format-patch. The file is saved to the current directory by default.

```text
Pack the commit a359*xxxx* of the /home/xxrepo repository into a patch file.
```
