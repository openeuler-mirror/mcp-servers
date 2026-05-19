# VM Management MCP Server

## Function Description

It provides basic management functions for KVM VMs, including:

- VM creation/deletion
- VM startup/stop
- VM status query
- VM network configuration

## Dependencies

- libvirt
- qemu-kvm
- virt-install
- libvirt-client

## How to Use

1. Ensure that the preceding dependencies have been installed.
2. Start the MCP server.
3. Call the provided tools through the MCP protocol.

## Tools

- create_vm: Create a VM.
- delete_vm: Delete a VM.
- start_vm: Start a VM.
- stop_vm: Stop a VM.
- list_vms: List all VMs.
- get_vm_status: Obtain VM status.
