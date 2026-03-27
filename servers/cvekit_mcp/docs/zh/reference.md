# 参考信息

## 相关文档

- [Gitee API 文档](https://gitee.com/api/v5/swagger)
- [GitCode API 文档](https://docs.gitcode.com/v1-docs/docs/)
- [OpenAI API 文档](https://platform.openai.com/docs/api-reference)
- [Python gettext 文档](https://docs.python.org/3/library/gettext.html)
- [PyBabel 文档](https://babel.pocoo.org/en/latest/)
- [GitPython 文档](https://gitpython.readthedocs.io/en/stable/)
- [PyYAML 文档](https://pyyaml.org/wiki/PyYAMLDocumentation)

## 依赖包

| 依赖包 | 版本要求 | 用途 |
|-------|---------|------|
| GitPython | >=3.1.0 | Git 操作 |
| PyYAML | >=6.0 | YAML 解析 |
| tabulate | >=0.9.0 | 表格展示（可选） |
| openpyxl | >=3.0.0 | Excel 文件处理 |
| requests | >=2.28.0 | HTTP 请求 |
| babel | >=2.10.0 | 国际化支持 |

## 环境变量

| 环境变量 | 描述 | 必需 |
|---------|------|------|
| REPO_URL | 仓库地址 | 是 |
| FORK_REPO_URL | fork 仓库地址 | 是 |
| GITEE_TOKEN | 代码托管平台令牌（支持Gitee、GitCode等） | 是 |
| SIGNER_NAME | 用户签名 | 是 |
| SIGNER_EMAIL | 用户邮箱 | 是 |
| LANG | 语言设置 | 否 |
| LLM_PROVIDER | 大模型提供商 | 否 |
| API_KEY | 大模型 API 密钥 | 否 |
| MODEL_NAME | 本地模型名称 | 否 |
| LOG_LEVEL | 日志级别 | 否 |
| LOG_FILE | 日志文件路径 | 否 |

## 命令行参数

### 通用参数

| 参数 | 描述 | 示例 |
|-----|------|------|
| --action | 执行的操作 | parse-issue, setup-env, etc. |
| --debug | 启用调试日志 | --debug |
| --json | 输出 JSON 格式 | --json |

### 特定操作参数

| 操作 | 参数 | 描述 |
|-----|------|------|
| parse-issue | --cve-id | CVE ID |
| get-commits | --cve-id | CVE ID |
| analyze-branches | --cve-id | CVE ID |
| apply-patch | --cve-id | CVE ID |
| apply-patch | --patch-path | 补丁路径 |
| create-pr | --cve-id | CVE ID |
| create-pr | --branch | 分支名称 |
| backport | --cve-id | CVE ID |
| backport | --branch | 分支名称 |
| backport | --api-key | API 密钥 |
| backport | --llm-provider | LLM 提供商 |
| backport-batch | --backport-config | 配置文件路径 |
| backport-batch | --backport-excel | Excel 文件路径 |
| backport-batch | -o, --output | 输出文件路径 |
| backport-batch | -i, --interactive | 交互模式 |
| backport-batch | --apply | 应用特定 commit |
| backport-batch | --signer-name | 签名用户名 |
| backport-batch | --signer-email | 签名邮箱 |
| 通用 | --gitee-token | 代码托管平台令牌 |

## 配置文件格式

### backport-batch 配置文件

```yaml
project: <项目名称>
project_url: <项目 URL>
project_dir: <源代码目录>
source_branch: <源分支>  # 可选
target_path: <目标仓库路径>
target_release: <目标版本>
patch_dataset_dir: <补丁数据集目录>
llm_provider: <LLM 提供商>  # 可选
api_key: <API 密钥>  # 建议通过环境变量
commits:
- commit: <commit ID>
  commit_title: <commit 标题>
```

## 报告文件格式

```yaml
project: <项目名称>
project_url: <项目 URL>
project_dir: <源代码目录>
target_path: <目标仓库路径>
target_release: <目标版本>
commits:
- commit: <commit ID>
  commit_title: <commit 标题>
  merged_in_target: <是否已合并>
  has_conflict: <是否有冲突>
  error: <错误信息>  # 可选
  patch_applied: <补丁是否应用>  # 可选
```

## 代码结构

```text
patchflow/
├── cli.py              # 命令行入口
├── core/              # 核心功能
│   ├── parser.py      # CVE 解析
│   ├── git.py         # Git 操作
│   ├── platform.py    # 代码托管平台操作（支持Gitee、GitCode等）
│   ├── backport.py    # 补丁回移植
│   └── llm.py         # LLM 集成
├── locales/           # 语言包
│   ├── en/            # 英文
│   └── zh/            # 中文
└── utils/             # 工具函数
    ├── config.py      # 配置管理
    ├── logger.py      # 日志管理
    └── helpers.py     # 辅助函数
```

## 最佳实践

1. **使用环境变量**：通过环境变量传入敏感信息，避免硬编码
2. **定期更新**：定期更新依赖包和工具版本
3. **使用虚拟环境**：在隔离的环境中运行，避免依赖冲突
4. **备份配置**：备份重要的配置文件和报告
5. **测试验证**：在生产环境使用前进行充分测试
6. **监控日志**：定期检查日志，及时发现问题
7. **权限控制**：为 Gitee 令牌设置最小必要权限
8. **文档维护**：及时更新文档，反映最新功能和变更
