# Container Image Conversion MCP Service

## Function Description

It provides container image format conversion and image pushing capabilities, supporting the following operations:

- Converting the image format (docker ↔ oci)
- Pushing images to the repository

## Dependencies

- skopeo
- buildah
- jq

## Tool Interfaces

### Converting the Image Format

```json
{
  "source": "docker://nginx:latest",
  "destination": "oci:/tmp/nginx:latest",
  "src_format": "docker",
  "dest_format": "oci"
}
```

### Pushing Images to the Repository

```json
{
  "image": "nginx",
  "registry": "registry.example.com/library",
  "tag": "latest",
  "authfile": "/path/to/auth.json"
}
```

## Configuration

Modify `mcp_config.json` to adjust default parameters:

- `--insecure-policy`: allows insecure image policies.
- `--override-os`: overrides the target OS type.
