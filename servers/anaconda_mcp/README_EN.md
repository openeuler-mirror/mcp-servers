# Anaconda MCP Server

It is an MCP server implementation for managing Anaconda environments.

## Features

- Conda Environment Management
  - Activate/deactivate environments (**conda_activate**/**conda_deactivate**)
  - List environments (**conda_env_list**)
  - Create environments (**conda_create**)
- Package Management
  - Install packages (**conda_install**)
  - List installed packages (**conda_list**)
  - Update packages (**conda_update**)

## Installation

1. Install Python 3.8+ and Conda.

2. Install dependencies:

    ```bash
    pip install -r src/requirements.txt
    ```

3. Start the server:

    ```bash
    python src/server.py
    ```
