# MCP Server RPM打包指南

## 1. 目录结构要求

每个MCP Server需要按照以下结构组织文件：
```
servers/
  └── [server-name]/       # MCP Server名称目录
      ├── mcp_config.json  # MCP Server配置文件(必须)
      ├── mcp-rpm.yaml     # RPM打包配置文件(必须)
      └── src/             # 源代码目录
          ├── server.py    # 主程序文件(必须)
          ├── requirements.txt # Python依赖(可选)
          └── ...          # 其他文件
```

## 2. mcp-rpm.yaml配置说明
可以参考`../servers/rpm-builder/mcp-rpm.yaml`

每个MCP Server 必须在根目录下创建`mcp-rpm.yaml`文件，格式如下：

```yaml
name: "MCP server 名称"  # 必须与目录名一致
summary: "简短描述"
description: |
  详细描述，支持多行

dependencies:
  system:  # 系统级依赖
    - python3
    - uv
    - python3-mcp
    - jq
  packages: # 额外的软件包依赖
    - rpm-build

files:
  required:  # 必须存在的文件
    - mcp_config.json
    - src/server.py
  optional:  # 可选文件
    - src/requirements.txt
    - src/pyproject.toml
```

## 3. 生成spec文件

配置完成后，运行以下命令生成spec文件：
```bash
python3 generate-mcp-spec.py
```

生成的`mcp-servers.spec`文件将包含所有MCP Server的打包配置。

## 4. 构建RPM包

1. 准备构建环境：
```bash
mkdir -p ~/rpmbuild/{SOURCES,SPECS}
```

2. 打包源代码：
```bash
tar czvf ~/rpmbuild/SOURCES/mcp-servers-1.0.0.tar.gz --transform 's,^,mcp-servers/,' *
```

3. 构建RPM包：
```bash
rpmbuild -ba mcp-servers.spec
```

构建完成后，RPM包将生成在`~/rpmbuild/RPMS/noarch/`目录下。

## 5. 注意事项

1. 确保所有MCP Server的`mcp_config.json`文件已正确配置
2. 如果MCP Server有Python依赖，必须在`src/requirements.txt`中列出
3. 每次新增或修改MCP Server后，需要重新生成spec文件
4. 版本更新时需要修改`generate-mcp-spec.py`中的版本号