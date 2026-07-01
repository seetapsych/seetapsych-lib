# -*- coding: utf-8 -*-

from typing import Any, Literal

from fabopsy_lib import api
from fabopsy_lib.utils.logger import logger
from fabopsy_lib.toolkit.face_selection import max_tracking, max_select, Detection

class Instance(api.Instance):
    def __init__(self, selection_mode: Literal['MAX_TRACKING', 'MAX'] = 'MAX_TRACKING'):
        self.__pid = 0
        self.__selection_mode = selection_mode
        self.__pre_selection: Detection | None = None

    def reset(self):
        self.__pid = 0
        self.__pre_selection = None

    def inference(self, *,
                  data: dict[str, Any],
                  report: dict[str, Any],
                  **kwargs) -> dict[str, Any]:
        face_detection = report.get('face_detection', [])
        face_landmarks = report.get('face_landmarks', [])

        if self.__selection_mode == 'MAX_TRACKING':
            selected_index, target_updated = max_tracking(face_detection, self.__pre_selection)
            if selected_index < 0:
                self.__pre_selection = None
                return report
            if target_updated:
                self.__pid += 1
        elif self.__selection_mode == 'MAX':
            selected_index = max_select(face_detection)
            if selected_index < 0:
                self.__pre_selection = None
                return report
        else:
            logger.warning('Unknown selection mode: %s', self.__selection_mode)
            return report

        self.__pre_selection = face_detection[selected_index]

        report['face_selection'] = {
            'pid': self.__pid,
        }

        report['face_detection'] = [face_detection[selected_index]]
        if len(face_landmarks) > selected_index:
            report['face_landmarks'] = [face_landmarks[selected_index]]

        return report


class Package(api.Package):
    def create(self, *,
               models: list[api.UsageModel],
               parameters: dict[str, Any],
               device: api.Device | None,
               **kwargs) -> Instance:
        selection_mode = parameters.get('selection_mode', 'MAX_TRACKING')

        return Instance(selection_mode)


def load() -> api.Package:
    return Package()


def main():
    pass


if __name__ == '__main__':
    main()

