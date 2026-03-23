# 安装patchflow agent

## 安装步骤

1. **安装依赖**

    ```bash
    cd servers/cvekit_mcp/src && pip install -r requirements.txt
    ```

2. **编译语言包**

    参考 [软件编译](./build.md) 章节的编译步骤。

3. **安装cvekit_mcp**

    ```bash
    python3 setup.py install
    ```

## 设置语言

patchflow agent 通过读取环境变量中的 `LANG` 设置语言。

### 环境变量设置

- **设置中文**：

  ```bash
  export LANG=zh_CN.UTF-8
  ```

- **设置英文**：

  ```bash
  export LANG=en_US.UTF-8
  ```

### MCP配置文件设置

在mcp配置文件中，可通过增加 `env` 字段设置语言：

**设置为中文**：

```json
{
  "env": {
    "LANG": "zh_CN.UTF-8"
  }
}
```

**设置为英文**：

```json
{
  "env": {
    "LANG": "en_US.UTF-8"
  }
}
```
