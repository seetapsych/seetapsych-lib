# -*- coding: utf-8 -*-

import json
import re
import os
from typing import Callable

from fabopsy_lib import api
from fabopsy_lib import schema
from fabopsy_lib.runtime.actions import call_entry
from fabopsy_lib.utils.dirs import appdirs
from fabopsy_lib.utils.download_file import download_file, extract_file
from fabopsy_lib.utils.defer import defer

__all__ = [
    'build_model',
    'exists_model',
    'LocalModel',
    'register_cloud_downloader',
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


_CLOUD_DOWNLOADERS: dict[str, Callable[[schema.CloudModel, str], str]] = {}


def _normalize_host(host: str) -> str:
    return (host or '').strip().lower()


def register_cloud_downloader(hosts: list[str], downloader: Callable[[schema.CloudModel, str], str]):
    for h in hosts:
        _CLOUD_DOWNLOADERS[_normalize_host(h)] = downloader


def _get_cloud_downloader(host: str) -> Callable[[schema.CloudModel, str], str] | None:
    return _CLOUD_DOWNLOADERS.get(_normalize_host(host))


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

    def __marker_path(self) -> str:
        return os.path.join(self.__cache_dir, '.fabopsy_cloud.json')

    def __read_marker(self) -> dict | None:
        path = self.__marker_path()
        try:
            with open(path, 'r', encoding='utf-8') as f:
                marker = json.load(f)
            if not isinstance(marker, dict):
                return None
            return marker
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def __marker_matches(self, marker: dict) -> bool:
        if marker.get('host') != self.__cfg.host:
            return False
        if marker.get('model_id') != self.__cfg.model_id:
            return False
        if marker.get('revision', '') != (self.__cfg.revision or ''):
            return False
        if marker.get('repo_type', '') != (self.__cfg.repo_type or ''):
            return False
        return True

    def __downloaded_dir_from_marker(self, marker: dict) -> str | None:
        path = marker.get('path')
        if not isinstance(path, str) or path == '':
            return None
        if os.path.isabs(path):
            model_dir = os.path.abspath(path)
        else:
            model_dir = os.path.abspath(os.path.join(self.__cache_dir, path))
        if not os.path.exists(model_dir):
            return None
        if self.__cfg.index:
            if not os.path.exists(os.path.join(model_dir, self.__cfg.index)):
                return None
        return model_dir

    def exists(self) -> bool:
        if not self.__cache_dir:
            return False
        marker = self.__read_marker()
        if not marker or not self.__marker_matches(marker):
            return False
        return self.__downloaded_dir_from_marker(marker) is not None

    def cache(self) -> str:
        if not self.__cache_dir:
            raise RuntimeError('cache_dir must be provided for cloud models')

        marker = self.__read_marker()
        if marker and self.__marker_matches(marker):
            model_dir = self.__downloaded_dir_from_marker(marker)
            if model_dir:
                return model_dir

        os.makedirs(self.__cache_dir, exist_ok=True)

        downloader = _get_cloud_downloader(self.__cfg.host)
        if downloader is None:
            raise RuntimeError(f'Unsupported cloud host: {self.__cfg.host}')
        model_dir = os.path.abspath(downloader(self.__cfg, self.__cache_dir))

        cache_dir_abs = os.path.abspath(self.__cache_dir)
        if os.path.commonpath([cache_dir_abs, model_dir]) != cache_dir_abs:
            raise RuntimeError(f'Cloud model downloaded outside cache_dir: {model_dir}')

        if self.__cfg.index and not os.path.exists(os.path.join(model_dir, self.__cfg.index)):
            raise RuntimeError(f'Index was not found in cloud model directory: {self.__cfg.index}')

        rel_path = os.path.relpath(model_dir, self.__cache_dir)
        marker = {
            'host': self.__cfg.host,
            'model_id': self.__cfg.model_id,
            'revision': self.__cfg.revision or '',
            'repo_type': self.__cfg.repo_type or '',
            'path': rel_path,
        }
        with open(self.__marker_path(), 'w', encoding='utf-8') as f:
            json.dump(marker, f, ensure_ascii=False, indent=2)

        return model_dir


def _download_huggingface(cfg: schema.CloudModel, cache_dir: str) -> str:
    try:
        from huggingface_hub import snapshot_download
    except ImportError as e:
        raise RuntimeError('huggingface_hub is required for CloudModel host=huggingface') from e
    revision = (cfg.revision or '').strip() or None
    repo_type = (cfg.repo_type or '').strip() or None
    kwargs = {
        'repo_id': cfg.model_id,
        'local_dir': cache_dir,
        'revision': revision,
        'local_dir_use_symlinks': False,
    }
    if repo_type:
        kwargs['repo_type'] = repo_type
    if cfg.allow_patterns is not None:
        kwargs['allow_patterns'] = cfg.allow_patterns
    if cfg.ignore_patterns is not None:
        kwargs['ignore_patterns'] = cfg.ignore_patterns
    path = snapshot_download(**kwargs)
    return str(path)


def _download_modelscope(cfg: schema.CloudModel, cache_dir: str) -> str:
    snapshot_download = None
    try:
        from modelscope.hub.snapshot_download import snapshot_download as _snapshot_download
        snapshot_download = _snapshot_download
    except ImportError:
        try:
            from modelscope.hub.api import snapshot_download as _snapshot_download
            snapshot_download = _snapshot_download
        except ImportError as e:
            raise RuntimeError('modelscope is required for CloudModel host=modelscope') from e
    revision = (cfg.revision or '').strip() or None
    path = snapshot_download(cfg.model_id, cache_dir=cache_dir, revision=revision)
    return str(path)


register_cloud_downloader(['huggingface', 'hf'], _download_huggingface)
register_cloud_downloader(['modelscope', 'ms'], _download_modelscope)


class DownloadModel(api.UsageModel):
    def __init__(self, cfg: schema.DownloadModel, *, usage: str = '', cache_dir: str = None):
        self.__cfg = cfg
        self.__usage = usage
        self.__cache_dir = cache_dir

    @property
    def usage(self) -> str:
        return self.__usage

    def exists(self) -> bool:
        cache_index = os.path.join(self.__cache_dir, self.__cfg.index)
        return os.path.exists(cache_index)

    def cache(self) -> str:
        cache_index = os.path.join(self.__cache_dir, self.__cfg.index)
        if os.path.exists(cache_index):
            return cache_index

        os.makedirs(self.__cache_dir, exist_ok=True)
        if self.__cfg.unpack:
            # download compressed file and upack it
            compressed_file = download_file(self.__cfg.url, self.__cache_dir, md5=self.__cfg.md5)
            with defer(lambda: os.remove(compressed_file)):
                extract_file(compressed_file, self.__cache_dir)
        else:
            # download to index file
            download_file(self.__cfg.url, cache_index, md5=self.__cfg.md5)

        assert os.path.exists(cache_index), (
            RuntimeError(f'Index was not found in download directory: {self.__cfg.index}'))

        return cache_index


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
    cache_dir = '.cache'

    download_model = DownloadModel(schema.DownloadModel(
        index='LICENSE',
        url='https://raw.githubusercontent.com/python/cpython/3.11/LICENSE',
        md5='fcf6b249c2641540219a727f35d8d2c2',
        **{}),
        cache_dir=cache_dir
    )

    print(download_model.exists(), download_model.cache())

    download_model = DownloadModel(schema.DownloadModel(
        index='font-consolas-ttf-1.2/fonts/Consolas.ttf',
        url='https://codeload.github.com/misuchiru03/font-consolas-ttf/zip/refs/tags/1.2',
        md5='999642B83F40AFE277C40EF8A4CB653E',
        unpack=True),
        cache_dir=cache_dir
    )

    print(download_model.exists(), download_model.cache())


if __name__ == '__main__':
    test()
