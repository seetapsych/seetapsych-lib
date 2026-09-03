# Built-in Modules

## SelectFace

> Select one target face from multi-face detection outputs for single-face downstream pipelines.

Module config: [face_selection.yml](seetapsych_lib/modules/face_selection.yml)

| Package Name | Provides Attributes | Requires Attributes |
|---|---|---|
| SelectFace | `face/selection`, `face/detection` | `face/detection` |

**Description**: Select one face from detections by max area or max-tracking with PID increments on target change.

**Parameters**

| Name | Type | Default | Selection | Description & Tuning |
|---|---|---|---|---|
| `selection_mode` | selection | `MAX_TRACKING` | `MAX_TRACKING`, `MAX` | Strategy for selecting from multiple faces. `MAX_TRACKING` adds temporal stability and increments PID on target switch; `MAX` picks the largest face every frame. |

**Models**: *(None)*

**Output Attributes**
- `face/selection` — [spec](https://github.com/seetapsych/seetapsych-attributes#faceselection).
- `face/detection` — [spec](https://github.com/seetapsych/seetapsych-attributes#facedetection).
