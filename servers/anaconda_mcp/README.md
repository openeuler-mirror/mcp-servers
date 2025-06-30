# Anaconda MCP 服务器

这是一个用于管理Anaconda环境的MCP服务器实现.

## 功能
- Conda环境管理
  - 环境激活/退出(conda_activate/conda_deactivate)
  - 环境列表查询(conda_env_list)
  - 环境创建(conda_create)
- 包管理
  - 包安装(conda_install)
  - 包列表查询(conda_list)  
  - 包更新(conda_update)

## 安装
1. 安装Python 3.8+和conda
2. 安装依赖: 
```bash
pip install -r src/requirements.txt
```
3. 运行服务器:
```bash
python src/server.py
```

