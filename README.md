# SeetaPsych Lib

> A Computer Vision Toolkit for Face-based Psychological Measurement

[![License](https://img.shields.io/badge/license-BSD-blue.svg)](LICENSE)

SeetaPsych Lib is a Python library for face and body-based psychology analysis.
It provides a modular Pipeline/Runner runtime and an optional Streamlit WebUI.

## Requirements

- Python >= 3.10
- (Recommended) uv package manager: <https://github.com/astral-sh/uv>

## Installation

### Create Virtual Environment

It is recommended to use an isolated virtual environment before installing dependencies.

#### Using uv (recommended)

```sh
# Create a virtual environment at .venv
uv venv

# Activate (bash/zsh)
source .venv/bin/activate

# Activate (PowerShell)
.venv\Scripts\Activate.ps1

# Activate (Windows CMD)
.venv\Scripts\activate.bat
```

#### Using standard venv

```sh
python -m venv .venv

# bash/zsh
source .venv/bin/activate

# PowerShell
.venv\Scripts\Activate.ps1

# Windows CMD
.venv\Scripts\activate.bat
```

#### Using conda

```sh
conda create -n seetapsych python=3.10
conda activate seetapsych
```

### Install Dependencies

Install the required dependencies:

- seetapsych-lib
- seetapsych-attributes
- seetapsych-configs

To run the WebUI, you need to install the `seetapsych-lib[webui]` package.

#### Using uv (recommended)

```sh
uv pip install 'seetapsych-lib[webui]' seetapsych-attributes seetapsych-configs
```

#### Using pip

```sh
pip install seetapsych-lib[webui] seetapsych-attributes seetapsych-configs
```

## Install Default Configs

```sh
# download default configs
seetapsych-manager download
# install each module requirements
seetapsych-manager setup
# download each model
seetapsych-manager cache
```

The `setup` and `cache` commands can be skipped.
When you use the WebUI or call the library programmatically later, `seetapsych-lib` can install dependencies and download necessary models on demand.

## Public Resources

The default modules installed with `seetapsych-lib` are published and maintained at <https://github.com/seetapsych/seetapsych-configs>.

To update the built-in modules to their latest versions, upgrade the configs package and re-download:

```sh
uv pip compile --upgrade-package seetapsych-configs
seetapsych-manager download -f
```

Algorithm inputs and execution outputs are defined via `Attributes`.

The full Attributes specification is available at <https://github.com/seetapsych/seetapsych-attributes>.

## Quick Start

### Run WebUI (Streamlit)

```sh
seetapsych-webui --log INFO
```

or

```sh
python -m seetapsych_lib.webui --log INFO
```

A local browser window will open automatically, or you can manually navigate to: `http://localhost:8501`.

Common arguments:

- `--dirs <DIR...>`: load modules from directories
- `--files <FILE...>`: load modules from local config files
- `--urls <URL...>`: load modules from remote URLs
- `--disable-builtin`: disable builtin modules
- `--disable-default`: disable default modules
- `--cache-dir <DIR>`: model cache directory
- `--upload-dir <DIR>`: upload directory
- `--log <LEVEL>`: log level (e.g., `DEBUG`, `INFO`, `WARNING`, or an integer like `10`)

### Programmatic Usage

```python
# -*- coding: utf-8 -*-

import json
import cv2

from seetapsych_lib.runtime.factory import Factory
from seetapsych_lib.runtime.pipeline import Pipeline
from seetapsych_lib.runtime.runner import Runner
from seetapsych_lib.runtime.parallel_runner import ParallelRunner


def main():
    # All installed algorithm modules are loaded by default during initialization
    # You can use the `load_xxx_module(s)` methods to load specific algorithm modules
    factory = Factory()

    # Quickly build a workflow and declare the attribute to compute as the face feature 'face/detection'
    # You can view all available attributes of installed algorithms using the `seetapsych-manager show` command
    # Result fields for attributes can be found at https://github.com/seetapsych/seetapsych-attributes
    pipeline = Pipeline(factory, attributes=["face/detection"])

    # Check for dependencies or missing issues that need to be resolved with solve()
    print(pipeline.problem())
    # Resolve workflow dependencies, automatically add face detection and corresponding models
    pipeline.solve()

    # Check for runtime environment issues that require installation or download to fix
    print(pipeline.satisfied())
    # Install missing dependencies required for the current pipeline to run
    pipeline.install_requirements()
    # Download missing models required for the pipeline to run
    pipeline.cache_models()

    # Create a basic executor
    runner = Runner(pipeline)
    # Or create a parallel executor
    # runner = ParallelRunner(pipeline)

    # Run the algorithm
    report = runner.run(data={"default": cv2.imread("image.jpg")})

    # Print the execution results
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

## Configuration

### Environment Variables

The following environment variables are supported:

| Env                     | Description                                                                                |
| :---------------------- | :----------------------------------------------------------------------------------------- |
| SEETAPSYCH\_LOG\_LEVEL  | Change default log level. Could be `WARNING`, `INFO`, `DEBUG`, or an integer (e.g., `10`). |
| SEETAPSYCH\_CACHE\_DIR  | Base directory for model cache. Models are cached under `<CACHE_DIR>/models`.              |
| SEETAPSYCH\_CONFIG\_DIR | Base directory for config files. Config files are loaded from `<CONFIG_DIR>/configs`.      |

