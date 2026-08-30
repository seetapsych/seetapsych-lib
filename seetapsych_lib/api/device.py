# -*- coding: utf-8 -*-

device_map = {
    "gpu": "cuda",
}

single_devices = {"cpu"}


class Device(object):
    def __init__(self, device_type: str = "cpu", device_index: int | None = None):
        device_type = device_type.strip().lower()

        colon_index = device_type.find(":")
        if colon_index >= 0:
            first, second = device_type[:colon_index], device_type[colon_index + 1 :]
            device_type = first
            if device_index is None:
                device_index = int(second)

        if not device_type:
            device_type = "cpu"
        if device_type in device_map:
            device_type = device_map[device_type]

        self.type = device_type
        self.index = device_index

    def __str__(self) -> str:
        if self.index is None or self.type in single_devices:
            return self.type
        else:
            return f"{self.type}:{self.index}"

    def __repr__(self) -> str:
        dumps = {
            "type": self.type,
            "index": self.index,
        }
        fields = ", ".join([f"{k}={repr(v)}" for k, v in dumps.items() if v is not None])
        return f"Device({fields})"
