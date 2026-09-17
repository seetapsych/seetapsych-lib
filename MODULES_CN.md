# 内置模块

简体中文 | [English](MODULES.md)

## SelectFace

> 从多人脸检测输出中选择一个目标人脸，用于单人脸下游流水线。

模块配置：[face_selection.yml](seetapsych_lib/modules/face_selection.yml)

| 算法包名称 | 提供属性 | 依赖属性 |
|---|---|---|
| SelectFace | `face/selection`, `face/detection` | `face/detection` |

**说明**：按最大面积或最大跟踪（带 PID 目标切换计数）策略从检测结果中选择一个人脸。

**参数**

| 名称 | 类型 | 默认值 | 可选值 | 说明与调优建议 |
|---|---|---|---|---|
| `selection_mode` | selection | `MAX_TRACKING` | `MAX_TRACKING`, `MAX` | 从多人脸中挑选的策略。`MAX_TRACKING` 加入时序稳定性，目标切换时递增 PID；`MAX` 每帧独立选取最大人脸。 |

**模型**：*(无)*

**输出属性**
- `face/selection` — [规格](https://github.com/seetapsych/seetapsych-attributes#faceselection)。
- `face/detection` — [规格](https://github.com/seetapsych/seetapsych-attributes#facedetection)。
