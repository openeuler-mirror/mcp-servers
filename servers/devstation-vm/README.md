

# DevStation VM MCP Server 使用说明

## 1. 环境准备

安装 python 依赖。为了更加直观，当前示例使用 `pip` 安装到系统的 python 目录，实际上更加推荐 `uv` 安装到虚拟环境。

````bash
pip install pydantic mcp requests --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
````

部署 DevStation VM MCP Server 所需文件，将 src 目录下的文件拷贝到自定义路径，例如：~/.oedp/mcp/

```bash
mkdir -p ~/.oedp/mcp/
cp servers/devstation-vm/src/* ~/.oedp/mcp/
```

## 2. MCP 配置

当前示例使用 VScode 开发平台，用 Remote ssh 连接到一个 openEuler 的 linux 环境。

在插件 Roo Code中配置了 DeepSeek-V3 的API。

打开 MCP 配置页面，在 `mcpServers` 中新增如下内容：

````json
{
  "mcpServers": {

    // ...

    "vm-tool": {
      "command": "python3",
      "args": [
        ".oedp/mcp/vm-tool.py"
      ],
      "disabled": false,
      "alwaysAllow": []
    }
  }
}
````

配置完成后，可以在 MCP 列表上看看到 `vm-tool`，且状态正常。

> 提示：如果出现报错，可以尝试执行在本地执行`python3 .oedp/mcp/vm-tool.py`来测试，无报错且进程挂起则说明启动正常。

## 3. 指令示例

你可以尝试如下指令，让AI帮你完成虚拟机的相关操作：

1. 请帮我创建一个2U4G20G的虚拟机，名为vm2，虚拟机模板为/var/lib/libvirt/images/openEuler-24.03-LTS-SP1-x86_64.qcow2

2. 请帮我查询本地的虚拟机vm1的IP

3. 请帮我删除本地的虚拟机vm1

> 提示：openEuler 官方提供的 qcow2 虚拟机镜像的 root 密码默认为 openEuler12#$，请及时修改。
