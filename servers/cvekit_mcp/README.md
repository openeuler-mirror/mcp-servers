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
