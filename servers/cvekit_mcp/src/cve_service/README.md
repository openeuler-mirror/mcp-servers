# 安装步骤
## 安装仓库所需依赖
安装oegitext插件用于提交pr
```bash
yum install oegitext
```
补丁冲突解决需要安装ctags，但openeuler仓库没有，需要引入fedora里的镜像源
```
wget https://dl.fedoraproject.org/pub/fedora/linux/releases/42/Everything/source/tree/Packages/c/ctags-6.1.0-2.fc42.src.rpm
```
构建ctags镜像源

安装开发工具组用于构建,包含gcc、make等编译工具
```bash
sudo dnf groupinstall -y "Development Tools"
rpmbuild --rebuild ctags-6.1.0-2.fc42.src.rpm

# 到rpmbuild路径下
cd ~/rpmbuild/RPMS/

# 安装二进制RPM包，替换为实际包名
dnf install -y ctags-6.1.0-2.fc42.x86_64.rpm
```

安装uv python管理工具
```bash
yum install -y uv
```
安装python依赖
```bash
# 启动虚拟环境
uv venv
# 安装依赖
uv sync

# 激活环境
cd cve_service
source .venv/bin/activate
``` 
## 代码还原操作指南
### 前置说明
本操作用于将 `cvekit_mcp` 文件夹还原为服务运行所需的版本，并迁移至 `cve-service` 目录下，依赖 `folder_diff.diff` 差异文件完成还原。

### 操作步骤
#### 步骤 1：解压压缩包
将 `cve_service` 目录下的 `camel.tar.gz` 压缩包解压至 `cve_service` 目录（保留原目录结构）：
```bash
# 进入 cve_service 目录（请替换为实际路径）
cd /path/to/cve_service
# 解压压缩包
tar -zxvf camel.tar.gz -C ./
```

#### 步骤 2：统一文件目录
将 `cve_service` 文件夹、`folder_diff.diff` 差异文件**移动至** `mcp-servers/servers` 目录下，确保以下文件/文件夹处于**同一级目录**：
```
mcp-servers/servers/
├── cvekit_mcp/          # 待还原的基准文件夹
├── cve_service/         # 目标版本文件夹
└── folder_diff.diff     # 差异文件（核心）
```
执行命令示例（请替换为实际路径）：
```bash
mv /path/to/cve_service /path/to/mcp-servers/servers/
mv /path/to/folder_diff.diff /path/to/mcp-servers/servers/
```

#### 步骤 3：还原 cvekit_mcp 文件夹
1. 进入 `mcp-servers/servers` 目录：
```bash
cd /path/to/mcp-servers/servers
```
2. 执行 patch 命令，将 `cvekit_mcp` 还原为服务所需版本：
```bash
patch -p0 < folder_diff.diff
```
> 说明：`-p0` 参数保留 diff 文件中的相对路径，确保能精准匹配待修改文件。

#### 步骤 4：迁移还原后的文件夹
将还原完成的 `cvekit_mcp` 文件夹移动至 `cve_service` 目录下：
```bash
mv cvekit_mcp cve_service/
```


## 其他配置
在仓库当前目录下，配置环境文件.env，里面需要配置以下参数:
```
SILICONFLOW_API_KEY=<api_key>
GITEE_TOKEN=<gitee_token>
LLM_PROVIDER = "deepseek"
```
接着配置mcp配置文件mcp_settings.json
```
{
  "mcpServers": {
    "cvekit_mcp": {
      "command": ".venv/bin/python",
      "env": {
        "LANG": "en_CN.UTF-8",
        "PYTHONPATH": "./cvekit_mcp/src"
      },
      "args": [
        "./cvekit_mcp/src/server.py",
        "--gitee-token", 
        "xxx",
        "--llm-provider",
        "deepseek",
        "--openai-key",
        "xxx"
      ],
      "disabled": false,
      "alwaysAllow": [],
      "description": "Gitee代码仓CVE补丁处理服务",
      "timeout": 1200
    }
  }
}
```

## 运行
### Step 1: 运行服务端
```
python app_server.py
```

### Step 2: 运行客户端
```
# 如果是任务 CVE分支分析与适配检查，运行以下命令：
python app_client.py --action branches-analysis --cve-id <CVE-ID> 
# 如果是任务 CVE补丁应用与PR创建， 运行以下命令
python app_client.py --action patch-apply-pr-creation --cve-id <CVE-ID> --branches <branches> --signer-name <signer-name> --signer-email <signer-email>
# 如果是运行整个CVE修复流程
python app_client.py --action pipeline --cve-id <CVE-ID> --branches <branches> --signer-name <signer-name> --signer-email <signer-email>
```
