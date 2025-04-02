# MCP Python SDK

<div align="center">

<strong>Python implementation of the Model Context Protocol (MCP)</strong>

[![PyPI][pypi-badge]][pypi-url]
[![MIT licensed][mit-badge]][mit-url]
[![Python Version][python-badge]][python-url]
[![Documentation][docs-badge]][docs-url]
[![Specification][spec-badge]][spec-url]
[![GitHub Discussions][discussions-badge]][discussions-url]

</div>

<!-- omit in toc -->
## 目录

- [MCP Python SDK](#mcp-python-sdk)
  - [概述](#概述)
  - [安装](#安装)
    - [如何把MCP添加到Python项目](#添加mcp-server到你的python项目)
    - [单独运行MCP开发工具](#单独运行mcp开发工具)
  - [快速开始](#快速开始)
  - [MCP是什么](#mcp是什么)
  - [核心概念](#核心概念)
    - [Server](#server)
    - [Resources](#resources)
    - [Tools](#tools)
    - [Prompts](#prompts)
    - [Images](#images)
    - [Context](#context)
  - [运行Server](#运行mcp-server)
    - [开发者模式](#开发者模式)
    - [使用Claude Desktop运行](#使用claude-desktop运行)
    - [直接执行](#直接执行)
    - [集成到现有ASGI服务器](#集成到现有asgi服务器)
  - [Demo](#demo)
    - [Echo Server](#echo-server)
    - [SQLite Explorer](#sqlite-explorer)
  - [进阶用法](#进阶用法)
    - [Low-Level Server](#low-level-server)
    - [编写一个MCP Client](#编写一个mcp-client)
    - [MCP Primitives](#mcp-primitives)
    - [Server Capabilities](#server-capabilities)
  - [参考文档](#参考文档)
  - [License](#license)

[pypi-badge]: https://img.shields.io/pypi/v/mcp.svg
[pypi-url]: https://pypi.org/project/mcp/
[mit-badge]: https://img.shields.io/pypi/l/mcp.svg
[mit-url]: https://github.com/modelcontextprotocol/python-sdk/blob/main/LICENSE
[python-badge]: https://img.shields.io/pypi/pyversions/mcp.svg
[python-url]: https://www.python.org/downloads/
[docs-badge]: https://img.shields.io/badge/docs-modelcontextprotocol.io-blue.svg
[docs-url]: https://modelcontextprotocol.io
[spec-badge]: https://img.shields.io/badge/spec-spec.modelcontextprotocol.io-blue.svg
[spec-url]: https://spec.modelcontextprotocol.io
[discussions-badge]: https://img.shields.io/github/discussions/modelcontextprotocol/python-sdk
[discussions-url]: https://github.com/modelcontextprotocol/python-sdk/discussions

## 概述

模型上下文协议（Model Context Protocol，MCP） 允许应用程序以标准化方式为大型语言模型（LLM）提供上下文，从而将上下文供给与实际的 LLM 交互逻辑解耦。本 Python SDK 完整实现了 MCP 规范，可轻松实现以下功能：

- 构建可连接任意 MCP Server的客户端
- 创建可暴露资源、提示词及工具的 MCP Server
- 使用 stdio 和 SSE 等标准传输协议
- 处理所有 MCP 协议消息与生命周期

## 安装

### 添加MCP Server到你的python项目

我们推荐使用 [uv](https://docs.astral.sh/uv/) 来管理python项目. 在基于 uv 管理的 Python 项目中，通过以下方式添加 `mcp` 依赖：

```bash
uv add "mcp[cli]"
```
或者，你也可以使用pip安装依赖:
```bash
pip install "mcp[cli]"
```

### 单独运行MCP开发工具

使用uv运行mcp命令:

```bash
uv run mcp
```

## 快速开始

让我们创建一个简易的 MCP 服务，该服务将实现以下内容：
- 计算器工具
- 若干数据接口

```python
# server.py
from mcp.server.fastmcp import FastMCP

# Create an MCP server
mcp = FastMCP("Demo")


# Add an addition tool
@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


# Add a dynamic greeting resource
@mcp.resource("greeting://{name}")
def get_greeting(name: str) -> str:
    """Get a personalized greeting"""
    return f"Hello, {name}!"
```

你可以安装这个MCP Server在 [Claude Desktop](https://claude.ai/download) 或者直接运行以下命令
```bash
mcp install server.py
```

您也可以通过 MCP Inspector 进行测试：
```bash
mcp dev server.py
```

## MCP是什么？

模型上下文协议 （[Model Context Protocol (MCP)](https://modelcontextprotocol.io)） 允许您构建以安全、标准化的方式向LLM应用提供数据和功能的服务器。可以将其理解为专为LLM交互设计的Web API。MCP服务器能够：

- 通过 **Resources** 提供数据 （类似GET端点，用于向LLM上下文加载信息）
- 通过 **Tools** 提供函数调用(类似POST端点，用于执行代码或生成某些结果)
- 通过 **Prompts** 提供交互模式(可复用的LLM交互模板)
- 还有更多的拓展能力！

## 核心概念

### Server

FastMCP 服务器是您接入 MCP 协议的核心接口，主要负责：

- 连接管理
- 协议合规性检查

```python
# Add lifespan support for startup/shutdown with strong typing
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fake_database import Database  # Replace with your actual DB type

from mcp.server.fastmcp import Context, FastMCP

# Create a named server
mcp = FastMCP("My App")

# Specify dependencies for deployment and development
mcp = FastMCP("My App", dependencies=["pandas", "numpy"])


@dataclass
class AppContext:
    db: Database


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""
    # Initialize on startup
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        # Cleanup on shutdown
        await db.disconnect()


# Pass lifespan to server
mcp = FastMCP("My App", lifespan=app_lifespan)


# Access type-safe lifespan context in tools
@mcp.tool()
def query_db(ctx: Context) -> str:
    """Tool that uses initialized resources"""
    db = ctx.request_context.lifespan_context["db"]
    return db.query()
```

### Resources

资源（Resources） 是向 LLM 提供数据的方式，类似于 REST API 中的 GET 端点：

- 仅提供数据，不执行复杂计算
- 无修改（不会修改系统状态）

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My App")


@mcp.resource("config://app")
def get_config() -> str:
    """Static configuration data"""
    return "App configuration here"


@mcp.resource("users://{user_id}/profile")
def get_user_profile(user_id: str) -> str:
    """Dynamic user data"""
    return f"Profile data for user {user_id}"
```

### Tools

工具（Tools） 允许 LLM 通过服务器执行操作。与资源不同，Tools的设计预期是：

- 执行计算任务（可包含复杂逻辑）
- 存在系统修改（如修改数据库状态）
- 需显式调用（由 LLM 主动触发）

```python
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My App")


@mcp.tool()
def calculate_bmi(weight_kg: float, height_m: float) -> float:
    """Calculate BMI given weight in kg and height in meters"""
    return weight_kg / (height_m**2)


@mcp.tool()
async def fetch_weather(city: str) -> str:
    """Fetch current weather for a city"""
    async with httpx.AsyncClient() as client:
        response = await client.get(f"https://api.weather.com/{city}")
        return response.text
```

### Prompts

提示词（Prompts） 是可复用的模板，用于优化 LLM 与服务器的交互：

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

mcp = FastMCP("My App")


@mcp.prompt()
def review_code(code: str) -> str:
    return f"Please review this code:\n\n{code}"


@mcp.prompt()
def debug_error(error: str) -> list[base.Message]:
    return [
        base.UserMessage("I'm seeing this error:"),
        base.UserMessage(error),
        base.AssistantMessage("I'll help debug that. What have you tried so far?"),
    ]
```

### Images

FastMCP 的 `Image` 类 为图像数据提供自动化处理能力：

```python
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

mcp = FastMCP("My App")


@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a thumbnail from an image"""
    img = PILImage.open(image_path)
    img.thumbnail((100, 100))
    return Image(data=img.tobytes(), format="png")
```

### Context

Context对象是Tools与Resource访问MCP能力的统一入口：

```python
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("My App")


@mcp.tool()
async def long_task(files: list[str], ctx: Context) -> str:
    """Process multiple files with progress tracking"""
    for i, file in enumerate(files):
        ctx.info(f"Processing {file}")
        await ctx.report_progress(i, len(files))
        data, mime_type = await ctx.read_resource(f"file://{file}")
    return "Processing complete"
```

## 运行MCP Server

### 开发者模式

MCP Inspector 提供开箱即用的服务调试方案，显著提升诊断效率：

```bash
mcp dev server.py

# Add dependencies
mcp dev server.py --with pandas --with numpy

# Mount local code
mcp dev server.py --with-editable .
```

### 使用Claude Desktop运行
如果你的MCP Server已经准备完成，可以使用Claude Desktop来运行：

```bash
mcp install server.py

# Custom name
mcp install server.py --name "My Analytics Server"

# Environment variables
mcp install server.py -v API_KEY=abc123 -v DB_URL=postgres://...
mcp install server.py -f .env
```

### 直接执行

直接运行MCP Server

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("My App")

if __name__ == "__main__":
    mcp.run()
```

使用以下方式运行:
```bash
python server.py
# or
mcp run server.py
```

### 集成到现有ASGI服务器

通过 `sse_app` 方法可将 SSE 服务器挂载至现有 ASGI 服务，实现多协议融合部署：

```python
from starlette.applications import Starlette
from starlette.routing import Mount, Host
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("My App")

# Mount the SSE server to the existing ASGI server
app = Starlette(
    routes=[
        Mount('/', app=mcp.sse_app()),
    ]
)

# or dynamically mount as host
app.router.routes.append(Host('mcp.acme.corp', app=mcp.sse_app()))
```

关于 Starlette 应用挂载的深度指南：查询 [Starlette documentation](https://www.starlette.io/routing/#submounting-routes).

## Demo

### Echo Server

Demo环境快速构建指南（集成Resource，Tools，Prompt）：

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Echo")


@mcp.resource("echo://{message}")
def echo_resource(message: str) -> str:
    """Echo a message as a resource"""
    return f"Resource echo: {message}"


@mcp.tool()
def echo_tool(message: str) -> str:
    """Echo a message as a tool"""
    return f"Tool echo: {message}"


@mcp.prompt()
def echo_prompt(message: str) -> str:
    """Create an echo prompt"""
    return f"Please process this message: {message}"
```

### SQLite Explorer

一个更复杂的数据库Demo展示:

```python
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SQLite Explorer")


@mcp.resource("schema://main")
def get_schema() -> str:
    """Provide the database schema as a resource"""
    conn = sqlite3.connect("database.db")
    schema = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
    return "\n".join(sql[0] for sql in schema if sql[0])


@mcp.tool()
def query_data(sql: str) -> str:
    """Execute SQL queries safely"""
    conn = sqlite3.connect("database.db")
    try:
        result = conn.execute(sql).fetchall()
        return "\n".join(str(row) for row in result)
    except Exception as e:
        return f"Error: {str(e)}"
```

## 进阶用法

### Low-Level Server

如需更精细的控制，您可以直接使用底层服务端实现。这将提供完整的协议访问权限，允许您自定义服务的每个环节，包括通过生命周期API（lifespan API）进行生命周期管理：

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fake_database import Database  # Replace with your actual DB type

from mcp.server import Server


@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[dict]:
    """Manage server startup and shutdown lifecycle."""
    # Initialize resources on startup
    db = await Database.connect()
    try:
        yield {"db": db}
    finally:
        # Clean up on shutdown
        await db.disconnect()


# Pass lifespan to server
server = Server("example-server", lifespan=server_lifespan)


# Access lifespan context in handlers
@server.call_tool()
async def query_db(name: str, arguments: dict) -> list:
    ctx = server.request_context
    db = ctx.lifespan_context["db"]
    return await db.query(arguments["query"])
```

生命周期API功能说明：
- 服务启停时的资源管理
- 处理器中通过请求上下文访问初始化资源
- 生命周期与处理器间的类型安全上下文传递

```python
import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Create a server instance
server = Server("example-server")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="example-prompt",
            description="An example prompt template",
            arguments=[
                types.PromptArgument(
                    name="arg1", description="Example argument", required=True
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    if name != "example-prompt":
        raise ValueError(f"Unknown prompt: {name}")

    return types.GetPromptResult(
        description="Example prompt",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text="Example prompt text"),
            )
        ],
    )


async def run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

### 编写一个MCP Client

SDK提供了一个high-level的MCP Client接口来连接各个MCP Servers：

```python
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="python",  # Executable
    args=["example_server.py"],  # Optional command line arguments
    env=None,  # Optional environment variables
)


# Optional: create a sampling callback
async def handle_sampling_message(
    message: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text",
            text="Hello, world! from model",
        ),
        model="gpt-3.5-turbo",
        stopReason="endTurn",
    )


async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read, write, sampling_callback=handle_sampling_message
        ) as session:
            # Initialize the connection
            await session.initialize()

            # List available prompts
            prompts = await session.list_prompts()

            # Get a prompt
            prompt = await session.get_prompt(
                "example-prompt", arguments={"arg1": "value"}
            )

            # List available resources
            resources = await session.list_resources()

            # List available tools
            tools = await session.list_tools()

            # Read a resource
            content, mime_type = await session.read_resource("file://some/path")

            # Call a tool
            result = await session.call_tool("tool-name", arguments={"arg1": "value"})


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

### MCP Primitives

MCP协议定义了Server的三个基础能力：

| 基础能力 | 管理对象               | 描述                                         | 场景                  |
|-----------|-----------------------|-----------------------------------------------------|------------------------------|
| Prompts   | User-controlled       | 用户触发的交互式模板        | Slash commands, menu options |
| Resources | Application-controlled| 由客户端应用程序管理的上下文数据   | File contents, API responses |
| Tools     | Model-controlled      |   暴露给大语言模型（LLM）用于执行操作     | API calls, data updates      |

### Server Capabilities

MCP servers在初始化时申明的功能：

| Capability  | Feature Flag                 | Description                        |
|-------------|------------------------------|------------------------------------|
| `prompts`   | `listChanged`                | Prompt template management         |
| `resources` | `subscribe`<br/>`listChanged`| Resource exposure and updates      |
| `tools`     | `listChanged`                | Tool discovery and execution       |
| `logging`   | -                            | Server logging configuration       |
| `completion`| -                            | Argument completion suggestions    |

## 参考文档

- [Model Context Protocol documentation](https://modelcontextprotocol.io)
- [Model Context Protocol specification](https://spec.modelcontextprotocol.io)
- [Officially supported servers](https://github.com/modelcontextprotocol/servers)


## License

基于 MIT License
