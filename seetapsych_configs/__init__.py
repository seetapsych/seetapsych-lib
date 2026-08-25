# -*- coding: utf-8 -*-

import os
from typing import TypedDict

import yaml


__all__ = [
    'ConfigInfo',
    'configs',
]


class ConfigInfo(TypedDict):
    name: str
    version: str
    description: str
    download_url: str
    homepage: str


def _load_configs() -> list[ConfigInfo]:
    yml_path = os.path.join(os.path.dirname(__file__), 'configs.yml')
    with open(yml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    raw_list = data.get('configs', []) if isinstance(data, dict) else []
    result: list[ConfigInfo] = []
    for item in raw_list:
        result.append(ConfigInfo(
            name=item['name'],
            version=item['version'],
            description=item['description'],
            download_url=item['download_url'],
            homepage=item.get('homepage', ''),
        ))
    return result


configs: list[ConfigInfo] = _load_configs()
