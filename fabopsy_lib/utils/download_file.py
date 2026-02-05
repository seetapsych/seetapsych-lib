# -*- coding: utf-8 -*-


import os
import shutil
import time
import hashlib
import zipfile
import tarfile
from http.client import HTTPResponse
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse, parse_qs
from urllib.request import urlopen
from typing import Literal

from tqdm import tqdm

from fabopsy_lib.utils.logger import logger


__all__ = [
    'download_file',
    'extract_file',
]


def filename_of_url(url: str, response: HTTPResponse) -> str | None:
    # find parameter in header
    filename: str | tuple | None = response.headers.get_param('filename', header='Content-Disposition')
    if filename is not None:
        if isinstance(filename, tuple):
            filename = filename[-1]
        return filename

    # no filename found in headers, extract from url
    parsed_url = urlparse(url)
    filename: str | None = os.path.basename(parsed_url.path)
    if not filename or filename == '.' or filename == '..':
        # try extract file=xxx or filename=xxx in url query
        filename = None
        query = parse_qs(parsed_url.query)
        if query:
            for name in ['filename', 'file']:
                if name in query:
                    filename = query[name][0]
                    break
    return filename


def extract_output_path(url: str, output_path: str | None, response: HTTPResponse) -> str:
    if not output_path:
        return filename_of_url(url, response) or 'unknown'
    elif os.path.isdir(output_path) or output_path[-1] in {'/', '\\'}:
        return os.path.join(output_path, filename_of_url(url, response) or 'unknown')
    else:
        return output_path


def download_http_response(
        response: HTTPResponse, output_path: str,
        buffer_size_bytes: int = 8192, *, basename: str = None, quiet: bool = False
):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    total_size = int(response.headers.get("content-length", 0))
    if not basename:
        basename = os.path.basename(output_path)

    with open(output_path, "wb") as f:
        with tqdm(total=total_size, desc=basename, unit='iB', unit_scale=True, disable=quiet) as bar:
            while chunk := response.read(buffer_size_bytes):
                f.write(chunk)
                bar.update(len(chunk))


def checksum(file_path: str, expected_hash: str, algorithm: Literal['md5', 'sha256']) -> bool:
    chunk_size = 8192
    hasher = hashlib.new(algorithm)
    with open(file_path, 'rb') as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    actually_hash = hasher.hexdigest().lower()
    expected_hash = ''.join(expected_hash.split()).lower()
    return expected_hash == actually_hash


def download_file(
        url: str,
        output: str | None = None,
        md5: str | None = None,
        sha256: str | None = None,
        buffer_size_bytes: int = 8192,
        max_retries: int = 5,
        retry_wait_seconds: float = 1,
        timeout_seconds: float = 60,
        overwrite: bool = False,
        quiet: bool = False,
) -> str:
    """
    Download file from url to output path.
    Notice: Only support HTTP/S link for now.
    If download failed, exception will be raised.
    :param url: URL to download
    :param output: Path to download file or directory
    :param md5: MD5 checksum
    :param sha256: SHA256 checksum
    :param buffer_size_bytes: Block size in bytes
    :param max_retries: Maximum number of retries
    :param retry_wait_seconds: Retry seconds
    :param timeout_seconds: Timeout seconds
    :param overwrite: Overwrite existing file
    :param quiet: If true, suppress stdout and process bar
    :return: Download file path, return None if download failed
    """
    parsed_url = urlparse(url)
    if parsed_url.scheme.lower() not in {'http', 'https'}:
        raise ValueError(f'Invalid URL Scheme {parsed_url.scheme}')

    if max_retries <= 0:
        max_retries = 1

    current_output_path: str | None = None
    current_output_temp: str | None = None
    current_output_name: str | None = 'unknown'

    def validate_file(validate_path: str, raise_exception: bool = False) -> bool:
        if md5 and not checksum(validate_path, md5, algorithm='md5'):
            if raise_exception:
                raise RuntimeError(f'Failed to checksum of {validate_path} md5={md5}')
            else:
                return False

        if sha256 and not checksum(validate_path, sha256, algorithm='sha256'):
            if raise_exception:
                raise RuntimeError(f'Failed to checksum of {validate_path} sha256={sha256}')
            else:
                return False

        return True


    if output and os.path.isfile(output) and not overwrite:
        if validate_file(output, raise_exception=False):
            return output
        else:
            logger.warning(f'File {os.path.basename(output)} already exists,'
                           f' but checksum failed. Redownloading...')


    for attempt in range(max_retries):
        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                response: HTTPResponse
                current_output_path = extract_output_path(url, output, response)
                current_output_path = os.path.abspath(current_output_path)
                current_output_name = os.path.basename(current_output_path)

                if os.path.exists(current_output_path):
                    if overwrite:
                        os.remove(current_output_path)
                    elif validate_file(current_output_path, raise_exception=False):
                        return current_output_path
                    else:
                        logger.warning(f'File {os.path.basename(current_output_path)} already exists,'
                                       f' but checksum failed. Redownloading...')

                current_output_temp = current_output_path + '.temp'
                download_http_response(
                    response, current_output_temp, buffer_size_bytes,
                    basename=os.path.basename(current_output_path),
                    quiet=quiet)
                break
        except (URLError, HTTPError) as e:
            if current_output_temp and os.path.exists(current_output_temp):
                os.remove(current_output_temp)
            logger.error(e)
            if attempt + 1 < max_retries:
                # retry in next time
                logger.error(f'Tried [{attempt + 1}/{max_retries}] download {url} failed.'
                             f' Retry after {retry_wait_seconds} seconds.')
                time.sleep(retry_wait_seconds)
            else:
                # finally failed
                logger.error(f'Tried [{attempt + 1}/{max_retries}] download {url} failed finally.')
                raise RuntimeError(f'Failed to download {current_output_name}'
                                   f' from {url} after {max_retries} retries') from e

    # checksum
    try:
        validate_file(current_output_temp, raise_exception=True)
    except RuntimeError:
        if current_output_temp and os.path.exists(current_output_temp):
            os.remove(current_output_temp)
        raise

    # move temp to finally output file
    if current_output_path != current_output_temp:
        os.makedirs(os.path.dirname(current_output_path), exist_ok=True)
        shutil.move(current_output_temp, current_output_path)

    return current_output_path


def extract_file(file: str, output_dir: str = None):
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(file))

    basename = os.path.basename(file).lower()

    if basename.endswith('.zip'):
        with zipfile.ZipFile(file, 'r') as f:
            f.extractall(output_dir)
    elif basename.endswith('.tar'):
        with tarfile.open(file, 'r') as f:
            f.extractall(output_dir)
    elif basename.endswith('.tar.gz') or basename.endswith('.tgz'):
        with tarfile.open(file, 'r:gz') as f:
            f.extractall(output_dir)
    else:
        raise RuntimeError(f'Unsupported file type: {basename}.')


def test():
    download_file(
        'https://raw.githubusercontent.com/python/cpython/3.11/LICENSE',
        md5='fcf6b249c2641540219a727f35d8d2c2'
    )


if __name__ == '__main__':
    test()
