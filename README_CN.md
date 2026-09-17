# SeetaPsych Lib

> 面向人脸心理测量的计算机视觉工具包

简体中文 | [English](README.md)

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](pyproject.toml)
[![License](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](LICENSE)

SeetaPsych Lib 是一个基于 Python 的、面向行为心理测量的开源计算机视觉工具包，为 SeetaPsych 项目的核心库。它提供了模块化的 Pipeline / Runner 运行时，支持自定义算法模块的组合与执行，并内置快速上手的 WebUI，便于开箱即用与实验探索。

## 概述

作为 SeetaPsych 生态的基础库，其在整个开源项目矩阵中的位置如 [图 1](#figure-matrix) 所示。

<div align="center" id="figure-matrix">
  <img src="assets/matrix.png" width="840"/>
  <p><em><strong>图 1</strong> 开源项目矩阵</em></p>
</div>

本项目针对以下主要应用场景提供解决方案，概括如 [图 2](#figure-usage) 所示。

<div align="center" id="figure-usage">
  <img src="assets/usage.png" width="640"/>
  <p><em><strong>图 2</strong> 目标使用场景</em></p>
</div>

本项目通过配置文件描述可用算法以及各算法可产出的属性。属性（attribute）即算法或处理方法的输出。

[图 3](#figure-attributes) 展示了如何通过配置文件（YML）描述算法与属性。

<div align="center" id="figure-attributes">
  <img src="assets/attributes.png" width="840"/>
  <p><em><strong>图 3</strong> 配置文件（YML）及其对应属性示例</em></p>
</div>

例如，Face 模块下的 `face-hub.yml` 提供两个属性 — `face/detection` 与 `face/landmarks`。如下所示，`face/detection` 属性包含检测到的人脸边界框（`xyxy`）及其置信度评分：

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

SeetaPsych 属性在 [seetapsych-attributes](https://github.com/seetapsych/seetapsych-attributes) 仓库中定义与维护。
共享配置文件（configs）位于 [seetapsych-configs](https://github.com/seetapsych/seetapsych-configs) 仓库。

这些 YML 配置文件属于框架内部管理机制，通常无需终端用户手动编辑 — 会在需要时自动获取。

每个属性可能依赖一个或多个算法模块进行计算。

**框架的核心能力在于依赖驱动的自动化：** 用户只需声明需要获取哪些属性；框架会根据所请求属性及其声明的依赖关系，自动解析全部所需算法模块，并将它们组装为优化后的计算图。具体示例如 [图 4](#figure-graph) 所示。

<div align="center" id="figure-graph">
  <img src="assets/graph.png" width="640"/>
  <p><em><strong>图 4</strong> 根据请求属性构建的计算图示例</em></p>
</div>

计算图由 Runner 执行，用于处理图像或视频并产出所请求的属性。默认情况下，Runner 会自动检测可用硬件环境，并在检测到支持的 GPU 时优先使用 GPU 加速进行算法推理。

[图 4](#figure-graph) 示例对应的具体依赖链如下：
- 首先，输入图像经 Face 模块处理，产出 `face/landmarks` 与 `face/dense_landmarks`。
- 随后，`face/landmarks` 被 Emo 模块消费，输出 `face/expression`、`face/action_units` 与 `face/dimensional_affect`。
- `face/dense_landmarks` 输入 Hertz 模块，用于估计 `face/heart_rate` 属性。

基于依赖的组织方式使得多个属性可以在同一计算图中共享并复用中间结果，从而避免重复计算。

内置算法模块以独立子项目的形式实现。每个子项目交付一个或多个算法包（通过 `modules/*.yml` 声明），并在全局配置注册表中注册。可用的算法子项目包括：
- [FaceHub](https://github.com/seetapsych/seetapsych-face-hub) — 人脸检测（RetinaFace / MediaPipe）、5 点关键点、468 点 3D 人脸网格、ArcFace 512 维人脸特征提取。
- [FaceEx](https://github.com/seetapsych/seetapsych-face-ex) — 280 点密集人脸关键点预测，可选二次精修流程。
- [Emo](https://github.com/seetapsych/seetapsych-emo) — 多任务面部情感估计：16 个动作单元、7 类分类表情、效价-唤醒维度情感。
- [GazeScreen](https://github.com/seetapsych/seetapsych-gaze-screen) — 桌面眼动场景下，基于 AFFNet 与 TDGazeNet 的屏幕注视坐标估计。
- [GazeFollow](https://github.com/seetapsych/seetapsych-gaze-follow) — 多人头检测、每人场景级注视跟随、双人社交注视关系分类。
- [Hertz](https://github.com/seetapsych/seetapsych-hertz) — 基于 rPPG 的非接触心率估计（TinyHR 卷积波形预测器 与 AdaChrom 色度分析）。

关于共享 schema、属性契约以及全局模块注册表的更多细节，请参见以下仓库：
- [seetapsych-attributes](https://github.com/seetapsych/seetapsych-attributes)
- [seetapsych-configs](https://github.com/seetapsych/seetapsych-configs)

## 运行要求

- Python >= 3.10
- （推荐）uv 包管理器：<https://github.com/astral-sh/uv>

## 安装

### 创建虚拟环境

安装依赖前，建议使用隔离的虚拟环境。

#### 使用 uv（推荐）

```sh
# 在 .venv 处创建虚拟环境
uv venv

# 激活（bash/zsh）
source .venv/bin/activate

# 激活（PowerShell）
.venv\Scripts\Activate.ps1

# 激活（Windows CMD）
.venv\Scripts\activate.bat
```

#### 使用标准 venv

```sh
python -m venv .venv

# bash/zsh
source .venv/bin/activate

# PowerShell
.venv\Scripts\Activate.ps1

# Windows CMD
.venv\Scripts\activate.bat
```

#### 使用 conda

```sh
conda create -n seetapsych python=3.10
conda activate seetapsych
```

### 安装依赖

安装所需依赖：

- seetapsych-lib
- seetapsych-attributes
- seetapsych-configs

若要运行 WebUI，需安装 `seetapsych-lib[webui]` 包。

#### 使用 uv（推荐）

```sh
uv pip install 'seetapsych-lib[webui]' seetapsych-attributes seetapsych-configs
```

#### 使用 pip

```sh
pip install 'seetapsych-lib[webui]' seetapsych-attributes seetapsych-configs
```

## 安装默认配置

```sh
# 下载默认配置
seetapsych-manager download
# 安装各模块依赖
seetapsych-manager setup
# 下载各模型
seetapsych-manager cache
```

`setup` 与 `cache` 命令可跳过。
在后续使用 WebUI 或以编程方式调用时，`seetapsych-lib` 会按需安装依赖并下载必要的模型。

## 公共资源

随 `seetapsych-lib` 一起安装的默认模块发布并维护于 <https://github.com/seetapsych/seetapsych-configs>。

如需将内置模块升级至最新版本，请升级 configs 包并重新下载：

```sh
# 将已安装的 seetapsych-configs 升级至最新可用版本
# 使用纯 pip 时：pip install --upgrade seetapsych-configs
uv pip install --upgrade seetapsych-configs
# 重新下载最新的模块定义
seetapsych-manager download -f
```

算法输入与执行输出通过「属性（Attributes）」定义。

完整的 Attributes 规范见 <https://github.com/seetapsych/seetapsych-attributes>。

## 快速开始

### 运行 WebUI（Streamlit）

```sh
seetapsych-webui --log INFO
```

或

```sh
python -m seetapsych_lib.webui --log INFO
```

本地浏览器窗口会自动打开，也可手动访问：`http://localhost:8501`。

常用参数：

- `--dirs <DIR...>`：从目录加载模块
- `--files <FILE...>`：从本地配置文件加载模块
- `--urls <URL...>`：从远程 URL 加载模块
- `--disable-builtin`：禁用内置模块
- `--disable-default`：禁用默认模块
- `--cache-dir <DIR>`：模型缓存目录
- `--upload-dir <DIR>`：上传目录
- `--log <LEVEL>`：日志级别（如 `DEBUG`、`INFO`、`WARNING`，或整数如 `10`）

### 编程使用

```python
# -*- coding: utf-8 -*-

import json
import cv2

from seetapsych_lib.runtime.factory import Factory
from seetapsych_lib.runtime.pipeline import Pipeline
from seetapsych_lib.runtime.runner import Runner
from seetapsych_lib.runtime.parallel_runner import ParallelRunner


def main():
    # 初始化时默认加载全部已安装的算法模块
    # 可使用 load_xxx_module(s) 系列方法加载特定算法模块
    factory = Factory()

    # 快速构建工作流，声明需要计算的属性为人脸检测 'face/detection'
    # 使用 'seetapsych-manager show' 命令可查看已安装算法的全部可用属性
    # 属性的结果字段参见 https://github.com/seetapsych/seetapsych-attributes
    pipeline = Pipeline(factory, attributes=["face/detection"])

    # 使用 problem() 检查是否存在需要解决的依赖或缺失问题
    print(pipeline.problem())
    # 解析工作流依赖，自动补充人脸检测模块及对应模型
    pipeline.solve()

    # 使用 satisfied() 检查是否存在需要安装或下载才能修复的运行环境问题
    print(pipeline.satisfied())
    # 安装当前流水线运行所需的缺失依赖
    pipeline.install_requirements()
    # 下载流水线运行所需的缺失模型
    pipeline.cache_models()

    # 设置参数
    package = pipeline.get_package(provide="face/detection")
    assert package is not None
    pipeline.set_parameters(package.uid, {"input_size": [640, 640]})

    # 创建基础执行器
    runner = Runner(pipeline)
    # 或创建并行执行器
    # runner = ParallelRunner(pipeline)

    # 运行算法
    report = runner.run(data={"default": cv2.imread("image.jpg")})

    # 打印执行结果
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
```

## 内置模块

本库还附带内置算法模块。完整列表与文档见 [MODULES_CN.md](MODULES_CN.md)。

## 配置

### 环境变量

支持以下环境变量：

| 环境变量 | 说明 |
| :-- | :-- |
| SEETAPSYCH\_LOG\_LEVEL  | 更改默认日志级别。可选值：`WARNING`、`INFO`、`DEBUG`，或整数（如 `10`）。 |
| SEETAPSYCH\_CACHE\_DIR  | 模型缓存根目录。模型缓存于 `<CACHE_DIR>/models` 下。 |
| SEETAPSYCH\_CONFIG\_DIR | 配置文件根目录。配置从 `<CONFIG_DIR>/configs` 加载。 |

## 开发

### 文档字符串规范

本项目所有代码文档字符串遵循 **Google 风格** 格式（含 `Args` / `Returns` / `Raises` 段落）。完整规范见 [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings)。

### 附加开发说明

本地验证步骤（lint、类型检查、测试、构建）、标签命名约定与发布流水线见 [DEVELOPMENT.md](DEVELOPMENT.md)。
