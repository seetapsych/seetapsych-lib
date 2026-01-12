# -*- coding: utf-8 -*-

import re
import json
from enum import Enum
from typing import Any, Optional, Literal, Union

from pydantic.fields import FieldInfo
from pydantic import BaseModel, Field

__all__ = [
    'Entry',
    'Model',
    'Package',
    'Module',
]


class Entity(BaseModel):
    name: str = Field('', description='')
    version: str = Field(
        '0.0.0',
        repr=True,
        pattern=r'^(\d+)(?:\.(\d+)(?:\.(\d+))?)?(-(?:[a-zA-Z0-9_.-]+))?(\+(?:[a-zA-Z0-9_.-]+))?$',
        examples=['1.2', '0.1.2', '1.23.3-alpha01', '2.0.1+20260101'],
        description='version like MAJOR[.MINOR[.PATCH]][-PRERELEASE][+BUILD]')
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


class Entry(BaseModel):
    package: Optional[str] = Field(
        None,
        examples=['x.y.z'],
        description='The package where the method is called')
    method: str = Field(
        ...,
        examples=['a.b.c.func'],
        description='Python method for this entry. '
                    'If a package is provided, '
                    'the complete package name will be concatenated with the package name of the method prefix')
    args: list[Any] = Field([])
    kwargs: dict[str, Any] = Field({})


class CloudModel(BaseModel):
    host: str = Field(
        ...,
        examples=['modelscope'],
        description='The cloud host to download model')
    model_id: str = Field(
        ...,
        description='Model id for model hosting repo')


class DownloadModel(BaseModel):
    url: str = Field(
        ...,
        description='Download model link. HTTP recommended')
    md5: str = Field(
        '',
        description='Model file md5')
    compressed: bool = Field(
        False,
        description='Is the downloaded file a compressed file? If so, the file will be automatically decompressed.')


class Model(Entity):
    """
    Model acquisition configuration.
    The model can be obtained using the `entry` code.
    Alternatively, it can be retrieved from the `host` via the `model_id` in `cloud`.
    Or, you can directly download it using the `download_url` and verify it using the `download_md5` in `download`.
    """

    usage: str = Field(
        '',
        description='Used to specify the specific models within a multi-model algorithm package')

    recommended: bool = Field(False, description='The recommended model will be used by default')

    entry: Optional[Entry] = Field(
        None,
        description='Python entry for loading this model. Entry should return @ref fabopsy_lib.api.Model')

    cloud: Optional[CloudModel] = Field(
        None,
        description='')

    download: Optional[DownloadModel] = Field(
        None,
        description='')


class ParameterType(str, Enum):
    Integer = 'integer'
    Number = 'number'
    String = 'string'
    Selection = 'selection'
    IntegerArray = 'integer[]'
    NumberArray = 'number[]'
    StringArray = 'string[]'
    SelectionArray = 'selection[]'


class Parameter(BaseModel):
    name: str
    type: ParameterType
    value: Union[None, int, float, str, list[int], list[float], list[str]] = Field(None)
    selection: list[str] = Field(None)
    description: str = Field('')


class Package(Entity):
    using_models: list[str] = Field(
        [],
        description='If it is greater than 1, the corresponding usage model needs to be used for initialization')
    inputs: list[str] = Field([], description='Describe modal if this package need multimodal')
    requires: list[str] = Field([], description='Required attributes to run this package')
    provides: list[str] = Field([], description='Provided attributes to run this package')
    entry: Entry = Field(
        ...,
        description='Python entry for loading this model. Entry should return @ref fabopsy_lib.api.Package')
    parameters: list[Parameter] = Field([], description='Parameters for package controlling')
    models: list[Model] = Field(
        ...,
        description='The available models can be switched according to the situation')


class ModuleInfo(Entity):
    requirements: list[str] = Field(
        [],
        description='Python requirements')


class Module(BaseModel):
    version: Literal['1.0'] = Field(
        '1.0',
        examples=['1.0'],
        description='Module configuration protocol version, which is different from the current module version')

    module: ModuleInfo = Field(..., description="Module information")

    packages: list[Package] = Field(
        ...,
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


if __name__ == '__main__':
    test()
