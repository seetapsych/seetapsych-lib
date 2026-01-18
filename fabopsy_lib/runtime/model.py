# -*- coding: utf-8 -*-


from fabopsy_lib import api
from fabopsy_lib import schema
from fabopsy_lib.runtime.actions import call_entry

__all__ = [
    'build_model',
    'LocalModel',
]


class WrapperModel(api.UsageModel):
    def __init__(self, model: api.Model, *, usage: str = ''):
        self.__usage = usage
        self.__model = model

    @property
    def usage(self) -> str:
        return self.__usage

    def cache(self, cache_dir: str = None) -> str:
        return self.__model.cache(cache_dir=cache_dir)



class LocalModel(api.UsageModel):
    def __init__(self, path: str, *, usage: str = ''):
        self.__usage = usage
        self.__path = path

    @property
    def usage(self) -> str:
        return self.__usage

    def cache(self, cache_dir: str = None) -> str:
        return self.__path


class CloudModel(api.UsageModel):
    def __init__(self, cfg: schema.CloudModel, *, usage: str = ''):
        self.__cfg = cfg
        self.__usage = usage

    @property
    def usage(self) -> str:
        return self.__usage

    def cache(self, cache_dir: str = None) -> str:
        raise NotImplementedError


class DownloadModel(api.UsageModel):
    def __init__(self, cfg: schema.DownloadModel, *, usage: str = ''):
        self.__cfg = cfg
        self.__usage = usage

    @property
    def usage(self) -> str:
        return self.__usage

    def cache(self, cache_dir: str = None) -> str:
        raise NotImplementedError


def build_model_with_cloud(cloud: schema.CloudModel, *, usage: str = '') -> api.UsageModel:
    return CloudModel(cloud, usage=usage)


def build_model_with_download(download: schema.DownloadModel, *, usage: str = '') -> api.UsageModel:
    return DownloadModel(download, usage=usage)


def build_model_with_entry(entry: schema.Entry, *, usage: str = '') -> api.UsageModel:
    return WrapperModel(call_entry(entry), usage=usage)


def build_model(model: schema.Model) -> api.UsageModel:
    if model.entry is not None:
        return build_model_with_entry(model.entry)

    if model.download is not None:
        return build_model_with_download(model.download)

    if model.cloud is not None:
        return build_model_with_cloud(model.cloud)

    raise RuntimeError('The model configuration must at least provide cloud, download, or entry.')


def test():
    pass


if __name__ == '__main__':
    test()
