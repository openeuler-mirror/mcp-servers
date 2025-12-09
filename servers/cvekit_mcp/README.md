# Gitee代码仓CVE补丁处理服务

## 安装指导
1. 安装依赖
```bash
cd servers/cvekit_mcp/src && pip install -r requirements.txt && pip install babel
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

1. 激活虚拟环境，配置环境变量
```bash
# 安装mcp-servers-cvekit后，激活虚拟python环境
source /opt/mcp-servers/servers/cvekit_mcp/.venv/bin/activate
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
cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} --openai-key ${OPENAI_KEY} --llm-provider ${LLVM_PROVIDER}
```