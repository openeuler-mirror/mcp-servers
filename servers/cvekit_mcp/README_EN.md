# CVE Patch Processing Service for the Code Repository Gitee

## Installation Guide

1. Install dependencies.

    ```bash
    cd servers/cvekit_mcp/src && pip install -r requirements.txt
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

In the MCP configuration file, you can add the **env** field to set the language.

Set the language to Chinese for the MCP

```json
      "env": {
        "LANG": "zh_CN.UTF-8"
      },
```

Set the language to English for the MCP

```json
      "env": {
        "LANG": "en_US.UTF-8"
      },
```

## Function Overview

1. Configure environment variables.

    ```bash
    # Configure the repository address.
    export REPO_URL=${REPO_URL} 
    # Configure the fork repository address.
    export FORK_REPO_URL=${FORK_REPO_URL}
    # Configure a Gitee personal token.
    export GITEE_TOKEN=${GITEE_TOKEN}
    # Configure the user signature.
    export SIGNER_NAME=${SIGNER_NAME}
    # Configure the user email address.
    export SIGNER_EMALI=${SIGNER_EMAIL}

    # (Optional) Configure the foundation model provider and key.
    # Use the cloud model as an example (**API_KEY** is required):
    # export LLM_PROVIDER=openai
    # export API_KEY=<your_llm_api_key>
    #
    # Use the local authentication-free model as an example (only when the local service provides the OpenAI-compatible /v1/chat/completions API):
    # export LLM_PROVIDER=local
    # export MODEL_NAME=codellama-32b-instruct # or your local model name
    # # If the local model does not need to be authenticated, you do not need to set **API_KEY**. Otherwise, set **API_KEY**.
    # export API_KEY=<optional_local_llm_token>
    ```

2. Parse issues.

    ```bash
    cvekit --action parse-issue --cve-id ${CVE_ID}
    ```

    **CVE_ID** indicates the ID of the CVE to be repaired.

3. Clone the Linux and kernel source code.

    ```bash
    cvekit --action setup-env
    ```

4. Obtain the introduced and fixed commit IDs.

    ```bash
    cvekit --action get-commits --cve-id ${CVE_ID}
    ```

5. Analysis and repair branches.

    ```bash
    cvekit --action analyze-branches --cve-id ${CVE_ID}
    ```

6. Apply patches.

    ```bash
    cvekit --action apply-patch --cve-id ${CVE_ID} --patch-path ${PATCH_PATH}
    ```

7. Create a PR.

    ```bash
    cvekit --action create-pr --cve-id ${CVE_ID} --branch ${BRANCH_NAME}
    ```

8. Resolve patch conflicts.

    ```bash
    cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} --api-key ${API_KEY} --llm-provider ${LLM_PROVIDER}
    ```

    Use a fully customized LLM (any OpenAI-compatible service):

    ```bash
    # --llm-provider supports any value and is used together with --llm-base-url and --llm-model-name.
    cvekit --action backport --cve-id ${CVE_ID} --branch ${BRANCH_NAME} \
      --llm-provider my-provider \
      --llm-base-url https://api.example.com/v1 \
      --llm-model-name gpt-4o-mini \
      --api-key ${API_KEY}
    ```

    **LLM configuration priority** (in descending order):

    a. Command line parameters: `--llm-provider`, `--llm-base-url`, and `--llm-model-name`
    b. Environment variables: `LLM_PROVIDER`, `LLM_BASE_URL`, and `LLM_MODEL_NAME` (or `MODEL_NAME`)
    c. Preset: `openai` (default)

9. Batch backport (backport-batch)

    `backport-batch` uses a YAML/JSON configuration file to check and backport data in batches and generates a `*.report.yml` report file for rerun and manual confirmation. Configuration files can be generated from Excel files, and patches can be directly applied and signed.

    - **Dependency description**: This function depends on `GitPython` (providing `import git`) and `PyYAML`. If the interactive mode (`-i/--interactive`) is enabled, you are advised to install `tabulate` for table display. If the Excel input function is used, you need to install `openpyxl` (included in `requirements.txt`).

### Generating a Configuration File from an Excel File

You can use the `--backport-excel` option to generate a configuration file from an Excel file. This is suitable for batch processing of a large number of commits.

```bash
# Generate a configuration file from an Excel file.
cvekit --action backport-batch --backport-excel ./950_commit.xlsx -o ./test.yml --backport-config ./demo.yml
```

### Configuration File (Raw Mode)

The raw configuration is used for batch check and report generation. By default, commits are sorted, merge/conflict detection is performed, and `${backport-config}.report.yml` is generated. **The backporting result is not directly implemented in the target repository** (for preliminary investigation).

Example (Do not write the token or API key into the file. You are advised to use environment variables or command lines to transfer parameters.)

```yaml
project: linux
project_url: https://gitee.com/openeuler/kernel
project_dir: /path/to/source-repo
source_branch: OLK-6.6              # optional: used for preferential filtering when multiple candidate titles are matched.
target_path: /path/to/target-repo
target_release: openEuler-24.03-LTS-SP1-patchpool
patch_dataset_dir: /path/to/patch_dataset
llm_provider: minimax               # optional: used for backporting in report mode.
api_key: ${API_KEY}                 # It is advised to use environment variables or the **--api-key** command line.
commits:
- commit: 2d1a8bfb61ec
  commit_title: 'etm4x: Fix etm4_count race by moving cpuhp callbacks to init'
- commit: 16a0cbac6609
  commit_title: 'drivers: arch_topology: Refactor do-while loops'
```

Running:

```bash
# Pass through the installed entry (after python setup.py install).
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json

# Or directly use the module (more intuitive for development and debugging).
python -m cvekit.cli --action backport-batch --backport-config /path/to/backport-batch.yml --debug --json
```

### Report File (Report Mode)

If the configuration file name extension is `.report.yml` (or the commits entry contains fields such as `merged_in_target/has_conflict/...`), it is considered as a report configuration.

The report configuration is used for "execution by report":

- **merged_in_target=true**: Skip
- **has_conflict=true**: Trigger backport (by calling the `backport` process/LLM).
- **has_conflict=false**: Try to apply `cherry-pick` directly in the target repository.

Run (optional interactive editing):

```bash
cvekit --action backport-batch --backport-config /path/to/backport-batch.yml.report.yml -i --debug --json
```

### Applying Specific Patches and Signing Them

You can use `--apply` to specify a specific commit for application and use `--signer-name` and `--signer-email` to add a signature to the commit.

```bash
# Apply specific patches and sign them.
cvekit --action backport-batch --backport-config test.yml.filtered.report.yml --json --debug --apply 71544d0b1de3 --signer-name "dev" --signer-email "dev@xx.com" -i
```

### Complete Workflow

1. **Generating Configurations from Excel**

   ```bash
   cvekit --action backport-batch --backport-excel ./950_commit.xlsx -o ./test.yml --backport-config ./demo.yml
   ```

2. **Generating a Report**

   ```bash
   cvekit --action backport-batch --backport-config ./test.yml --debug
   ```

3. **Viewing the Generated Report**

   ```bash
   cat test.yml.report.yml
   ```

4. **Performing Interactive Backport**

   ```bash
   cvekit --action backport-batch --backport-config test.yml.report.yml --debug -i
   ```

5. **Applying Specific Patches and Signing Them**

   ```bash
   cvekit --action backport-batch --backport-config test.yml.filtered.report.yml --json --debug --apply 71544d0b1de3 --signer-name "dev" --signer-email "dev@xx.com" -i
   ```

Notes

- You are advised to use environment variables to pass sensitive information, such as `GITEE_TOKEN` and `API_KEY`, or run the `--gitee-token/--api-key` command to pass sensitive information.
- `backport-batch` writes a report file. Pay attention to the `*.report.yml` file generated in the same directory and use it as the input for the next round.
- When using the Excel input function, ensure that the `openpyxl` dependency `pip install openpyxl` has been installed.
