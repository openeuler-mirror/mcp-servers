# patch-analyzer-mcp

## Introduction

The backporting analysis agent automatically pulls the code from the upstream community to generate patches, analyzes the patch content to generate Excel files, reads the approved Excel files, submits the files to the destination repository by module, and creates web page merge requests (MRs).

## Restrictions

Currently, only one upstream community code repository can be tracked. Multiple upstream repositories cannot be tracked at the same time.

## Software Architecture

FastMCP and GitPython packages that depend on Python
Python version: 3.10 or later

## Installation

1. Download the conda management tool from `wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh`.
2. conda create --name mcp-server python=3.10
3. After entering the conda environment, install pip install fastmcp and gitpython.
4. xxxx
5. xxxx

## Instructions

Usage of the MCP server:

1. Modify the **src/assistant.conf** file.

    | Parameter                 | Configuration Description                                          |
    |----------------------|----------------------------------------------------|
    | kernel_src_url       | Upstream code repository address of the kernel software                       |
    | kernel_src_url_proxy | Upstream code repository proxy of the kernel software, which affects the commit_id column in the Excel file.|
    | kernel_commitID      | The upstream code repository of the kernel software starts analysis from the specified commit ID.   |
    | kernel_src_branch    | Branch of the upstream code repository of the kernel software                    |
    | kernel_dst_branch    | Branch of the destination code repository of the kernel software                    |
    | kernel_dst_url       | Upstream code repository address of the kernel software                      |
    | kernel_project_url   | Address to which the creation web MRs are sent                          |
    | kernel_project_token | Key of creating web MRs   |                          |
    | kernel_mr_server     | Name of the server for creating a web MR (Currently, MRs in Sangfor and Gitee formats are supported.)|

    Note: To add the configuration of the OpenSSL software, copy the preceding fields and replace kernel with openssl. For example:
    kernel_src_url       ->  openssl_src_url
    kernel_src_url_proxy -> openssl_src_url_proxy
    The rule applies to other configurations.

2. python3 patch_assistant starts the MCP server. By default, the 0.0.0.0:8100 port is listened.

---------------------------------------------------------------
 **Usage of the MCP server:**

To use the agent client independently, perform the following steps:

1. Modify the **src/assistant.conf** file.

    | Parameter                  | Configuration Description                                          |
    |----------------------|------------------------------------------------|
    | api_key              | llm api_key. If there is no llm api_key, enter **EMPTY**.                        |
    | base_url             | llm base_url                                   |
    | model_name           | LLM model name                                       |
    | temperature          | LLM model temperature, which is used to adjust the stability and creativity of the LLM output. The output is more stable when the value ranges from 0.1 to 0.3.              |
    | top_p                | llm top_p, which is used to adjust the stability of the LLM output. The output is more stable when the value ranges from 0.7 to 0.9.            |
    | mcp_server_ip        | IP address of the MCP server                               |
    | mcp_server_port      | MCP server port                             |
    | patch_excel_gen_path | Path for generating the patch analysis result in Excel file. The file name is in the format of software-timestamp.xlsx.            |
    | patch_excel_path     | Complete path of the Excel file imported during backporting                          |
    | sse_read_timeout     | Timeout interval for no data response from the SSE server, in seconds. Set this parameter based on the maximum running duration of the synchronized code block on the server. You can increase the value as required.|

    Set model-related parameters based on the local LLM model or online LLM model. For other parameters, set them based on the local MCP server and local disk path.
2. python client/mcp_client.py starts the process and enters the execution for interaction as prompted. The agent selects software based on the list provided in software_list. The **software patch analysis and backporting** commands are supported.
3. After the software patch analysis is complete, an Excel file will be generated for manual review by the architect. The "Confirm Merge" (only **Yes/No** can be entered) and "Reason for Confirmation" fields in the Excel file must be filled in. If these fields are left blank, the backporting will fail.
4. Before performing the "Backporting" operation, upload the reviewed Excel file by following step 2. Wait for the agent to return the result. If a patch conflict occurs, manually review and resolve the issue.

How to use the client to access the Roo Code:

1. Modify the **client/client.conf** file in the same way.
2. python3 patch_assistant.py starts the MCP server. By default, the 0.0.0.0:8100 port is listened.
3. Configure the **client/mcp_config.json** file to listen to port 8100 of the client in the Roo Code.

    ```text
    {
      "mcpServers": {# label name, which is fixed.
        "patch_analyse": { # MCP server name
          "type": "streamable-http", # MCP connection mode, which is fixed.
          "url": "http://0.0.0.0:8100/mcp", #MCP client URL
          "disabled": false,
          "timeout": 3600, # timeout interval
          "alwaysAllow": [ 
          ] # always-on interface, which can be left empty
        }
      }
    }
    ```

4. Customize prompts in the Roo Code based on the LLM effect.
5. Perform Q&A in the Roo Code.
