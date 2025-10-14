# patch-analyzer-mcp

#### 介绍
补丁回合分析智能体，具有自动拉取上游社区代码生成补丁，分析补丁内容生成excel文件，读取审核后的excel文件按照模块粒度提交到目的仓并创建网页MR合并请求。

#### 限制
目前只支持跟踪一个上游社区代码仓，不支持同时跟踪多个上游仓

#### 软件架构
依赖python的fastmcp,gitpython包
要求python>=3.10


#### 安装教程

1. wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh  下载conda管理工具
2. conda create --name mcp-server python=3.10
3. 进入conda环境后安装依赖 pip install fastmcp, gitpython
4.  xxxx
5.  xxxx

#### 使用说明

mcp server服务端使用方式：
1. 修改src/assistant.conf文件

| 参数                  | 配置说明                                           |
|----------------------|----------------------------------------------------|
| kernel_src_url       | "kernel"软件的上游代码仓地址                        |
| kernel_src_url_proxy | "kernel"软件的上游代码仓代理，影响excel的commit_id列|
| kernel_commitID      | "kernel"软件的上游代码仓从指定commitID处开始分析    |
| kernel_src_branch    | "kernel"软件的上游代码仓的分支                     |
| kernel_dst_branch    | "kernel"软件的目的代码仓的分支                     |
| kernel_dst_url       | "kernel"软件的上游代码仓地址                       |
| kernel_project_url   | 创建web MR请求的发送地址                           |
| kernel_project_token | 创建web MR请求的密钥    |                          |
| kernel_mr_server     | 创建web MR的服务器名(目前支持sangfor和gitee格式的MR)|

特殊说明：如果要增加openssl软件的配置，复制新增上述字段并将替换"kernel"字段为"openssl"即可，如：
kernel_src_url       -》 openssl_src_url
kernel_src_url_proxy -》 openssl_src_url_proxy
依次类推

2. python3 patch_assistant 拉起mcp server服务即可，默认会监听0.0.0.0:8100端口

---------------------------------------------------------------
 **mcp server客户端使用方式：** 

独立使用agent client客户端使用方式：
1. 修改src/assistant.conf文件

| 参数                   | 配置说明                                           |
|----------------------|------------------------------------------------|
| api_key              | llm api_key,若无填“EMPTY”                         |
| base_url             | llm base_url                                   |
| model_name           | llm 模型名                                        |
| temperature          | llm 模型温度，调节llm输出稳定性和创造性，0.1~0.3输出结果更加稳定               |
| top_p                | llm top_p，调节llm输出稳定性，0.7~0.9输出结果更加稳定             |
| mcp_server_ip        | mcp server服务端ip                                |
| mcp_server_port      | mcp server服务端port                              |
| patch_excel_gen_path | 补丁分析结果excel生成的路径，文件名会是 软件-时间戳.xlsx             |
| patch_excel_path     | 补丁回合导入的excel文件完整路径信息                           |
| sse_read_timeout     | sse服务端无数据响应超时时间，单位：s，根据服务端最长同步代码块运行时长设置，可以适当调大 |

按照本地llm模型或者线上llm模型设置模型相关参数，其他按照本地mcp server服务端，本地磁盘路径设置；
2. python client/mcp_client.py 拉起进程，根据程序提示交互输入执行的执行，agent按照software_list提供的列表提示选择软件进行操作，支持 **“软件补丁分析”、“补丁回合”** 两个指令；
3. 完成“软件补丁分析”后，将输出excel供架构师人工审核，需要回填excel中“确认合入”（仅可填 “ **是/否** ” ）、“确认理由”，此两项为必填项，若空缺将导致补丁回合步骤失败；
4. 执行“补丁回合”前需要上传评审后的excel文件，按照步骤2执行，等待agent返回结果，若出现补丁冲突问题，需要人工检视修复；


客户端接入roo code使用方式：
1. 同样的方式修改client/client.conf文件；
2. python3 patch_assistant.py 拉起mcp server服务即可，默认会监听0.0.0.0:8100端口
2. 配置client/mcp_config.json，在roo code里监听客户端8100端口；

```
{
  "mcpServers": { #标签名，固定
    "patch_analyse": { # mcp server名称
      "type": "streamable-http", # 连接mcp方式，固定
      "url": "http://0.0.0.0:8100/mcp", #mcp 客户端 url
      "disabled": false,
      "timeout": 3600, # 超时时间
      "alwaysAllow": [ 
      ] # 常开的接口，置空就可以
    }
  }
}
```

3. 配置roo code中自定义prompt,看情况根据llm效果来；
4. roo code中进行问答；
