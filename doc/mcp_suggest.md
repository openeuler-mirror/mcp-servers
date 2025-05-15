# MCP Server格式描述建议

### 背景

MCP Server需要一个格式化的描述，用来表述自身元数据，依赖，能力描述和问题处理建议，用于后续的打包及信息快速读取，并支持后续能力扩展。

#### 元数据

随着MCP Server数量的增长，用户需要能够快速获取到所需MCP Server，并快速查找并获取到相关MCP Server的来源，这类元数据通常包括

- 唯一标识，避免MCP Server冲突
- 名称
- 能力概述
- 来源

#### 依赖管理

开发者完成MCP Servers开发后，用户基于各种MCP Client去部署安装MCP Servers进行使用。MCP Server当前支持多种语言开发（typescript, java, python ...)，软件的依赖分为语言包依赖及外部工具依赖：

- 对于自身的语言包依赖，可以通过安装包管理器进行安装；
- 对于外部工具的依赖，需要基于当前系统去安装相关的软件包活工具，需要有一个描述能够安装此类依赖。

#### 问题管理

大模型在访问MCP Servers时，调用Tool的时候，会因为环境原因出现各种类型的问题，例如：

- 运行的依赖在环境中缺失，执行失败
- 工具能力混淆，调用错误
- 传入参数异常，调用错误



### 格式（初稿）

```yaml
id: "Deploy.software.xxx_mcp"        # 描述mcp的 类型.子类.名称
name: "xxx_mcp"                      # 名称
description: "基于xxx调用返回yy"       # 能力描述
homepage: "https://xxx"              # mcp的来源

tools:
	- tool_name: "tool_1"              # 工具名称
		description: "用于xxx"            # 工具能力描述
		template: ""                     # 工具调用模板
		parameters:
			- arg_1: "type, des, required" # 参数类型, 参数描述, 是否可选
			- arg_2: ....
		output: "type, des"              # 返回类型, 返回描述
	- tool_name: "tool_2" 
		...
requires:
	- d1                               # 依赖包1
	- d2                               # 依赖包2
faqs:                                # 记录错误返回后的处理经验
	- reponse: "当返回缺少xxx时候" 
		solution: "可以执行yy来解决"
	- reponse: "xxx"
		solution: "yyy"
		
... # 支持后续关键字扩展
```