单http部署:  rooCode(IDE)--http--patch_assistant(:8100)                      

#### 使用说明
1.修改配置文件assistant.conf配置项目

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
| api_key              | llm api_key,若无填“EMPTY”                         |
| base_url             | llm base_url                                   |
| model_name           | llm 模型名                                        |
| temperature          | llm 模型温度，调节llm输出稳定性和创造性，0.1~0.3输出结果更加稳定               |
| top_p                | llm top_p，调节llm输出稳定性，0.7~0.9输出结果更加稳定             |
| timeout              | llm 模型调用超时时间                                        |
| max_workers          | 调用llm的并发数                                        |
| patch_excel_gen_path | 补丁分析结果excel生成的路径，文件名会是 软件-时间戳.xlsx             |
| judge_rules          | 自定义的检视规则                                        |

特殊说明：如果要增加openssl软件的配置，复制新增上述字段并将替换"kernel"字段为"openssl"即可，如：
kernel_src_url       -》 openssl_src_url
kernel_src_url_proxy -》 openssl_src_url_proxy
依次类推

2.python3 patch_assistant.py启动服务，默认监听:8100端口

3.客户端接入roo code
```
{
  "mcpServers": { #标签名，固定
    "patch_analyse": { # mcp server名称
      "type": "streamable-http", # 连接mcp方式，固定
      "url": "http://0.0.0.0:8100/mcp", #mcp 客户端 url
      "headers": {
          "Authorization": "Bearer sk-1234" #用户独立的token，配置这个值可以隔离用户间的参数
      },
      "disabled": false,
      "timeout": 3600, # 超时时间
      "alwaysAllow": [ 
      ] # 常开的接口，置空就可以
    }
  }
}
```

4. 配置roo code中自定义prompt,看情况根据llm效果来；
5. roo code中进行问答；
