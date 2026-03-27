# 使用patchflow agent

## 环境变量配置

在使用patchflow agent前，需配置以下环境变量：

```bash
# 配置仓库地址
export REPO_URL=${REPO_URL} 
# 配置fork仓库地址
export FORK_REPO_URL=${FORK_REPO_URL}
# 配置代码托管平台令牌（支持Gitee、GitCode等）
export GITEE_TOKEN=${GITEE_TOKEN}
# 配置用户签名
export SIGNER_NAME=${SIGNER_NAME}
# 配置用户邮箱
export SIGNER_EMAIL=${SIGNER_EMAIL}

# （可选）配置大模型提供商及密钥
# 使用云端模型示例（需提供 API_KEY）：
# export LLM_PROVIDER=openai
# export API_KEY=<your_llm_api_key>
#
# 使用本地免鉴权模型示例（仅当本地服务提供 OpenAI 兼容的 /v1/chat/completions 接口）：
# export LLM_PROVIDER=local
# export MODEL_NAME=codellama-32b-instruct   # 或你的本地模型名称
# # 本地模型如不需要鉴权，可不设置 API_KEY；如需鉴权则正常配置 API_KEY
# export API_KEY=<optional_local_llm_token>
```

## 命令使用

### 1. 解析issue

```bash
cvekit --action parse-issue --cve-id ${CVE_ID}
```

其中，CVE_ID是要修复的CVE id

### 2. 克隆linux和kernel源码

```bash
cvekit --action setup-env
```

### 3. 获取引入和修复commit id

```bash
cvekit --action get-commits --cve-id ${CVE_ID}
```

### 4. 分析修复分支

```bash
cvekit --action analyze-branches --cve-id ${CVE_ID}
```

### 5. 应用补丁

```bash
cvekit --action apply-patch --cve-id ${CVE_ID} --patch-path ${PATCH_PATH}
```

### 6. 创建PR

```bash
cvekit --action create-pr --cve-id ${CVE_ID} --branch ${BRANCH_NAME}
```

### 7. 修复补丁冲突

```bash
cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} --api-key ${API_KEY} --llm-provider ${LLM_PROVIDER}
```

## 批量回移植（backport-batch）

`backport-batch` 通过一个 YAML/JSON 配置文件批量检查/回移植提交，并输出 `*.report.yml` 报告文件用于复跑与人工确认。支持从 Excel 文件生成配置文件，以及直接应用补丁并签名。

### 依赖说明

该功能依赖 `GitPython`（提供 `import git`）与 `PyYAML`；若启用交互模式（`-i/--interactive`）建议安装 `tabulate` 用于表格展示；若使用 Excel 输入功能，需要安装 `openpyxl`（已在 `requirements.txt` 中包含）。

### 从 Excel 文件生成配置

可以通过 `--backport-excel` 选项从 Excel 文件生成配置文件，适用于批量处理大量提交。

```bash
# 从 Excel 文件生成配置文件
cvekit --action backport-batch --backport-excel ./950_commit.xlsx -o ./test.yml --backport-config ./demo.yml
```

### 配置文件（raw 模式）

raw 配置用于“批量检查 + 生成报告”，默认会对 commits 做排序、合入/冲突检测，并生成 `${backport-config}.report.yml`，**不会在目标仓直接落地回移植结果**（用于先摸底）。

示例（不要把 token / api_key 写进文件，建议用环境变量或命令行传参）：

```yaml
project: linux
project_url: https://gitee.com/openeuler/kernel
project_dir: /path/to/source-repo
source_branch: OLK-6.6              # 可选：用于在多候选 title 匹配时优先过滤
target_path: /path/to/target-repo
target_release: openEuler-24.03-LTS-SP1-patchpool
patch_dataset_dir: /path/to/patch_dataset
llm_provider: minimax               # 可选：report 模式回移植时使用
api_key: ${API_KEY}                 # 建议通过环境变量或命令行 --api-key
commits:
- commit: 2d1a8bfb61ec
  commit_title: 'etm4x: Fix etm4_count race by moving cpuhp callbacks to init'
- commit: 16a0cbac6609
  commit_title: 'drivers: arch_topology: Refactor do-while loops'
```

运行：

```bash
# 通过已安装的入口（python setup.py install 后）
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json

# 或直接用模块运行（开发调试更直观）
python -m cvekit.cli --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json
```

### 报告文件（report 模式）

当配置文件后缀为 `.report.yml`（或 commits 条目包含 `merged_in_target/has_conflict/...` 等字段）时视为 report 配置。

report 配置用于”按报告执行”：

- **merged_in_target=true**：跳过
- **has_conflict=true**：触发回移植（调用 `backport` 流程/LLM）
- **has_conflict=false**：直接在目标仓尝试 `cherry-pick` 应用

运行（可选交互编辑）：

```bash
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml.report.yml -i --debug --json
```

### 应用特定补丁并签名

可以使用 `--apply` 选项指定特定的 commit 进行应用，并使用 `--signer-name` 和 `--signer-email` 选项为提交添加签名。

```bash
# 应用特定补丁并签名
cvekit --action backport-batch --backport-config test.yml.filtered.report.yml --json --debug --apply 71544d0b1de3 --signer-name "dev" --signer-email "dev@xx.com" -i
```

## 完整工作流程

1. **从 Excel 生成配置**

   ```bash
   cvekit --action backport-batch --backport-excel ./950_commit.xlsx -o ./test.yml --backport-config ./demo.yml
   ```

2. **生成报告**

   ```bash
   cvekit --action backport-batch --backport-config ./test.yml --debug
   ```

3. **查看生成的报告**

   ```bash
   cat test.yml.report.yml
   ```

4. **交互式执行回移植**

   ```bash
   cvekit --action backport-batch --backport-config test.yml.report.yml --debug -i
   ```

5. **应用特定补丁并签名**

   ```bash
   cvekit --action backport-batch --backport-config test.yml.filtered.report.yml --json --debug --apply 71544d0b1de3 --signer-name "dev" --signer-email "dev@xx.com" -i
   ```

## 注意事项

- 建议用环境变量传入敏感信息：`GITEE_TOKEN`、`API_KEY`，或通过命令行 `--gitee-token/--api-key` 传入。
- `backport-batch` 会写出报告文件，请关注同目录下生成的 `*.report.yml` 并以它作为下一轮输入。
- 使用 Excel 输入功能时，确保安装了 `openpyxl` 依赖：`pip install openpyxl`。
