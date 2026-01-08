# -*- coding: utf-8 -*-

import re
import json
from enum import Enum
from typing import Any, Optional

from pydantic.fields import FieldInfo
from pydantic import BaseModel, Field

__all__ = [
    'SchemaEntry',
    'SchemaModel',
    'SchemaPackage',
    'SchemaModule',
    'schema',
    'parse',
]


class SchemaEntity(BaseModel):
    name: str = Field(..., description='')
    description: str = Field('', description='')
    keywords: list[str] = Field([], description='')
    version: str = Field(
        ...,
        repr=True,
        pattern=r'^(\d+)(?:\.(\d+)(?:\.(\d+))?)?(-(?:[a-zA-Z0-9_.-]+))?(\+(?:[a-zA-Z0-9_.-]+))?$',
        examples=['1.2', '0.1.2', '1.23.3-alpha01', '2.0.1+20260101'],
        description='version like MAJOR[.MINOR[.PATCH]][-PRERELEASE][+BUILD]')

    @property
    def format_version(self) -> tuple[int, int, int, str, str]:
        field: FieldInfo = self.__class__.__pydantic_fields__['version']
        pattern = field.metadata[0].pattern
        match = re.match(pattern, self.version)
        if not match:
            return 0, 0, 0, '', ''
        return int(match[1] or 0), int(match[2] or 0), int(match[3] or 0), match[4] or '', match[5] or ''


class SchemaEntry(BaseModel):
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


class SchemaModel(SchemaEntity):
    usage: str = Field(
        '',
        description='Used to specify the specific models within a multi-model algorithm package')

    entry: Optional[SchemaEntry] = Field(
        None,
        description='Python entry for loading this model. Entry should return @ref fabopsy_lib.api.Model')

    host: str = Field(
        ...,
        examples=['modelscope'],
        description='The cloud host to download model')
    model_id: str = Field(
        '',
        description='Model id for model hosting repo')


class AttributeType(str, Enum):
    Integer = 'integer'
    Number = 'number'
    String = 'string'
    Selection = 'selection'
    IntegerArray = 'integer[]'
    NumberArray = 'number[]'
    StringArray = 'string[]'
    SelectionArray = 'selection[]'


class SchemaAttribute(BaseModel):
    name: str
    type: AttributeType
    value: None|int|float|str|list[int]|list[float]|list[str] = Field(None)
    selection: list[str] = Field(None)


class SchemaPackage(BaseModel):
    entry: SchemaEntry = Field(
        ...,
        description='Python entry for loading this model. Entry should return @ref fabopsy_lib.api.Package')
    using_models: list[str] = Field(
        [],
        description='If it is greater than 1, the corresponding usage model needs to be used for initialization')
    models: list[SchemaModel] = Field(
        ...,
        description='The available models can be switched according to the situation')
    requires: list[str] = Field([], description='Required attributes to run this package')
    provides: list[str] = Field([], description='Provided attributes to run this package')
    attributes: list[SchemaAttribute] = Field([], description='Attributes for package controlling')
    inputs: list[str] = Field([], description='Describe modal if this package need multimodal')


class SchemaModule(SchemaEntity):
    requirements: list[str] = Field(
        [],
        description='Python requirements')
    packages: list[SchemaPackage] = Field(
        ...,
        description='Packages that can be loaded')


def schema():
    return SchemaModule.model_json_schema()


def example() -> str:
    return SchemaModule.model_construct().model_dump_json(ensure_ascii=False, indent=2)


def parse(obj: dict[str, Any]) -> SchemaModule:
    SchemaModule.model_validate(obj)
    return SchemaModule(**obj)


if __name__ == '__main__':
    print(json.dumps(schema(), ensure_ascii=False, indent=2))
    print(example())
    t = parse({'name': 'Name', 'version': '1.0.0', 'packages': [], 'description': 'No description'})
    print(t.format_version)
