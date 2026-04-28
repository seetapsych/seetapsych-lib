# -*- coding: utf-8 -*-

import re
import json
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic.fields import FieldInfo
from pydantic import BaseModel, Field, model_validator

__all__ = [
    'Uid',
    'Entry',
    'Model',
    'Module',
    'Entity',
    'Package',
    'ParameterType',
    'Parameter',
    'ModuleSpec',
    'CloudModel',
    'DownloadModel',
]


Uid = str


class CustomBaseModel(BaseModel):
    pass


class Entity(CustomBaseModel):
    uid: Uid = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description='Unique identifier. Provide a unique string, or a UUID will be generated.'
    )
    name: str = Field('', description='')
    version: str = Field(
        '0.0.0',
        repr=True,
        pattern=r'^(\d+)(?:\.(\d+)(?:\.(\d+))?)?(-(?:[a-zA-Z0-9_.-]+))?(\+(?:[a-zA-Z0-9_.-]+))?$',
        examples=['1.2', '0.1.2', '1.23.3-alpha01', '2.0.1+20260101'],
        description='Version format: MAJOR[.MINOR[.PATCH]][-PRERELEASE][+BUILD]')
    description: str = Field('', description='')
    keywords: list[str] = Field([], description='')

    @property
    def format_version(self) -> tuple[int, int, int, str, str]:
        field: FieldInfo = self.__class__.__pydantic_fields__['version']
        pattern = field.metadata[0].pattern
        match = re.match(pattern, self.version)
        if not match:
            return 0, 0, 0, '', ''
        return int(match[1] or 0), int(match[2] or 0), int(match[3] or 0), match[4] or '', match[5] or ''


class Entry(CustomBaseModel):
    package: str | None = Field(
        None,
        examples=['x.y.z'],
        description='Package from which the method is called')
    method: str = Field(
        examples=['a.b.c.func'],
        description='Python method for this entry. '
                    'If a package is provided, '
                    'the package name is prepended as the method prefix')
    args: list[Any] = Field([])
    kwargs: dict[str, Any] = Field({})


class CloudModel(CustomBaseModel):
    host: str = Field(
        examples=['modelscope', 'huggingface', 'aistudio'],
        description='Cloud host for downloading the model')
    model_id: str = Field(
        description='Model ID in the hosting repository')
    revision: str = Field(
        '',
        description='Optional revision/tag/commit to download')
    repo_type: str = Field(
        '',
        description='Repository type for the cloud host (e.g., Hugging Face: model/dataset/space)')
    allow_patterns: list[str] | None = Field(
        None,
        description='Optional allow patterns for file filtering (Hugging Face only)')
    ignore_patterns: list[str] | None = Field(
        None,
        description='Optional ignore patterns for file filtering (Hugging Face only)')
    index: str = Field(
        '',
        description='Optional index file/dir path for existence check, relative to the downloaded directory')
    contains: list[str] = Field(
        [],
        description='Extra file/dir path for existence check, relative to the downloaded directory')


class DownloadModel(CustomBaseModel):
    index: str = Field(
        description='Output filename used as the model cache index, for existence checks.')
    url: str = Field(
        description='Model download FTP or HTTP/S URL. HTTP/S is recommended')
    md5: str = Field(
        '',
        description='MD5 checksum of the downloaded model file')
    sha256: str = Field(
        '',
        description='SHA256 checksum of the downloaded model file')
    unpack: bool = Field(
        False,
        description='Whether the downloaded file is compressed. If true, it will be decompressed automatically.')
    contains: list[str] = Field(
        [],
        description='Extra file/dir path for existence check. Only work with upack = True')


class Model(Entity):
    """
    Model acquisition configuration.
    The model can be obtained using the `entry` code.
    Alternatively, it can be retrieved from the `host` via the `model_id` in `cloud`.
    Or, you can directly download it using the `download_url` and verify it using the `download_md5` in `download`.
    """

    usage: str = Field(
        '',
        description='Specifies the model to use within a multi-model algorithm package')

    recommended: bool = Field(False, description='If true, this model is used by default')

    cloud: CloudModel | None = Field(
        None,
        description='')

    download: DownloadModel | None = Field(
        None,
        description='')

    entry: Entry | None = Field(
        None,
        description='Python entry for loading this model. The entry should return @ref fabopsy_lib.api.Model')

    metadata: dict[str, Any] = Field(
        {},
        description='Metadata is used to describe a model, '
                    'typically indicating the necessary backbone network, '
                    'pre-processing, and other parameters of the model.')

    @model_validator(mode='after')
    def check_not_all_none(self):
        if all(x is None for x in [self.cloud, self.download, self.entry]):
            raise ValueError("cloud, download and entry can not all be None")
        return self


class ParameterType(str, Enum):
    Integer = 'integer'
    Number = 'number'
    String = 'string'
    Selection = 'selection'
    Boolean = 'boolean'
    IntegerArray = 'integer[]'
    NumberArray = 'number[]'
    StringArray = 'string[]'
    SelectionArray = 'selection[]'
    Object = 'object'


class Parameter(CustomBaseModel):
    name: str
    type: ParameterType

    text: str = Field('')
    description: str = Field('')

    value: None | int | float | str | bool | list[int] | list[float] | list[str] | dict[str, Any] = Field(None)
    selection: list[str] = Field(None)


class Package(Entity):
    usage_models: list[str] = Field(
        [],
        description='If more than one usage model is available, a specific one must be selected for initialization')
    inputs: list[str] = Field([], description='Lists input modalities if this package is multimodal')
    requires: list[str] = Field([], description='Attributes required to run this package')
    provides: list[str] = Field([], description='Attributes provided by this package')
    entry: Entry = Field(
        description='Python entry for loading this package. The entry should return @ref fabopsy_lib.api.Package')
    parameters: list[Parameter] = Field([], description='Parameters for controlling the package')
    models: list[Model] = Field(
        description='Available models that can be switched as needed')


class GitRef(CustomBaseModel):
    name: str = Field(description='Package name to check if this package has been installed')
    repo: str = Field(description='Git repo address to download package')
    require: str | None = Field(None, description='Version to check package like: >=1.3,<3')
    revision: str | None = Field(None, description='Change the revision, branch or commit to setup')
    subdir: str | None = Field(None, description='Subdir in git source to setup')


class ModuleSpec(Entity):
    requirements: list[str] = Field(
        [],
        description='Python package requirements')

    refs: list[GitRef] = Field(
        [],
        description='Python package to install from git')


class Module(CustomBaseModel):
    version: Literal['1.0'] = Field(
        '1.0',
        examples=['1.0'],
        description="Module configuration protocol version, distinct from the module's own version")

    module: ModuleSpec = Field(description="Module specification")

    packages: list[Package] = Field(
        [],
        description='Packages that can be loaded')


def schema():
    return Module.model_json_schema()


def example() -> str:
    return Module.model_construct().model_dump_json(ensure_ascii=False, indent=2)


def parse(obj: dict[str, Any]) -> Module:
    Module.model_validate(obj)
    return Module(**obj)


def test():
    print(json.dumps(schema(), ensure_ascii=False, indent=2))
    print(example())
    t = parse({'version': '1.0', 'module': {'name': 'Name', 'version': '1.0.0', 'description': 'No description'}, 'packages': []})
    print(t.module.format_version)

    from fabopsy_lib.utils.markdown import schema2markdown
    md = schema2markdown(Module.model_json_schema())
    print(md)


if __name__ == '__main__':
    test()
