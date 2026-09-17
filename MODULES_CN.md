# 内置算法模块

简体中文 | [English](MODULES.md)

## SelectFace

> 从多人脸检测结果中筛选一张目标人脸，供单人下游流水线使用。

模块配置：[face_selection.yml](seetapsych_lib/modules/face_selection.yml)

| 算法包名称 | 提供属性 | 依赖属性 |
|---|---|---|
| SelectFace | `face/selection`, `face/detection` | `face/detection` |

**说明**：从人脸检测结果中按策略选取一张人脸，支持最大面积优先或最大跟踪优先（带 PID 目标切换计数机制）两种策略。

**参数**

| 名称 | 类型 | 默认值 | 可选值 | 说明与调优建议 |
|---|---|---|---|---|
| `selection_mode` | selection | `MAX_TRACKING` | `MAX_TRACKING`, `MAX` | 多人脸筛选策略。`MAX_TRACKING` 引入时序稳定性，目标切换时 PID 计数器递增；`MAX` 则逐帧独立选取面积最大的人脸。 |

**模型**：*(无)*

**输出属性**
- `face/selection` — [规格定义](https://github.com/seetapsych/seetapsych-attributes#faceselection)。
- `face/detection` — [规格定义](https://github.com/seetapsych/seetapsych-attributes#facedetection)。
