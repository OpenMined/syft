# SyftBox SDK Documentation

## Overview

The SyftBox SDK provides an interface for managing datasites and permissions of SyftBox.

## Installation

```python
# Package installation (assuming it's published on PyPI)
pip install syftbox-sdk
```

## Configuration

The SDK requires a configuration file located at `~/.syftbox/client_config.json` by default. The configuration file should contain:

```json
{
  "sync_folder": "/path/to/data/directory",
  "email": "user@example.com"
}
```

You can override the config file location using the `SYFTBOX_CLIENT_CONFIG_PATH` environment variable.

## Basic Usage

### Initializing the client Context

```python
from syftbox_sdk import SyftBoxContext

# Method 1: Initialize directly
ctx = SyftBoxContext(data_dir="/path/to/data", email="user@example.com")

# Method 2: Load from config file
ctx = SyftBoxContext.load()
```

### Managing Data Directories

```python
# Get user's personal datasite directory
my_datasite = ctx.get_datasite()
# Result: /path/to/data/user@example.com

# Get another user's datasite directory
other_datasite = ctx.get_datasite("other@example.com")
# Result: /path/to/data/other@example.com

# Get application data directory
app_data = ctx.get_app_data("my_app")
# Result: /path/to/data/user@example.com/app_pipelines/my_app

# Create directories
ctx.make_dirs(my_datasite, app_data)
```

### Managing Permissions

```python
from syftbox_sdk.permissions import EVERYONE

# Set directory as writable by everyone
data_path = ctx.get_datasite() / "public_data"
ctx.set_writable(data_path)

# Set directory as readable by everyone but writable only by specific users
restricted_path = ctx.get_datasite() / "restricted_data"
ctx.set_readable(restricted_path, readers=EVERYONE)

# Set directory with specific writers
ctx.set_writable(data_path, writers=["user1@example.com", "user2@example.com"])
```

## Common Patterns

### Setting Up Application Workspace

```python
def setup_app_workspace(ctx: SyftBoxContext, app_name: str):
    # Get app data directory
    app_dir = ctx.get_app_data(app_name)

    # Create necessary subdirectories
    input_dir = app_dir / "input"
    output_dir = app_dir / "output"
    ctx.make_dirs(input_dir, output_dir)

    # Set appropriate permissions, input readable by everyone (default)
    ctx.set_readable(input_dir)
    # output writable by only user1@test.com
    ctx.set_writable(output_dir, writers=["user1@test.com"])

    return app_dir
```
