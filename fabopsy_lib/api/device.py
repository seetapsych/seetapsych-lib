# -*- coding: utf-8 -*-

device_map = {
    'gpu': 'cuda',
}

single_devices = {'cpu'}


class Device(object):
    def __init__(self, device_name: str = 'cpu', device_id: int = None):
        device_name = device_name.strip().lower()

        colon_index = device_name.find(':')
        if colon_index >= 0:
            first, second = device_name[:colon_index], device_name[colon_index + 1:]
            device_name = first
            if device_id is None:
                device_id = int(second)

        if not device_name:
            device_name = 'cpu'
        if device_name in device_map:
            device_name = device_map[device_name]

        self.name = device_name
        self.id = device_id

    def __str__(self):
        if self.id is None or self.name in single_devices:
            return self.name
        else:
            return f'{self.name}:{self.id}'

    def __repr__(self):
        return self.__str__()
