# 软件编译

patchflow agent 使用 gettext 模块实现多语言支持，在代码正式执行前，需编译语言包，将文本格式的 PO 文件编译为 MO 文件。

## 编译步骤

1. **提取可翻译字符串**

    ```bash
    pybabel extract -k i18n -o messages.pot .
    ```

2. **更新翻译目录**

    ```bash
    pybabel update -i messages.pot -d cvekit/locales
    ```

3. **编译消息目录**

    ```bash
    pybabel compile -d cvekit/locales
    ```

## 注意事项

- 若代码未修改，只需编译消息目录即可
- 若有新增翻译字符串，需修改 `cvekit/locales` 下对应语言中的 `messages.po` 文件

## 依赖安装

在编译前，确保已安装所需依赖：

```bash
cd servers/cvekit_mcp/src && pip install -r requirements.txt
```
