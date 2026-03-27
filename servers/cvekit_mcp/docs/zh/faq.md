# FAQ

## 常见问题

### 1. patchflow agent 是什么？

**答**：patchflow agent 是一个专注于处理代码仓中CVE补丁的工具，支持Gitee、GitCode等多个代码托管平台，旨在自动化CVE漏洞修复流程，提高补丁处理效率。

### 2. patchflow agent 支持哪些功能？

**答**：patchflow agent 支持以下功能：

- CVE解析
- 环境搭建（克隆Linux和kernel源码）
- 补丁分析（获取引入和修复commit ID，分析修复分支）
- 补丁应用
- PR创建
- 冲突解决（使用LLM辅助）
- 批量回移植

### 3. 如何设置语言？

**答**：patchflow agent 通过读取环境变量中的 `LANG` 设置语言：

- 设置中文：`export LANG=zh_CN.UTF-8`
- 设置英文：`export LANG=en_US.UTF-8`

也可以在mcp配置文件中通过 `env` 字段设置语言。

### 4. 如何处理补丁冲突？

**答**：使用 `backport` 命令并指定 LLM 提供商和 API 密钥来处理补丁冲突：

```bash
cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} --api-key ${API_KEY} --llm-provider ${LLM_PROVIDER}
```

### 5. 如何批量处理多个补丁？

**答**：使用 `backport-batch` 命令批量检查和回移植提交：

```bash
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml --debug
```

### 6. 如何从 Excel 文件生成配置？

**答**：使用 `--backport-excel` 选项从 Excel 文件生成配置：

```bash
cvekit --action backport-batch --backport-excel ./950_commit.xlsx -o ./test.yml --backport-config ./demo.yml
```

### 7. 如何为提交添加签名？

**答**：使用 `--signer-name` 和 `--signer-email` 选项为提交添加签名：

```bash
cvekit --action backport-batch --backport-config test.yml.filtered.report.yml --apply <commit> --signer-name "dev" --signer-email "dev@xx.com"
```

### 8. 为什么语言包编译失败？

**答**：可能的原因包括：

- 缺少 gettext 工具
- 语言包文件格式错误

解决方案：安装 gettext 工具并检查语言包文件格式。

### 9. 为什么代码托管平台 API 调用失败？

**答**：可能的原因包括：

- GITEE_TOKEN 未设置或无效
- API 速率限制
- 网络连接问题

解决方案：检查 GITEE_TOKEN 是否正确设置，等待 API 速率限制重置，检查网络连接。

### 10. 如何启用调试日志？

**答**：使用 `--debug` 参数启用调试日志：

```bash
cvekit --action <action> --debug
```

### 11. 如何安装必要的依赖？

**答**：运行以下命令安装依赖：

```bash
cd servers/cvekit_mcp/src && pip install -r requirements.txt
```

对于批量回移植功能，还需要安装：

```bash
pip install GitPython PyYAML tabulate openpyxl
```

### 12. 如何查看生成的报告？

**答**：批量回移植会生成报告文件，查看报告：

```bash
cat test.yml.report.yml
```

## 更多问题

对于更多问题，请参考 [常见问题](https://docs.openeuler.openatom.cn/zh/docs/common/faq/general/general_faq.html) 页面。
