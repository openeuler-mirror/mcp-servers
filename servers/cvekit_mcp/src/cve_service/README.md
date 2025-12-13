# 安装步骤
## 安装服务所需依赖
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
cd cve_service
uv venv
# 安装依赖
uv sync -i https://mirrors.aliyun.com/pypi/simple/

# 激活环境
source .venv/bin/activate
``` 
解压压缩包
将 `cve_service` 目录下的 `camel.tar.gz` 压缩包解压至 `cve_service` 目录（保留原目录结构）：
```bash
tar -zxvf camel.tar.gz
```
## 部署cvekit_mcp工具
1. 安装依赖
```bash
cd servers/cvekit_mcp/src && pip install babel
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
