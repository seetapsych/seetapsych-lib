# -*- coding: utf-8 -*-

import re
import os.path

from fabopsy_lib import api
from fabopsy_lib import schema
from fabopsy_lib.runtime.actions import call_entry
from fabopsy_lib.utils.dirs import appdirs

__all__ = [
    'build_model',
    'exists_model',
    'LocalModel',
]


def default_cache_dir() -> str:
    cache_dir = os.environ.get('FABOPSY_CACHE_DIR', '') or appdirs.user_cache_dir
    return os.path.join(cache_dir, 'models')


def sanitize_folder(name: str):
    # exclude control characters (0-31)
    forbidden = r'\/:*?"<>|' + ''.join(chr(i) for i in range(32))

    result = re.sub(f'[{re.escape(forbidden)}]', '__', name)
    result = re.sub(r'_+', '__', result)

    return result


def entity_cache_dir(entity: schema.Entity, cache_dir: str = None) -> str:
    return os.path.join(cache_dir or default_cache_dir(), sanitize_folder(entity.uid) or '__anonymous__')


class WrapperModel(api.UsageModel):
    def __init__(self, model: api.Model, *, usage: str = ''):
        self.__usage = usage
        self.__model = model

    @property
    def usage(self) -> str:
        return self.__usage

    def exists(self) -> bool:
        return self.__model.exists()

    def cache(self) -> str:
        return self.__model.cache()


class LocalModel(api.UsageModel):
    def __init__(self, path: str, *, usage: str = ''):
        self.__usage = usage
        self.__path = path

    @property
    def usage(self) -> str:
        return self.__usage

    def exists(self) -> bool:
        return os.path.exists(self.__path)

    def cache(self) -> str:
        return self.__path


class CloudModel(api.UsageModel):
    def __init__(self, cfg: schema.CloudModel, *, usage: str = '', cache_dir: str = None):
        self.__cfg = cfg
        self.__usage = usage
        self.__cache_dir = cache_dir

    @property
    def usage(self) -> str:
        return self.__usage

    def exists(self) -> bool:
        return False

    def cache(self) -> str:
        raise NotImplementedError


class DownloadModel(api.UsageModel):
    def __init__(self, cfg: schema.DownloadModel, *, usage: str = '', cache_dir: str = None):
        self.__cfg = cfg
        self.__usage = usage
        self.__cache_dir = cache_dir

    @property
    def usage(self) -> str:
        return self.__usage

    def exists(self) -> bool:
        return False

    def cache(self) -> str:
        raise NotImplementedError


def build_model_with_cloud(
        cloud: schema.CloudModel, *,
        usage: str = '', cache_dir: str = None) -> api.UsageModel:
    return CloudModel(cloud, usage=usage, cache_dir=cache_dir)


def build_model_with_download(
        download: schema.DownloadModel, *,
        usage: str = '', cache_dir: str = None) -> api.UsageModel:
    return DownloadModel(download, usage=usage, cache_dir=cache_dir)


def build_model_with_entry(
        entry: schema.Entry, *,
        usage: str = '', cache_dir: str = None) -> api.UsageModel:
    return WrapperModel(call_entry(entry, {'cache_dir': cache_dir}), usage=usage)


def build_model(model: schema.Model, *, cache_dir: str = None) -> api.UsageModel:
    model_dir = entity_cache_dir(model, cache_dir=cache_dir)

    if model.entry is not None:
        return build_model_with_entry(model.entry, usage=model.usage, cache_dir=model_dir)

    if model.download is not None:
        return build_model_with_download(model.download, usage=model.usage, cache_dir=model_dir)

    if model.cloud is not None:
        return build_model_with_cloud(model.cloud, usage=model.usage, cache_dir=model_dir)

    raise RuntimeError('The model configuration must at least provide cloud, download, or entry.')


def exists_model(model: schema.Model, *, cache_dir: str = None) -> bool:
    try:
        return build_model(model, cache_dir=cache_dir).exists()
    except:
        return False


def test():
    pass


if __name__ == '__main__':
    test()
