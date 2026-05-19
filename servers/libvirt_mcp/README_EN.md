
# DevStation VM MCP Server Usage Description

## 1. Environment Setup

Install the Python dependency. In this example, `pip` is installed in the **python** directory of the system. It is recommended that `uv` be installed in the virtual environment.

````bash
pip install pydantic mcp requests --trusted-host mirrors.huaweicloud.com -i https://mirrors.huaweicloud.com/repository/pypi/simple
````

Deploy the files required by the DevStation VM MCP Server. Copy the files in the **src** directory to a custom path, for example, **~/.oedp/mcp/**.

```bash
mkdir -p ~/.oedp/mcp/
cp servers/libvirt_mcp/src/* ~/.oedp/mcp/
```

## 2. MCP Configuration

In this example, the VScode development platform is used, and the openEuler Linux environment is connected in remote SSH mode.

The DeepSeek-V3 API is configured in the Roo Code plugin.

Open the MCP configuration page and add the following content to `mcpServers`:

````json
{
  "mcpServers": {

    // ...

    "libvirt_mcp": {
      "command": "python3",
      "args": [
        ".oedp/mcp/libvirt_mcp.py"
      ],
      "disabled": false,
      "alwaysAllow": []
    }
  }
}
````

After the configuration is complete, you can view `libvirt_mcp` in the MCP list and its status is normal.

> Note: If an error is reported, run the `python3 .oedp/mcp/libvirt_mcp.py` command on the local host. If no error is reported and the process is suspended, the startup is normal.

## 3. Command Examples

You can run the following commands to enable AI to perform VM-related operations:

1. Create a VM (named vm2) with 2 vCPUs, 4 GB RAM, and a 20 GB disk, utilizing the template located at **/var/lib/libvirt/images/openEuler-24.03-LTS-SP1-x86_64.qcow2**.

2. Query the IP address of the local vm1 for me.

3. Delete the local vm1 for me.

> Note: The default root password of the QCOW2 VM image provided by openEuler is **openEuler12#$**. Change the password in a timely manner.
