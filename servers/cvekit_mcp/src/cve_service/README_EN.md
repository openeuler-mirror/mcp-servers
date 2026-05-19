# Installation Procedure

## Installing Dependencies Required by the Service

Install the oegitext plugin for committing PRs.

```bash
yum install oegitext
```

To resolve patch conflicts, ctags needs to be installed. However, the openEuler repository does not contain ctags. Therefore, the image source in Fedora needs to be introduced.

```bash
wget https://dl.fedoraproject.org/pub/fedora/linux/releases/42/Everything/source/tree/Packages/c/ctags-6.1.0-2.fc42.src.rpm
```

Build a ctags image source.

Install the development tool group for building compilation tools such as GCC and Make.

```bash
sudo dnf groupinstall -y "Development Tools"
rpmbuild --rebuild ctags-6.1.0-2.fc42.src.rpm

# To the rpmbuild directory
cd ~/rpmbuild/RPMS/

# Install the binary RPM package. Replace its name with the actual one.
dnf install -y ctags-6.1.0-2.fc42.x86_64.rpm
```

Install the uv python management tool.

```bash
yum install -y uv
```

Install the Python dependency.

```bash
# Start the virtual environment.
cd cve_service
uv venv
# Install dependencies.
uv sync -i https://mirrors.aliyun.com/pypi/simple/

# Activate the environment.
source .venv/bin/activate
``` 

Decompress the package.
Decompress the `camel.tar.gz` package in the `cve_service` directory to the `cve_service` directory (retain the original directory structure).

```bash
tar -zxvf camel.tar.gz
```

## Deploying the cvekit_mcp Tool

1. Install dependencies.

    ```bash
    cd servers/cvekit_mcp/src && pip install babel
    ```

2. Compile the language package.

    The cvekit uses the gettext module to support multiple languages. Before executing the code, compile the language package to convert the PO file in text format into an MO file.

    Extract translatable strings.

    ```bash
    pybabel extract -k i18n -o messages.pot .
    ```

    Update the translation directory.

    ```bash
    pybabel update -i messages.pot -d cvekit/locales
    ```

    Compile the message directory.

    ```bash
    pybabel compile -d cvekit/locales
    ```

    Note: If the code is not modified, you only need to translate the message directory. If new strings are added for translation, modify the **messages.po** file in the corresponding language in **cvekit/locales**.

3. Perform the installation.

    ```bash
    python3 setup.py install
    ```

## Setting the Language

The cvekit sets the language by reading **LANG** in the environment variable.

Set the language to Chinese:

```bash
export LANG=zh_CN.UTF-8
```

Set the language to English:

```bash
export LANG=en_US.UTF-8
```

## Others

In the current directory of the repository, create and configure the environment file `.env`. The following is an example of common configurations:

```bash
# Gitee access token (used to read issues, submit comments, and perform operations on repositories)
GITEE_TOKEN=<gitee_token>

# LLM providers. The options are as follows:
#   - OpenAI official API (default)
#   - DeepSeek official API
#   - SiliconFlow-hosted DeepSeek model (recommended for environments in the Chinese mainland)
#   - Local or self-built OpenAI-compatible model service (authentication-free)
#   - <Any value>: any custom OpenAI-compatible service (must be used together with LLM_BASE_URL).
LLM_PROVIDER=openai

# Unified LLM API key (whichever LLM_PROVIDER is used)
API_KEY=<llm_api_key>

# Default model type (used only by some providers; retain the default value in most cases)
DEFAULT_MODEL_TYPE="deepseek-ai/DeepSeek-V3"

# (Optional) Use a fully customized LLM service (any OpenAI-compatible API).
# To use a non-preset LLM service, configure the following variables:
# LLM_BASE_URL=https://api.example.com/v1 #: basic URL of the custom LLM API
# LLM_MODEL_NAME=gpt-4o-mini               # custom model name

# Local configuration file (generally no modification is required.)
DEFAULT_LOCAL_CONFIG="mcp_settings.json"

# Code clone directory (the target repository will be cloned to this directory during CVE handling.)
DEFAULT_CLONE_PATH="~/Image"

# Default target repository and fork repository
DEFAULT_TARGET_REPO="https://gitcode.com/openeuler/kernel"
DEFAULT_FORK_REPO="https://gitcode.com/devstation-robot/kernel"

# Default list of branches to be concerned
DEFAULT_BRANCHES="OLK-6.6, OLK-5.10, openEuler-1.0-LTS"
```

### Using a Local LLM (Local Provider)

If you have a locally deployed LLM service that provides **OpenAI-compatible APIs** (such as `/v1/chat/completions`),
you can enable the local model using `LLM_PROVIDER=local`:

```bash
# Using a local model (authentication-free example)
LLM_PROVIDER=local

# Local model name (you can change it to your own model name as needed.)
MODEL_NAME="codellama-32b-instruct"

# If the local service does not require authentication, you do not need to set **API_KEY**.
# If authentication is required, you can configure any token accepted by the local service.
# API_KEY="<your_local_llm_token>"
```

Requirements:

- The local service must implement the OpenAI-compatible Chat Completion API. For example:
  - `http://127.0.0.1:5000/v1/chat/completions`
- The value of `MODEL_NAME` must be the same as the actual model name provided by your local service.
- If `LLM_PROVIDER=local` is set but `API_KEY` is not set, the system uses a placeholder key, and the backend request still contains an Authorization header.
  The local service can choose to ignore or verify this header.

### Using a Fully-Custom LLM Service (Any Provider Value)

If you need to use any third-party LLM service (such as an internally-deployed model or a niche cloud service provider),
you can set any `LLM_PROVIDER` value (such as `custom`, `internal`, or `my-llm`)
to use it together with `LLM_BASE_URL` and `LLM_MODEL_NAME`.

```bash
# Use custom LLM services.
LLM_PROVIDER=my-provider
LLM_BASE_URL=https://api.example.com/v1
LLM_MODEL_NAME=gpt-4o-mini
API_KEY=<your_api_key>
```

**Configuration priority** (in descending order):

1. Command line parameters: `--llm-provider`, `--llm-base-url`, and `--llm-model-name`
2. Environment variables: `LLM_PROVIDER`, `LLM_BASE_URL`, and `LLM_MODEL_NAME` (or `MODEL_NAME`)
3. Preset: automatically selected based on `LLM_PROVIDER`
Configure the MCP configuration file **mcp_settings.json**.

```shell
{
  "mcpServers": {
    "cvekit_mcp": {
      "command": ".venv/bin/python",
      "env": {
        "LANG": "en_CN.UTF-8",
        "PYTHONPATH": "../cvekit_mcp/src"
      },
      "args": [
        "path_to/cvekit_mcp/src/server.py",
        "--gitee-token", 
        "xxx",
        "--llm-provider",
        "deepseek",
        "--api-key",
        "xxx"
      ],
      "disabled": false,
      "alwaysAllow": [],
      "description": "CVE patch processing service of the code repository Gitee"
      "timeout": 1200
    }
  }
}
```

## Running

### Step 1: Run the server.

```bash
python app_server.py
```

### Step 2: Run the client.

```shell
# For the task CVE branch analysis and adaptation check, run the following command:
python app_client.py --action branches-analysis --cve-id <CVE-ID> 
# For the task CVE patch application and PR creation, run the following command:
python app_client.py --action patch-apply-pr-creation --cve-id <CVE-ID> --branches <branches> --signer-name <signer-name> --signer-email <signer-email>
# Run the entire CVE repair process.
python app_client.py --action pipeline --cve-id <CVE-ID> --branches <branches> --signer-name <signer-name> --signer-email <signer-email>
```
