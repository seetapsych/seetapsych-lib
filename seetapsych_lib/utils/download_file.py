# -*- coding: utf-8 -*-


import os
import shutil
import time
import hashlib
import zipfile
import tarfile
from http.client import HTTPResponse
from urllib.error import URLError, HTTPError
from urllib.parse import urlparse, parse_qs, unquote
from urllib.request import urlopen
from ftplib import FTP, error_perm
from typing import Literal

from tqdm import tqdm

from seetapsych_lib.utils.logger import logger


__all__ = [
    'download_file',
    'extract_file',
]


def filename_of_url(url: str, response: HTTPResponse | None) -> str | None:
    # find parameter in header
    filename: str | tuple | None = (
        None
        if response is None else
        response.headers.get_param('filename', header='Content-Disposition')
    )
    if filename is not None:
        if isinstance(filename, tuple):
            filename = filename[-1]
        return filename

    # no filename found in headers, extract from url
    parsed_url = urlparse(url)
    filename: str | None = os.path.basename(unquote(parsed_url.path))
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


def extract_output_path(url: str, output_path: str | None, response: HTTPResponse | None) -> str:
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
    Notice: Only support FTP and HTTP/S link for now.
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
    scheme = parsed_url.scheme.lower()

    kwargs = dict(
        url=url,
        output=output,
        md5=md5,
        sha256=sha256,
        buffer_size_bytes=buffer_size_bytes,
        max_retries=max_retries,
        retry_wait_seconds=retry_wait_seconds,
        timeout_seconds=timeout_seconds,
        overwrite=overwrite,
        quiet=quiet,
    )

    if scheme in {'http', 'https'}:
        return download_http_file(**kwargs)
    elif scheme in {'ftp'}:
        return download_ftp_file(**kwargs)
    else:
        raise ValueError(f'Invalid URL Scheme {parsed_url.scheme}')

def download_http_file(
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
        **kwargs,
) -> str:
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


def download_ftp_endpoint(
        ftp: FTP,
        remote_path: str,
        output_path: str,
        buffer_size_bytes: int = 8192,
        *,
        basename: str | None = None,
        quiet: bool = False
):
    """
    Download file from FTP endpoint to local path.

    Features:
    - Streaming download
    - Progress bar via tqdm
    - Automatic directory creation

    :param ftp: Connected FTP client
    :param remote_path: Full remote file path (absolute or relative)
    :param output_path: Local file path
    :param buffer_size_bytes: Block size
    :param basename: Name for progress bar display
    :param quiet: Disable progress bar
    """

    # Ensure local directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Resolve display name
    if not basename:
        basename = os.path.basename(output_path)

    # Try to get file size (may fail on some servers)
    total_size = 0
    try:
        total_size = ftp.size(remote_path) or 0
    except Exception:
        total_size = 0  # fallback if not supported

    with open(output_path, "wb") as f:
        with tqdm(
                total=total_size if total_size > 0 else None,
                desc=basename,
                unit='iB',
                unit_scale=True,
                disable=quiet
        ) as bar:
            def callback(data: bytes):
                f.write(data)
                bar.update(len(data))

            # Use full path directly (no need cwd)
            ftp.retrbinary(
                f'RETR {remote_path}',
                callback,
                blocksize=buffer_size_bytes
            )


def download_ftp_file(
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
        **kwargs,
) -> str:
    parsed_url = urlparse(url)
    if parsed_url.scheme.lower() != 'ftp':
        raise ValueError(f'Invalid URL Scheme {parsed_url.scheme}')

    if max_retries <= 0:
        max_retries = 1

    host = parsed_url.hostname
    port = parsed_url.port or 21
    username = parsed_url.username or 'anonymous'
    password = parsed_url.password or ''

    filepath = unquote(parsed_url.path)
    if not filepath:
        raise ValueError('FTP URL must include file path')

    filename = os.path.basename(filepath)

    current_output_path: str | None = None
    current_output_temp: str | None = None
    current_output_name: str | None = filename

    def validate_file(validate_path: str, raise_exception: bool = False) -> bool:
        if md5 and not checksum(validate_path, md5, algorithm='md5'):
            if raise_exception:
                raise RuntimeError(f'Failed to checksum of {validate_path} md5={md5}')
            return False

        if sha256 and not checksum(validate_path, sha256, algorithm='sha256'):
            if raise_exception:
                raise RuntimeError(f'Failed to checksum of {validate_path} sha256={sha256}')
            return False

        return True

    # Check existing output
    if output and os.path.isfile(output) and not overwrite:
        if validate_file(output, raise_exception=False):
            return output
        else:
            logger.warning(f'File {os.path.basename(output)} already exists, '
                           f'but checksum failed. Redownloading...')

    for attempt in range(max_retries):
        ftp = None
        try:
            ftp = FTP()
            ftp.connect(host, port, timeout=timeout_seconds)
            ftp.login(username, password)
            ftp.set_pasv(True)

            # Change working directory
            dirpath = os.path.dirname(filepath)
            if dirpath:
                ftp.cwd(dirpath)

            # Resolve output path
            current_output_path = extract_output_path(url, output, None)
            current_output_path = os.path.abspath(current_output_path)
            current_output_name = os.path.basename(current_output_path)

            if os.path.exists(current_output_path):
                if overwrite:
                    os.remove(current_output_path)
                elif validate_file(current_output_path, raise_exception=False):
                    return current_output_path
                else:
                    logger.warning(f'File {current_output_name} already exists, '
                                   f'but checksum failed. Redownloading...')

            current_output_temp = current_output_path + '.temp'
            download_ftp_endpoint(
                ftp,
                filepath,
                current_output_temp,
                buffer_size_bytes,
                basename=current_output_name,
                quiet=quiet
            )
            break

        except (OSError, error_perm) as e:
            if current_output_temp and os.path.exists(current_output_temp):
                os.remove(current_output_temp)

            logger.error(e)

            if attempt + 1 < max_retries:
                logger.error(f'Tried [{attempt + 1}/{max_retries}] download {url} failed.'
                             f' Retry after {retry_wait_seconds} seconds.')
                time.sleep(retry_wait_seconds)
            else:
                logger.error(f'Tried [{attempt + 1}/{max_retries}] download {url} failed finally.')
                raise RuntimeError(
                    f'Failed to download {current_output_name} '
                    f'from {url} after {max_retries} retries'
                ) from e
        finally:
            if ftp:
                try:
                    ftp.quit()
                except Exception:
                    pass

    # Validate checksum
    try:
        validate_file(current_output_temp, raise_exception=True)
    except RuntimeError:
        if current_output_temp and os.path.exists(current_output_temp):
            os.remove(current_output_temp)
        raise

    # Move to final path
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
        md5='fcf6b249c2641540219a727f35d8d2c2',
        overwrite=True,
    )
    download_file(
        'ftp://test.rebex.net/readme.txt',
        md5='DA4BA9D17A7F9EBB90CF5F2F7F4BD81E',
        overwrite=True,
    )


if __name__ == '__main__':
    test()
