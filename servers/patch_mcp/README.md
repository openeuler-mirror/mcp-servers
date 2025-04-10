# Patch Spec MCP Server 使用说明

用于自动提交补丁的MCP服务器，支持将patch文件应用到目标仓库，并自动更新该仓库根目录下的.spec文件

## 1. 环境准备

安装 python 依赖。为了更加直观，当前示例使用 `uv` 安装到虚拟环境：

```bash
uv pip install pydantic mcp gitpython --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
```

## 2. MCP 配置

在插件 Roo Code 中配置 MCP 服务器，编辑 MCP 配置文件 `mcp_settings.json`，在 `mcpServers` 中新增如下内容：

```json
{
  "mcpServers": {
    "自动提交补丁并更新spec文件": {
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

配置完成后，可以在 MCP 列表上看到 `patchMcp` 服务，且状态正常。

> 如果出现报错，请根据提示信息检查 python 组件依赖是否满足。

## 3. 功能说明

- 将patch文件复制到目标仓库的根目录
- 自动更新.spec文件中的Release版本号(+1)
- 在.spec文件中按照补丁分类规则添加新的Patch行
- 若.spec文件采用`%patch -P1 -p1`这样的命令来安装补丁，也会按照补丁分类规则，自动在对应部分生成安装新添加的补丁的命令
- 生成标准化的changelog条目

### apply_patch_to_repo

将patch文件应用到仓库并更新.spec文件

**参数**:
- `repo_path`: 目标仓库路径(必填)
- `patch_path`: patch文件路径(必填)
- `patch_info`: patch变更信息，用于changelog(可选)

## 4. 补丁分类规则

根据补丁文件名判断其架构，自动分类到.spec文件的对应架构部分，生成的补丁编号在该部分最大的补丁编号基础上+1；
若.spec文件采用`%patch -P1 -p1`这样的命令来安装补丁，安装命令也放到对应的架构部分

1. 如果patch文件名中包含"loongarch"或"LoongArch"字样，则放到`%ifarch loongarch64`部分的最后
2. 如果patch文件名中包含"Sw64"、"sw64"或"sw_64"字样，则放到`%ifarch sw_64`部分的最后
3. 不带特殊架构字样的补丁文件放入`# patches for all arch`部分，如找不到定位符`# patches for all arch`，则放到spec文件内容中所有补丁引用的最后

## 5. 生成的Changelog格式

```text
* Tue Dec 3 2024 sxxx <xxxx@xxx.com> - 3.2.0-5
- DESC: high performance
```

## 6. 使用示例

使用方法：

请把/home/xxxx.patch文件应用到/home/xxrepo仓库的当前分支。

可以结合gitMcp一起使用，一键打包patch文件，并应用到制品仓后提交代码：

请把/home/xxorigin_repo仓库的commit a359xxx打成patch文件，命名为323-xxxx.patch保存到/home/dev目录，把该补丁应用到/home/xxxsrc_repo仓库的指定分支，并提交所有修改到远程仓库。

### 使用场景一 不区分补丁架构类型的spec文件示例

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

该场景下，补丁应用对spec文件的修改如下：

1. Release版本号+1： 
   Release:        4

2. 添加补丁文件的声明：
   Patch1: 0001-Change-branch-name-for-jemalloc.patch
   Patch2: 0002-install-python3-wheel.patch
   Patch3: 0003-move-bolt-libraries-to-lib.patch
   Patch4: 0004-Change-branch-name-for-gcc-and-AI4C.patch

3. 在%changelog下新增日志：
   %changelog
   * Fri Apr 18 2025 lulixxxx <lulixxxx@xxx.com> - 12.3.1-78
   - DESC: 0004-Change-branch-name-for-gcc-and-AI4C

### 使用场景二 按照架构区分补丁的spec文件示例

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

该场景下，补丁应用对spec文件的修改如下：

1. Release版本号+1： %global gcc_release 79

2. 添加补丁文件的声明及补丁文件安装命令：
   - **如果是通用补丁** (0001-all-test.patch):
     - 在第一个`# patches for all arch`的尾部加入新行`Patch4: 0001-all-test.patch`
     - 在第二个`# patches for all arch`的尾部加入新行`%patch -P4 -p1`

   - **如果是架构特定补丁** (0001-loongarch-test.patch):
     - 在第一个`%ifarch loongarch64`的尾部，%endif之前，加入新行`Patch3004: 0001-loongarch-test.patch`
     - 在第二个`%ifarch loongarch64`的尾部，%endif之前，加入新行`%patch -P3004 -p1`

3. 在%changelog下新增日志：
   %changelog
   * Fri Apr 18 2025 lulixxxx <lulixxxx@xxx.com> - 12.3.1-78
   - DESC: 0001-loongarch-test

## 7. 依赖环境

- Python 3.6+
- FastMCP
- pydantic
- GitPython