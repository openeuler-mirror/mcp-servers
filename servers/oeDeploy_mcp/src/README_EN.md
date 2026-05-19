# oeDeploy MCP Server `mcp-oedp` Usage Description

The MCP server helps users intelligently call oeDeploy capabilities to quickly deploy software.

## 1. Environment Setup (Skip This Step If mcp-servers-oeDeploy Has Been Installed)

Download the oeDeploy code and copy the `oeDeploy/oedp-mcp/mcp-oedp` directory to a custom path, for example, `~/.oedp/mcp/`.

```bash
git clone https://gitee.com/openeuler/oeDeploy.git
mkdir -p ~/.oedp/mcp/
cp -r oeDeploy/oedp-mcp/mcp-oedp ~/.oedp/mcp/
```

Configure the Python virtual environment, go to the `mcp-oedp` directory, initialize `uv`, and install dependencies.

```bash
cd ~/.oedp/mcp/mcp-oedp
uv venv --system-site-packages
uv pip install -e .
```

## 2. MCP Configuration

Ensure that your intelligent agent application (interaction interface) supports the MCP service, such as Roo Code and Cherry Studio.

Open the MCP configuration page for manual configuration, or directly edit the MCP configuration file. You need to configure the access address `model_url`, key `api_key`, and model name `model_name` of the LLM API for the MCP Server to process relatively complex operations. If the LLM API is unavailable, some functions will be restricted. You can obtain API information from the official websites of model service providers such as DeepSeek and SiliconFlow.

For example, if you use the official API of DeepSeek, refer to the following configuration:

````json
{
  "mcpServers": {
    "mcp-oedp": {
      "command": "uv",
      "args": [
        "--directory", "~/.oedp/mcp/", // Enter the uv initialization path (path where mcp-oedp.py is located) based on your actual situation.
        "run", "mcp-oedp.py",
        "--model_url", "https://api.deepseek.com",
        "--api_key", "<--DeepSeek key-->",
        "--model_name", "deepseek-chat"
      ],
      "disabled": false,
      "timeout": 1800
    }
  }
}
````

After the configuration is complete, you can view `mcp-oedp` in the MCP list and its status is normal.

> If the MCP server status is abnormal, check whether the Python component dependencies meet the requirements as prompted.

## 3. One-Click Deployment Using Natural Languages

After the oeDeploy plugin is developed, let's use AI to complete one-click deployment of kubernetes-1.31.1. Prepare three Linux nodes that can communicate with each other at Layer 3.

Create a dialog box in Roo Code and send the following commands:

```text
Use oeDeploy to deploy kubernetes-1.31.1 in one click.
The IP address of the master node is 192.168.0.10, the root password is *xxxxxxxx*, the architecture is amd64, and the oe version is 24.03-LTS.
The IP address of the first worker node is 192.168.0.11, the root password is *xxxxxxxx*, the architecture is amd64, and the oe version is 24.03-LTS.
The IP address of the second worker node is 192.168.0.12, the root password is *xxxxxxxx*, the architecture is amd64, and the oe version is 24.03-LTS.
```

MCP will enable the LLM to automatically initialize the oeDeploy plugin, configure parameters, and perform the final deployment.
