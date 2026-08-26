# SeetaPsych Lib

> A Computer Vision Toolkit for Face-based Psychological Measurement

[![License](https://img.shields.io/badge/license-BSD-blue.svg)](LICENSE)

SeetaPsych Lib is a Python library for face and body-based psychology analysis.
It provides a modular Pipeline/Runner runtime and an optional Streamlit WebUI.

## Requirements

- Python >= 3.10
- (Recommended) uv package manager: https://github.com/astral-sh/uv

## Installation

### Using uv (recommended)

```sh
uv pip install seetapsych-lib[webui] seetapsych-attributes seetapsych-configs
```

### Using pip

Install runtime dependencies:

```sh
pip install seetapsych-lib seetapsych-attributes seetapsych-configs
```

If you want to run the WebUI, install extra tools manually:

```sh
pip install seetapsych-lib[webui]
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
import numpy as np

from seetapsych_lib.api import Device
from seetapsych_lib.runtime import Factory, Pipeline, Runner

factory = Factory(enable_example=True)

pkg = next(p for p in factory.packages if p.name == "Example Package")

pipeline = Pipeline(factory, packages=[pkg.uid])
pipeline.add_model(pkg.uid, pkg.models[0].uid)
pipeline.solve()

ok, _ = pipeline.satisfied()
if not ok:
    pipeline.install_requirements()

runner = Runner(pipeline, device=Device("cpu"))
result = runner.run(np.zeros((64, 64, 3), dtype=np.uint8))
print(result)
```

## Configuration

### Environment Variables

The following environment variables are supported:

| Env               | Description                                                                      |
|:------------------|:---------------------------------------------------------------------------------|
| SEETAPSYCH_LOG_LEVEL | Change default log level. Could be `WARNING`, `INFO`, `DEBUG`, or an integer (e.g., `10`). |
| SEETAPSYCH_CACHE_DIR | Base directory for model cache. Models are cached under `<CACHE_DIR>/models`.     |
| SEETAPSYCH_CONFIG_DIR | Base directory for config files. Config files are loaded from `<CONFIG_DIR>/configs`. |
