# codeReview Mcp使用说明

codeReview Mcp提供对C语言项目的代码读取，并触发大模型进行代码检视，返回issue

## Tools

1. review_code

   - 查询项目代码中的各种相关要素源码，只需要列出需要查询的
   - input:
     - project_path : 需要被检视的项目路径，使用绝对路径, 注意是项目路径, 不是包含type_name的文件路径
     - query_type: one of [--func, --struct, --macro, --globalvar]
     ​            "--func": {"type": "string", "description": "需要查询的函数名字"},
     ​            "--struct": {"type": "string", "description": "结构体名字"},
     ​            "--macro": {"type": "string", "description": "宏名字"},
     ​            "--globalvar": {"type": "string", "description": "全局变量名字"}
     - query_name: the name that need to check
   - Returns: list, code content and Review prompt

