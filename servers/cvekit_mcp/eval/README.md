# AI Backport Eval

用于独立评测 cvekit Mystique 回移植结果与人工 PR commit 的一致性。

当前评测流程会：

1. 从输入 Excel 提取并去重 source commit；如果没有 Excel，则从人工 PR commit message 中提取源 commit。
2. 从人工 PR 历史映射对应 commit，并为每个 case 推导独立 baseline。
3. 在相同 target baseline 上单独运行 cvekit backport。
4. 区分 `already_merged`、`need_not_ported`、`direct_apply`、`mystique_patch` 和 `failed`。
5. 比较 AI 结果与人工 commit 的最终 tree 和 stable patch-id。
6. 输出包含 `Results`、`ConflictDetails` 和 `RunInfo` 的 Excel 报告。

## 文件

- `backport_eval.py`：当前最新通用评测程序。
- `scripts/run_backport_eval.sh`：通用启动脚本模板，参数为示例值，可复制或用环境变量覆盖。
- `env.example.sh`：不包含真实密钥的环境变量模板。

## 环境

```bash
python3 -m pip install -r requirements.txt
cp env.example.sh env.local.sh
# 编辑 env.local.sh，填写 API_KEY
source env.local.sh
```

还需要：

- 可用的 `cvekit` CLI。
- source 和 target Git 仓库。
- 描述 source commit 的输入 Excel，或 PR commit message 中包含源 commit 号。
- 能在 target 仓库创建临时分支和 worktree 的权限。

## 评测

启动脚本保留了当前 `/home/dev` 联调环境路径：

```bash
bash scripts/run_backport_eval.sh
```

可以把额外参数直接传给 `backport_eval.py`：

```bash
bash scripts/run_backport_eval.sh --discover-only
bash scripts/run_backport_eval.sh --case-limit 3
```

其他 PR 可复制通用脚本，或用环境变量覆盖示例值：

```bash
EVAL_NAME=my-eval \
SOURCE_REPO=/path/to/source \
SOURCE_BRANCH=origin/main \
SOURCE_EXCEL=/path/to/commits.xlsx \
TARGET_REPO=/path/to/target \
PR_URL=https://example.com/org/repo/pulls/123 \
FIRST_PR_COMMIT=FIRST_SHA \
LAST_PR_COMMIT=LAST_SHA \
CVEKIT=/path/to/cvekit \
CVEKIT_WORKDIR=/path/to/cvekit/workdir \
bash scripts/run_backport_eval_example.sh --discover-only
```

当前 `/home/dev` 示例脚本会默认从主 target 仓库创建独立 worktree：

```text
BASE_TARGET_REPO=/home/dev/Image/OpenCloudOS-Kernel
TARGET_WORKTREE_ROOT=/home/dev/Image/OpenCloudOS-Kernel-worktrees
TARGET_REPO=$TARGET_WORKTREE_ROOT/$EVAL_NAME
```

因此 `pr319_backport_eval` 和 `pr321_backport_eval` 会使用不同工作区，可以并行运行。不要手动把两个并行任务的 `TARGET_REPO` 覆盖成同一个目录；同一个 Git worktree 不能同时被多个评测脚本 `switch/reset/clean/apply`。

如果没有原始 commit 列表，可以不传 `--source-excel`，或在示例脚本里把 `SOURCE_EXCEL` 设为空：

```bash
SOURCE_EXCEL= \
bash scripts/run_backport_eval_example.sh --discover-only
```

此时脚本会从 PR commit message 中提取源 commit。支持常见格式包括：

```text
commit: <sha>
upstream commit: <sha>
openeuler commit: <sha>
(cherry picked from commit <sha>)
```

在这种模式下，结果表里的 `source_excel_rows` 字段会记录提取到该 source commit 的 PR commit 序号。

## 安全

不要提交真实的 LLM API key、GitCode/Gitee token、运行日志或评测 Excel。仓库的 `.gitignore` 已默认排除这些内容。
