# 故障排除

## 常见问题

### 1. 依赖安装失败

**症状**：执行 `pip install -r requirements.txt` 时失败

**可能原因**：

- 网络连接问题
- Python 版本不兼容
- 依赖包版本冲突

**解决方案**：

- 检查网络连接
- 确保使用 Python 3.6+ 版本
- 尝试使用虚拟环境：

  ```bash
  python3 -m venv venv
  source venv/bin/activate  # Linux/macOS
  venv\Scripts\activate     # Windows
  pip install --upgrade pip
  pip install -r requirements.txt
  ```

### 2. 语言包编译失败

**症状**：执行 `pybabel compile` 命令失败

**可能原因**：

- 缺少 gettext 工具
- 语言包文件格式错误

**解决方案**：

- 安装 gettext 工具：

  ```bash
  # Ubuntu/Debian
  apt-get install gettext

  # openEuler/CentOS/RHEL
  yum install gettext

  # macOS
  brew install gettext
  ```

- 检查语言包文件格式是否正确

### 3. 代码托管平台 API 调用失败

**症状**：执行需要代码托管平台 API 的命令时失败

**可能原因**：

- GITEE_TOKEN 未设置或无效
- API 速率限制
- 网络连接问题

**解决方案**：

- 检查 GITEE_TOKEN 是否正确设置
- 等待 API 速率限制重置
- 检查网络连接

### 4. 补丁应用失败

**症状**：执行 `apply-patch` 命令时失败

**可能原因**：

- 补丁路径不正确
- 补丁与目标代码不兼容
- Git 仓库状态异常

**解决方案**：

- 检查补丁路径是否正确
- 检查目标代码是否与补丁兼容
- 确保 Git 仓库状态正常：

  ```bash
  git status
  git stash
  ```

### 5. 批量回移植失败

**症状**：执行 `backport-batch` 命令时失败

**可能原因**：

- 配置文件格式错误
- 缺少必要依赖
- 目标仓库状态异常

**解决方案**：

- 检查配置文件格式是否正确
- 安装必要依赖：

  ```bash
  pip install GitPython PyYAML tabulate openpyxl
  ```

- 确保目标仓库状态正常

### 6. LLM 调用失败

**症状**：执行需要 LLM 的命令时失败

**可能原因**：

- API_KEY 未设置或无效
- LLM_PROVIDER 配置错误
- 网络连接问题

**解决方案**：

- 检查 API_KEY 是否正确设置
- 确认 LLM_PROVIDER 配置正确
- 检查网络连接

## 日志排查

### 启用调试日志

使用 `--debug` 参数启用调试日志：

```bash
cvekit --action <action> --debug
```

### 日志分析

- 检查错误信息和堆栈跟踪
- 确认所有必要的环境变量都已设置
- 验证 API 调用是否成功

## 环境检查

### 检查 Python 版本

```bash
python3 --version
```

### 检查依赖状态

```bash
pip list
```

### 检查 Git 状态

```bash
git status
git log --oneline -n 5
```

## 联系支持

如果以上解决方案都无法解决问题，可通过以下方式寻求支持：

- 查看项目文档和 issue 追踪
- 联系项目维护者
- 提交新的 issue 描述问题
