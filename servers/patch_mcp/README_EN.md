# Patch Spec MCP Server Usage Description

The MCP server used to automatically submit patches can apply patch files to the target repository and automatically update the `.spec` file in the root directory of the repository.

## 1. Environment Setup

Install the Python dependency. For better visualization, the current example uses `uv` to install the dependency in a virtual environment.

```bash
uv pip install pydantic mcp gitpython --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

## 2. MCP Configuration

Configure the MCP server in the Roo Code plugin, edit the MCP configuration file `mcp_settings.json`, and add the following content to `mcpServers`:

```json
{
  "mcpServers": {
    "Automatically submitting the patch and updating the spec file": {
      "command": "uv",
      "args": [
        "--directory",
        "YOUR_PATH/mcp-servers/servers/patch_mcp/src",
        "run",
        "patch_mcp.py"
      ],
      "disabled": false
    }
  }
}
```

After the configuration is complete, you can view `patchMcp` in the MCP list and its status is normal.

> If an error is reported, check whether the Python component dependencies meet the requirements as prompted.

## 3. Function Description

- Copy the patch file to the root directory of the target repository.
- Automatically update the release version number (+1) in the `.spec` file.
- Add a new patch line to the `.spec` file based on the patch classification rules.
- If the `.spec` file uses a command such as `%patch -P1 -p1` to install patches, the command for installing the newly-added patch will be automatically generated in the corresponding part based on the patch classification rules.
- Generate standardized changelog entries.

### apply_patch_to_repo

Apply the patch file to the repository and update the `.spec` file.

**Parameters**

- `repo_path`: target repository path (mandatory).
- `patch_path`: patch file path (mandatory).
- `patch_info`: patch change information, used for changelog (optional).

## 4. Patch Classification Rules

Determine the architecture based on the patch file name and automatically classify the patch to the corresponding part in the `.spec` file. The generated patch number is the largest patch number in this part plus 1.
If the `.spec` file uses a command such as `%patch -P1 -p1` to install patches, the installation command is also placed in the corresponding architecture part.

1. If the patch file name contains "loongarch" or "LoongArch", place it at the end of the `%ifarch loongarch64` part.
2. If the patch file name contains "Sw64", "sw64", or "sw_64", place it at the end of the `%ifarch sw_64` part.
3. Place the non-architecture-specific patch file in the `# patches for all arch` part. If the locator `# patches for all arch` cannot be found, place the patch file at the end of all patch references in the `.spec` file.

## 5. Format of the Generated Changelog

```text
* Tue Dec 3 2024 sxxx <xxxx@xxx.com> - 3.2.0-5
- DESC: high performance
```

## 6. Examples

How to use:

Apply the /home/*xxxx*.patch file to the current branch of the /home/*xx*repo repository.

You can use it together with gitMcp to package patch files in one-click mode, apply it to the artifact repository, and commit the code.

Pack the commit a359*xxx* of the /home/*xx*origin_repo repository into a patch file, name it 323-*xxxx*.patch, save it to the **/home/dev** directory, apply the patch to the specified branch of the /home/*xxx*src_repo repository, and commit all changes to the remote repository.

### Example of the `.spec` File in Scenario 1 Where the Patch Architecture Type Is Not Distinguished

```spec
...
Release:        3

Patch1: 0001-Change-branch-name-for-jemalloc.patch
Patch2: 0002-install-python3-wheel.patch
Patch3: 0003-move-bolt-libraries-to-lib.patch

%changelog

* Wed Mar 19 2025 liyaxxx <412xxxx@qq.com> - 12.3.1-77
- Type:Bugfix
- DESC: Re-enable malloc support below ptr_compression
...
```

In this scenario, the `.spec` file is modified as follows:

1. Release version number + 1:
   Release: 4

2. Add the patch file statement:
   Patch1: 0001-Change-branch-name-for-jemalloc.patch
   Patch2: 0002-install-python3-wheel.patch
   Patch3: 0003-move-bolt-libraries-to-lib.patch
   Patch4: 0004-Change-branch-name-for-gcc-and-AI4C.patch

3. Add the following logs under %changelog:
   %changelog
   * Fri Apr 18 2025 lulixxxx <lulixxxx@xxx.com> - 12.3.1-78
   - DESC: 0004-Change-branch-name-for-gcc-and-AI4C

### Example of the `.spec` File in Scenario 2 Where the Patch Architecture Type Is Distinguished

```spec
...
%global gcc_release 78

Release: %{gcc_release}

# patches for all arch
Patch1: 0001-Version-Set-version-to-12.3.1.patch
Patch2: 0002-RISCV-Backport-inline-subword-atomic-patches.patch
Patch3: 0003-CONFIG-Regenerate-configure-file.patch

# Part 3000 ~ 4999
%ifarch loongarch64
Patch3001: loongarch-add-alternatives-for-idiv-insns-to-improve.patch
Patch3002: loongarch-avoid-unnecessary-sign-extend-after-32-bit.patch
Patch3003: LoongArch-Subdivision-symbol-type-add-SYMBOL_PCREL-s.patch
%endif

# patches for all arch
%patch -P1 -p1
%patch -P2 -p1
%patch -P3 -p1

%ifarch loongarch64
%patch -P3001 -p1
%patch -P3002 -p1
%patch -P3003 -p1
%endif

%changelog

* Wed Mar 19 2025 liyaxxx <412xxxx@qq.com> - 12.3.1-77
- Type:Bugfix
- DESC: Re-enable malloc support below ptr_compression
...
```

In this scenario, the `.spec` file is modified as follows:

1. Release version number + 1: %global gcc_release 79

2. Add the patch file statement and patch file installation command:
   - **If it is a common patch** (0001-all-test.patch):
     - Add the new line `Patch4: 0001-all-test.patch` to the end of the first `# patches for all arch`.
     - Add the new line `%patch -P4 -p1` to the end of the second `# patches for all arch`.

   - **If it is an architecture-specific patch** (0001-loongarch-test.patch):
     - Add the new line `Patch3004: 0001-loongarch-test.patch` before %endif at the end of the first `%ifarch loongarch64`.
     - Add the new line `%patch -P3004 -p1` before %endif at the end of the second `%ifarch loongarch64`.

3. Add the following logs under %changelog:
   %changelog
   * Fri Apr 18 2025 lulixxxx <lulixxxx@xxx.com> - 12.3.1-78
   - DESC: 0001-loongarch-test

## 7. Environment Dependencies

- Python 3.6+
- FastMCP
- pydantic
- GitPython
