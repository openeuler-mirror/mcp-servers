# LLM 冲突解决人工确认功能

## 功能概述

在 CVE 补丁应用过程中，当启用 LLM 自动解决冲突功能时，可以选择添加人工确认环节，确保补丁的安全性和准确性。

## 使用场景

### 推荐启用人工确认的场景：
- ✅ 生产环境的 CVE 修复
- ✅ 高危漏洞的补丁
- ✅ 核心系统组件的修改
- ✅ 对代码安全性要求较高的场景

### 可以不用人工确认的场景：
- ✅ 测试环境验证
- ✅ 低风险补丁
- ✅ 批量自动化处理

## 使用方法

### 1. 默认用法（需要人工确认）

```bash
cvekit apply-patch --use-llm --branch ule4-develop CVE-2024-1234
```

LLM 生成补丁后，会**暂停并显示补丁内容**，等待用户确认。

### 2. 自动化模式（跳过确认）

```bash
cvekit apply-patch --use-llm --no-confirm --branch ule4-develop CVE-2024-1234
```

LLM 生成的补丁将**自动应用**，无需用户干预。

> ⚠️ **注意**：`--no-confirm` 参数仅用于自动化场景，生产环境建议保持默认的人工确认。

### 3. 交互式确认流程

当使用 `--use-llm` 时（默认行为），系统将：

1. **显示 LLM 生成的完整补丁内容**
2. **提示用户选择操作**：
   ```
   是否应用此补丁？(y/n/edit): 
   ```

3. **用户选项**：
   - `y` 或 `yes`: 应用补丁
   - `n` 或 `no`: 拒绝应用补丁（流程终止）
   - `edit`: 打开编辑器手动修改补丁

### 4. 编辑补丁示例

选择 `edit` 后：
- 系统会使用默认编辑器（`$EDITOR` 环境变量指定，默认为 `vi`）打开临时补丁文件
- 用户可以修改补丁内容
- 保存退出后，系统将应用修改后的补丁

## 参数说明

### `--use-llm`
- **作用**: 启用 LLM 自动解决补丁冲突
- **类型**: 布尔标志
- **默认**: 关闭

### `--no-confirm`
- **作用**: 跳过 LLM 生成补丁后的人工确认步骤
- **类型**: 布尔标志
- **默认**: `False`（需要确认）
- **说明**: 仅在自动化场景使用，生产环境建议保持默认确认

> 💡 **设计原则**: 安全优先。默认需要人工确认，只有明确指定 `--no-confirm` 才会自动应用。

### 其他相关参数

```bash
# LLM 配置
--llm-provider       # LLM 提供商（如 openai, minimax, deepseek）
--llm-base-url      # LLM API 基础地址
--llm-model-name    # LLM 模型名称
--api-key           # LLM API 密钥
```

## 完整示例

### 示例 1: 安全修复（推荐用于生产）

```bash
export API_KEY="your-api-key"
cvekit apply-patch \
    --use-llm \
    --branch ule4-develop \
    --llm-provider openai \
    --llm-model-name gpt-4o-mini \
    CVE-2024-1234
```

这是**默认行为**，LLM 生成补丁后会暂停等待确认。

### 示例 2: 快速自动修复（适合测试/自动化）

```bash
export API_KEY="your-api-key"
cvekit apply-patch \
    --use-llm \
    --no-confirm \
    --branch ule4-develop \
    --llm-provider openai \
    --llm-model-name gpt-4o-mini \
    CVE-2024-1234
```

⚠️ **警告**: 补丁会自动应用，不会等待确认！

### 示例 3: 使用自定义 LLM 服务

```bash
cvekit apply-patch \
    --use-llm \
    --branch ule4-develop \
    --llm-provider custom \
    --llm-base-url https://api.example.com/v1 \
    --llm-model-name my-model \
    --api-key sk-xxx \
    CVE-2024-1234
```

默认需要确认，如果要自动应用，加上 `--no-confirm` 即可。

## 输出示例

### 启用人工确认时的输出

```
[INFO] 尝试使用 LLM 自动解决冲突...
[INFO] LLM 成功解决冲突，生成修复后的补丁...

================================================================================
LLM 生成的补丁内容如下，请确认是否应用：
================================================================================

--- a/fs/iomap/buffered-io.c
+++ b/fs/iomap/buffered-io.c
@@ -123,7 +123,7 @@ iomap_write_end(struct inode *inode, loff_t pos, unsigned len,
         copied = iomap_write_end_inline(page, iomap, pos, len, status);
-        if (unlikely(copied < 0))
+        if (WARN_ON_ONCE(copied < 0))
                 goto out_unlock;
 
================================================================================

是否应用此补丁？(y/n/edit): 
```

### 用户选择后的响应

- **选择 y**: `[INFO] 用户确认应用补丁` → 继续应用
- **选择 n**: `[INFO] 用户拒绝应用补丁` → 终止流程
- **选择 edit**: 打开编辑器 → 允许修改补丁

## 环境变量

可以通过环境变量设置默认行为：

```bash
# 默认启用人工确认（更安全）
export LLM_CONFIRM=true

# 默认禁用人工确认（更自动化）
export LLM_CONFIRM=false
```

## 最佳实践

### 推荐配置

对于生产环境，建议直接使用默认行为（无需额外参数）：

```bash
# 默认就需要确认，安全！
cvekit apply-patch --use-llm --branch xxx CVE-xxx
```

如果需要别名简化：
```bash
alias cvekit-auto='cvekit apply-patch --use-llm --no-confirm'
```

### 工作流程建议

1. **初次修复**: 使用默认行为（需要确认）仔细审查 LLM 生成的补丁
2. **批量处理**: 对同一 CVE 的多个分支，可以先在一个分支上验证，然后使用 `--no-confirm` 批量处理其他分支
3. **紧急修复**: 时间紧迫时可以使用 `--no-confirm`，但事后应该 review 提交的补丁

## 注意事项

⚠️ **重要提醒**:

1. 即使启用了人工确认，也应该仔细审查补丁内容
2. 编辑补丁时要小心保持 unified diff 格式
3. 拒绝应用补丁后，需要手动解决冲突或重新运行
4. LLM 生成的补丁可能包含 unintended changes，务必仔细检查

## 技术实现

### 核心修改

- **apply_patch.py**: 添加 `llm_confirm` 参数和确认逻辑
- **cli.py**: 添加 `--no-confirm` CLI 参数（默认需要确认）
- **conflict_resolver.py**: 保持不变（补丁生成逻辑）

### 确认流程

```
git apply 失败
    ↓
检测到 use_llm=True
    ↓
调用 LLM ConflictResolver
    ↓
生成修复后的补丁
    ↓
[如果 llm_confirm=True]
    ├─ 显示补丁内容
    ├─ 等待用户输入
    ├─ y → 应用补丁
    ├─ n → 终止
    └─ edit → 编辑后应用
    ↓
应用补丁并提交
```

## 故障排除

### Q: 编辑器无法打开？
A: 检查 `$EDITOR` 环境变量是否正确设置：
```bash
echo $EDITOR  # 查看当前编辑器
export EDITOR=vim  # 设置编辑器
```

### Q: 如何跳过确认？
A: 使用 `--no-confirm` 参数即可：
```bash
cvekit apply-patch --use-llm --no-confirm --branch xxx CVE-xxx
```

### Q: 确认后可以反悔吗？
A: 一旦确认应用，补丁就会被提交。如需撤销，请使用 git reset 或 git revert。

## 参考资料

- [CVEKit MCP 使用指南](../README.md)
- [LLM 冲突解决器实现](src/cvekit/utils/agent/conflict_resolver.py)
- [补丁应用逻辑](src/cvekit/utils/apply_patch.py)
