# PCI Device Information MCP Server

## Function Description

It provides the MCP tool for querying PCI device information, including:

- Obtaining detailed PCI device information
- Listing all PCI devices

## Dependencies

- pciutils (providing the **lspci** command)
- python3
- uv

## How to Use

```bash
# Call the service through the MCP client.
mcp call pci_info_mcp get_pci_info
mcp call pci_info_mcp list_pci_devices
```

## Example Output

```json
{
  "status": "success",
  "data": "00:00.0 \"Host bridge\" \"Intel Corporation\" ..."
}
```

## Packaging Description

Use generate-mcp-spec.py in the root directory of the project to generate the RPM spec file.
