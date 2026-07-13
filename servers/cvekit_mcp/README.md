# Gitcode代码仓CVE补丁处理服务

## 安装指导
1. 安装依赖
```bash
cd servers/cvekit_mcp/src && pip install -r requirements.txt
```
2. 编译语言包

cvekit使用gettext模块实现多语言的支持，在代码正式执行前，需编译语言包，把文本格式PO文件编译为MO文件

提取可翻译字符串
```bash
pybabel extract -k i18n -o messages.pot .
```
更新翻译目录
```bash
pybabel update -i messages.pot -d cvekit/locales
```
编译消息目录
```bash
pybabel compile -d cvekit/locales
```
注意：若代码未修改，只需翻译消息目录即可；若有新增翻译字符串，需修改cvekit/locales下对应语言中的messages.po文件

3. 安装
```bash
python3 setup.py install
```

## 设置语言

cvekit通过读取环境变量中的LANG设置语言

设置中文：
```bash
export LANG=zh_CN.UTF-8
```
设置英文：
```bash
export LANG=en_US.UTF-8
```

在mcp配置文件中，可通过增加env字段设置语言

mcp设置为中文
```json
      "env": {
        "LANG": "zh_CN.UTF-8"
      },
```
mcp设置为英文
```json
      "env": {
        "LANG": "en_US.UTF-8"
      },
```

## 功能简介

1. 配置环境变量
```bash
# 配置仓库地址
export REPO_URL=${REPO_URL} 
# 配置fork仓库地址
export FORK_REPO_URL=${FORK_REPO_URL}
# 配置gitee私人令牌
export GITEE_TOKEN=${GITEE_TOKEN}
# 配置用户签名
export SIGNER_NAME=${SIGNER_NAME}
# 配置用户邮箱
export SIGNER_EMALI=${SIGNER_EMAIL}

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

2. 解析issue
```bash
cvekit --action parse-issue --cve-id ${CVE_ID}
```
其中，CVE_ID是要修复的CVE id

3. 克隆linux和kernel源码
```bash
cvekit --action setup-env
```

4. 获取引入和修复commit id
```bash
cvekit --action get-commits --cve-id ${CVE_ID}
```

5. 分析修复分支
```bash
cvekit --action analyze-branches --cve-id ${CVE_ID}
```

6. 应用补丁
```bash
cvekit --action apply-patch --cve-id ${CVE_ID} --patch-path ${PATCH_PATH}
```

7. 创建PR
```bash
cvekit --action create-pr --cve-id ${CVE_ID} --branch ${BRANCH_NAME}
```

8. 修复补丁冲突
```bash
cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} --api-key ${API_KEY} --llm-provider ${LLM_PROVIDER}
```

### 选择解冲突方法

cvekit 支持以下解冲突方法：

- `portgpt`：默认方法，对应 `cvekit --action backport`。
- `mystique`：可选方法，对应 `cvekit --action mystique`。

单次回移植可直接通过 action 选择方法：

```bash
# 默认 PortGPT 流程
cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME}

# Mystique 流程
cvekit --action mystique --cve-id ${CVE_ID} --branch ${BRANCH_NAME}
```

启动 MCP 服务时，可通过 `--backport-engine` 指定 `analyze_branches`
自动处理冲突补丁时使用的方法：

```bash
cd servers/cvekit_mcp/src
python server.py --backport-engine mystique
```

MCP 服务默认使用 `portgpt`。修改启动参数后需要重启服务。

### Mystique 依赖与格式配置

Mystique 使用 Joern 进行代码分析。安装后通过 `JOERN_PATH` 指定
`joern-cli` 路径；未设置时默认使用 `~/.local/joern/joern-cli`。

```bash
curl -fSL https://github.com/joernio/joern/releases/latest/download/joern-install.sh \
  -o joern-install.sh
chmod +x joern-install.sh
./joern-install.sh --install-dir=~/.local/joern

export JOERN_PATH=~/.local/joern/joern-cli
```

Mystique模式下，解冲突之后对生成的代码进行格式调整，存在以下两种方式：

- `full`：对完整函数进行 LLM 格式调整，是默认模式。
- `changed`：保留目标函数中未变化的代码，仅对新增或替换区域进行 LLM
  格式调整，适合尽量减少无关格式变化。

使用 `changed` 模式时，若目标仓库存在 `.clang-format` 且系统能找到
`clang-format`，Mystique 还会使用目标仓库的格式规则处理变化行。

```bash
# 安装方式按系统选择，例如：
yum install clang-tools-extra
command -v clang-format

cvekit --action mystique --cve-id ${CVE_ID} --branch ${BRANCH_NAME} \
  --format-mode changed
```

也可以通过环境变量设置默认格式模式：

```bash
export MYSTIQUE_FORMAT_MODE=changed
```

在 MCP 配置中使用 Mystique 时，可将相关环境变量放入 `env`：

```json
{
  "cvekit_mcp": {
    "command": "python",
    "args": ["/path/to/cvekit_mcp/src/server.py", "--backport-engine", "mystique"],
    "env": {
      "JOERN_PATH": "/home/user/.local/joern/joern-cli",
      "MYSTIQUE_FORMAT_MODE": "changed"
    }
  }
}
```

`clang-format` 不属于必需依赖；未安装或目标仓库没有 `.clang-format` 时，
Mystique 会跳过局部 clang-format，继续生成补丁。通过 MCP 运行时，还需
确保 MCP 服务进程的 `PATH` 中包含 `clang-format` 所在目录。

使用完全自定义 LLM（任意 OpenAI 兼容服务）：
```bash
# --llm-provider 支持任意值，配合 --llm-base-url 和 --llm-model-name 使用
cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} \
  --llm-provider my-provider \
  --llm-base-url https://api.example.com/v1 \
  --llm-model-name gpt-4o-mini \
  --api-key ${API_KEY}
```

**LLM 配置优先级**（从高到低）：
1. 命令行参数：`--llm-provider`, `--llm-base-url`, `--llm-model-name`
2. 环境变量：`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL_NAME`（或 `MODEL_NAME`）
3. 内置预设：`openai`（默认）

9. 批量回移植（backport-batch）

`backport-batch` 通过一个 YAML/JSON 配置文件批量检查/回移植提交，并输出 `*.report.yml` 报告文件用于复跑与人工确认。支持从 Excel 文件生成配置文件，以及直接应用补丁并签名。

- **依赖说明**：该功能依赖 `GitPython`（提供 `import git`）与 `PyYAML`；若启用交互模式（`-i/--interactive`）建议安装 `tabulate` 用于表格展示；若使用 Excel 输入功能，需要安装 `openpyxl`（已在 `requirements.txt` 中包含）。

### 从 Excel 文件生成配置

可以通过 `--backport-excel` 选项从 Excel 文件生成配置文件，适用于批量处理大量提交。

```bash
# 从 Excel 文件生成配置文件
cvekit --action backport-batch --backport-excel ./950_commit.xlsx -o ./test.yml --backport-config ./demo.yml
```

### 配置文件（raw 模式）

raw 配置用于“批量检查 + 生成报告”，默认会对 commits 做排序、合入/冲突检测，并生成 `${backport-config}.report.yml`，**不会在目标仓直接落地回移植结果**（用于先摸底）。

默认情况下会检查完整 commits 列表。若希望先推进到第一个阻塞冲突，可追加 `--stop-at-first-conflict`：cvekit 仍会先对全部 commits 完成排序，然后按排序结果逐条检测；检测到第一条冲突后停止，后续条目写入 report 并标记为 `status: pending`。

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
backport_engine: portgpt            # 可选：portgpt（默认）或 mystique
commits:
- commit: 2d1a8bfb61ec
  commit_title: 'etm4x: Fix etm4_count race by moving cpuhp callbacks to init'
- commit: 16a0cbac6609
  commit_title: 'drivers: arch_topology: Refactor do-while loops'
  backport_engine: mystique         # 可选：仅覆盖当前 commit
```

运行：

```bash
# 通过已安装的入口（python setup.py install 后）
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json

# 全量排序后只检查到第一条冲突，后续条目保持 pending
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json --stop-at-first-conflict

# 通过命令行指定本次批处理使用 Mystique
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml --backport-engine mystique --debug --json

# 或直接用模块运行（开发调试更直观）
python -m cvekit.cli --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json
```

批处理的方法选择优先级为：

```text
单条 commit 的 backport_engine
  > 命令行 --backport-engine
  > YAML 顶层 backport_engine
  > portgpt
```

只支持 `portgpt` 和 `mystique`。最终使用的方法会写入 report。

### 报告文件（report 模式）

当配置文件后缀为 `.report.yml`（或 commits 条目包含 `merged_in_target/has_conflict/...` 等字段）时视为 report 配置。

report 配置用于“按报告执行”：
- **merged_in_target=true**：跳过
- **has_conflict=true**：使用配置的 `backport_engine` 触发回移植
- **has_conflict=false**：直接在目标仓尝试 `cherry-pick` 应用
- **status=pending**：尚未检查，可配合 `--stop-at-first-conflict` 从第一条 pending 继续检测；report 模式不会重新排序。

运行（可选交互编辑）：

```bash
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml.report.yml -i --debug --json
```

### 应用特定补丁并签名

可以使用 `--apply` 选项指定特定的 commit 或 patch 进行应用，并使用 `--commit-message-source`、`--commit-message-template`、`--signer-name`、`--signer-email` 等参数覆盖配置文件中的提交信息生成规则。

`--commit-message-source auto` 表示由 cvekit 判断 commit message 来源；也可以显式指定为 `openEuler` 或 `upstream`。如果 report/config 里已经有 `linux_repo_path`，命令行无需重复传 `--linux-repo-path`；只有需要临时覆盖配置文件里的 Linux 仓库路径时才追加该参数。

```bash
# 应用特定补丁，自动判断 commit message 来源，并签名
cvekit --action backport-batch \
  --backport-config test.yml.filtered.report.yml \
  --json --debug \
  --apply 71544d0b1de3 \
  --commit-message-source auto \
  --commit-message-template $'{{subject}}\n\ncommit {{commit_id}} {{source}}\n\n{{body}}\n\n{{trailers}}' \
  --signer-name "dev" \
  --signer-email "dev@xx.com"
```

### 完整工作流程

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
   cvekit --action backport-batch \
     --backport-config test.yml.filtered.report.yml \
     --json --debug \
     --apply 71544d0b1de3 \
     --commit-message-source auto \
     --commit-message-template $'{{subject}}\n\ncommit {{commit_id}} {{source}}\n\n{{body}}\n\n{{trailers}}' \
     --signer-name "dev" \
     --signer-email "dev@xx.com"
   ```

注意：
- 建议用环境变量传入敏感信息：`GITEE_TOKEN`、`API_KEY`，或通过命令行 `--gitee-token/--api-key` 传入。
- `backport-batch` 会写出报告文件，请关注同目录下生成的 `*.report.yml` 并以它作为下一轮输入。
- 使用 Excel 输入功能时，确保安装了 `openpyxl` 依赖：`pip install openpyxl`。
