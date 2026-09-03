# SeetaPsych Lib

> A Computer Vision Toolkit for Face-based Psychological Measurement

[![License](https://img.shields.io/badge/license-BSD-blue.svg)](LICENSE)

SeetaPsych Lib is a Python-based computer vision toolkit for face-based psychological analysis, serving as the core library of the SeetaPsych project. It provides a modular Pipeline/Runner runtime that supports the composition and execution of custom algorithm modules, and ships with a quick-start WebUI for rapid onboarding and experimentation.

## Overview

As the foundational library of the SeetaPsych ecosystem, its position within the broader open-source project matrix is illustrated in [Fig. 1](#figure-matrix).

<div align="center" id="figure-matrix">
  <img src="https://raw.githubusercontent.com/seetapsych/seetapsych-lib/main/assets/matrix.png" width="840"/>
  <p><em><strong>Figure 1.</strong> Open source project matrix</em></p>
</div>

The project provides solutions for the following primary application scenarios, as summarized in [Fig. 2](#figure-usage).

<div align="center" id="figure-usage">
  <img src="https://raw.githubusercontent.com/seetapsych/seetapsych-lib/main/assets/usage.png" width="640"/>
  <p><em><strong>Figure 2.</strong> Target Use Cases</em></p>
</div>

The project uses configuration files to describe the available algorithms and the attributes that each algorithm can produce. An attribute represents the output of an algorithm or processing method.

[Fig. 3](#figure-attributes) illustrates how algorithms and attributes are described through configuration files (YML).

<div align="center" id="figure-attributes">
  <img src="https://raw.githubusercontent.com/seetapsych/seetapsych-lib/main/assets/attributes.png" width="840"/>
  <p><em><strong>Figure 3.</strong> Examples of configuration files (YML) and their corresponding attributes</em></p>
</div>

For example, `face-hub.yml` (under the Face module) provides two attributes — `face/detection` and `face/landmarks`. The `face/detection` attribute, shown below, contains the detected face bounding box (`xyxy`) and its confidence score:

```json
{
  "face_detection": [
    {
      "xyxy": [
        128.772,
        158.999,
        286.546,
        369.401
      ],
      "score": 0.802
    }
  ]
}
```

SeetaPsych attributes are defined and maintained in the [seetapsych-attributes](https://github.com/seetapsych/seetapsych-attributes) repository.  
The shared configuration files (configs) live in the [seetapsych-configs](https://github.com/seetapsych/seetapsych-configs) repository.

These YML configuration files are part of the framework's internal management mechanism and typically do not require manual editing by end users — they are fetched automatically when needed.

Each attribute may depend on one or more algorithm modules for computation.

**The key capability of the framework is dependency-driven automation:** users only need to specify which attributes they want to obtain. Based on the requested attributes and their declared dependencies, the framework automatically resolves all required algorithm modules and assembles them into an optimized computation graph. A concrete example is shown in [Fig. 4](#figure-graph).

<div align="center" id="figure-graph">
  <img src="https://raw.githubusercontent.com/seetapsych/seetapsych-lib/main/assets/graph.png" width="640"/>
  <p><em><strong>Figure 4.</strong> Example of a computation graph constructed from requested attributes</em></p>
</div>

The computation graph is executed by a Runner, which processes images or videos and produces the requested attributes. By default, the Runner automatically detects the available hardware environment and prioritizes GPU acceleration for algorithm inference when a supported GPU is present.

The example in [Fig. 4](#figure-graph) walks through a concrete dependency chain aligned with the diagram:
- First, the input image is processed by the Face module, which produces `face/landmarks` and `face/dense_landmarks`.
- `face/landmarks` is then consumed by the Emo module, which outputs `face/expression`, `face/action_units`, and `face/dimensional_affect`.
- `face/dense_landmarks` feeds into the Hertz module, which estimates the `face/heart_rate` attribute.

This dependency-based organization enables multiple attributes to share and reuse intermediate results within a single computation graph, avoiding redundant computation.

For further details, refer to the following repositories:
- [seetapsych-attributes](https://github.com/seetapsych/seetapsych-attributes)
- [seetapsych-configs](https://github.com/seetapsych/seetapsych-configs)

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
pip install 'seetapsych-lib[webui]' seetapsych-attributes seetapsych-configs
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
# Upgrade the installed seetapsych-configs package to the latest available version
# For plain pip: pip install --upgrade seetapsych-configs
uv pip install --upgrade seetapsych-configs
# Re-download the latest module definitions
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

    # Set parameters
    package = pipeline.get_package(provide="face/detection")
    assert package is not None
    pipeline.set_parameters(package.uid, {"input_size": [640, 640]})

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

## Built-in Modules

This library also ships with built-in algorithm modules. See the full list and documentation in [MODULES.md](https://github.com/seetapsych/seetapsych-lib/blob/main/MODULES.md).

## Configuration

### Environment Variables

The following environment variables are supported:

| Env                     | Description                                                                                |
| :---------------------- | :----------------------------------------------------------------------------------------- |
| SEETAPSYCH\_LOG\_LEVEL  | Change default log level. Could be `WARNING`, `INFO`, `DEBUG`, or an integer (e.g., `10`). |
| SEETAPSYCH\_CACHE\_DIR  | Base directory for model cache. Models are cached under `<CACHE_DIR>/models`.              |
| SEETAPSYCH\_CONFIG\_DIR | Base directory for config files. Config files are loaded from `<CONFIG_DIR>/configs`.      |
