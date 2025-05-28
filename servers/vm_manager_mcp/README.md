# 虚拟机管理MCP Server

## 功能描述
提供KVM虚拟机的基础管理功能，包括：
- 虚拟机创建/删除
- 虚拟机启动/停止
- 虚拟机状态查询
- 虚拟机网络配置

## 依赖要求
- libvirt
- qemu-kvm
- virt-install
- libvirt-client

## 使用方法
1. 确保已安装上述依赖
2. 启动MCP Server
3. 通过MCP协议调用提供的工具

## 工具列表
- create_vm: 创建虚拟机
- delete_vm: 删除虚拟机
- start_vm: 启动虚拟机
- stop_vm: 停止虚拟机
- list_vms: 列出所有虚拟机
- get_vm_status: 获取虚拟机状态