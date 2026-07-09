# -*- coding: utf-8 -*-

import copy
from typing import List, Tuple, TypedDict


class Detection(TypedDict):
    xyxy: List[float]
    score: float


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

    return inter_area / union_area


def max_select(detections: list[Detection]) -> int:
    if not detections:
        return -1

    if len(detections) == 1:
        return 0
    
    detections = copy.deepcopy(detections)
    for i, det in enumerate(detections):
        x1, y1, x2, y2 = det['xyxy']
        det['$area'] = (x2 - x1) * (y2 - y1)
        det['$index'] = i

    detections.sort(key=lambda x: x['$area'], reverse=True)
    return detections[0]['$index']


def max_tracking(detections: list[Detection], pre_selection: Detection | None = None) -> Tuple[int, bool]:
    """
    :param detections: current detections
    :param pre_selection: previous detection
    :return: target index and whether it was changed or not
    """
    iou_threshold = 0.3
    switch_ratio = 0.5

    if not detections:
        return -1, False

    detections = copy.deepcopy(detections)
    for i, det in enumerate(detections):
        x1, y1, x2, y2 = det['xyxy']
        det['$area'] = (x2 - x1) * (y2 - y1)
        det['$index'] = i

    detections.sort(key=lambda x: x['$area'], reverse=True)

    if pre_selection is None:
        # select max detection target
        return detections[0]['$index'], True

    max_area = detections[0]['$area']
    # selected closed target
    for det in detections:
        det['$iou'] = calculate_iou(det, pre_selection)

    iou_detections = copy.deepcopy(detections)
    iou_detections = [det for det in iou_detections if det['$iou'] > iou_threshold]
    iou_detections.sort(key=lambda x: x['$iou'], reverse=True)

    if not iou_detections:
        # select max target while no detection in near area
        return detections[0]['$index'], True

    if iou_detections[0]['$area'] / max_area < switch_ratio:
        # the other max detection is greater the closest detection as switch ratio description
        return detections[0]['$index'], True

    return iou_detections[0]['$index'], False


def main():
    pass


if __name__ == '__main__':
    main()
