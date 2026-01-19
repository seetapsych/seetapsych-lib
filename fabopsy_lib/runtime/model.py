# -*- coding: utf-8 -*-


import os.path

from fabopsy_lib import api
from fabopsy_lib import schema
from fabopsy_lib.runtime.actions import call_entry


__all__ = [
    'default_cache_dir',
    'build_model',
    'exists_model',
    'LocalModel',
]


def default_cache_dir() -> str:
    # TODO: using default cache_dir if it's not provided
    return ''


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
    if not cache_dir:
        cache_dir = default_cache_dir()

    if model.entry is not None:
        return build_model_with_entry(model.entry, usage=model.usage, cache_dir=cache_dir)

    if model.download is not None:
        return build_model_with_download(model.download, usage=model.usage, cache_dir=cache_dir)

    if model.cloud is not None:
        return build_model_with_cloud(model.cloud, usage=model.usage, cache_dir=cache_dir)

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
