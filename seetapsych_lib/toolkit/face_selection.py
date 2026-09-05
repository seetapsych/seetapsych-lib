# -*- coding: utf-8 -*-

import copy
from typing import TypedDict, cast


class Detection(TypedDict):
    """Rectangular face detection result with confidence score.

    Matches ``seetapsych_attributes.types.BBox`` contract (xyxy + score).
    Exposed publicly for type annotations by callers such as
    ``toolkit.packages.face_selection``.
    """

    # [x1, y1, x2, y2] -- pixel-coordinate bounding box
    xyxy: list[float]
    # detection confidence in [0, 1]
    score: float


class _WorkingDetection(Detection, total=False):
    """Internal-only extension of Detection with transient scratch fields.

    Fields declared here are written *only* on deep-copied local lists
    inside ``max_select`` / ``max_tracking`` and must never leak into the
    original ``Detection`` instances supplied by callers. Using
    ``total=False`` makes every declared field ``NotRequired``, matching
    the reality that each helper sets only a subset of these during
    processing.
    """

    _area: float
    _index: int
    _iou: float


def calculate_iou(det1: Detection, det2: Detection) -> float:
    """
    Calculate IoU of two bounding boxes in xyxy format.

    Args:
        det1: Detection with xyxy = [x1, y1, x2, y2]
        det2: Detection with xyxy = [x1, y1, x2, y2]

    Returns:
        IoU value in range [0.0, 1.0]
    """
    x1_min, y1_min, x1_max, y1_max = det1["xyxy"]
    x2_min, y2_min, x2_max, y2_max = det2["xyxy"]

    # Calculate intersection rectangle
    inter_x_min = max(x1_min, x2_min)
    inter_y_min = max(y1_min, y2_min)
    inter_x_max = min(x1_max, x2_max)
    inter_y_max = min(y1_max, y2_max)

    inter_width = max(0.0, inter_x_max - inter_x_min)
    inter_height = max(0.0, inter_y_max - inter_y_min)
    inter_area = inter_width * inter_height

    # Calculate areas of both boxes
    area1 = max(0.0, x1_max - x1_min) * max(0.0, y1_max - y1_min)
    area2 = max(0.0, x2_max - x2_min) * max(0.0, y2_max - y2_min)

    union_area = area1 + area2 - inter_area

    if union_area <= 0.0:
        return 0.0

    return cast(float, inter_area / union_area)


def max_select(detections: list[Detection]) -> int:
    if not detections:
        return -1

    if len(detections) == 1:
        return 0

    working: list[_WorkingDetection] = cast(list[_WorkingDetection], copy.deepcopy(detections))
    for i, det in enumerate(working):
        x1, y1, x2, y2 = det["xyxy"]
        det["_area"] = (x2 - x1) * (y2 - y1)
        det["_index"] = i

    working.sort(key=lambda x: x["_area"], reverse=True)
    return int(working[0]["_index"])


def max_tracking(detections: list[Detection], pre_selection: Detection | None = None) -> tuple[int, bool]:
    """Select a detection using area + IoU-based temporal smoothing.

    Prefers the previous selection when the current closest IoU neighbour is
    above ``iou_threshold`` and its area is still within ``switch_ratio`` of
    the largest box. Falls back to the largest detection otherwise.

    Args:
        detections: Current frame detections (xyxy + score).
        pre_selection: Detection chosen in the previous frame, if any.

    Returns:
        A 2-tuple ``(index, changed)`` where ``index`` is the selected
        position in ``detections`` (``-1`` if empty) and ``changed``
        indicates whether the selection differs from ``pre_selection``.
    """
    iou_threshold = 0.3
    switch_ratio = 0.5

    if not detections:
        return -1, False

    working: list[_WorkingDetection] = cast(list[_WorkingDetection], copy.deepcopy(detections))
    for i, det in enumerate(working):
        x1, y1, x2, y2 = det["xyxy"]
        det["_area"] = (x2 - x1) * (y2 - y1)
        det["_index"] = i

    working.sort(key=lambda x: x["_area"], reverse=True)

    if pre_selection is None:
        # select max detection target
        return int(working[0]["_index"]), True

    max_area = working[0]["_area"]
    # selected closed target
    for det in working:
        det["_iou"] = calculate_iou(det, pre_selection)

    iou_detections: list[_WorkingDetection] = cast(list[_WorkingDetection], copy.deepcopy(working))
    iou_detections = [det for det in iou_detections if det["_iou"] > iou_threshold]
    iou_detections.sort(key=lambda x: x["_iou"], reverse=True)

    if not iou_detections:
        # select max target while no detection in near area
        return int(working[0]["_index"]), True

    if iou_detections[0]["_area"] / max_area < switch_ratio:
        # the other max detection is greater the closest detection as switch ratio description
        return int(working[0]["_index"]), True

    return int(iou_detections[0]["_index"]), False


def main():
    pass


if __name__ == "__main__":
    main()
