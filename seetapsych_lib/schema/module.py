# -*- coding: utf-8 -*-

import json
import re
import uuid
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic.fields import FieldInfo

__all__ = [
    "Uid",
    "Entry",
    "Model",
    "Module",
    "Entity",
    "Package",
    "ParameterType",
    "Parameter",
    "ModuleSpec",
    "CloudModel",
    "DownloadModel",
]


Uid = str


class CustomBaseModel(BaseModel):
    """Shared configuration base applying to every module schema model."""


class Entity(CustomBaseModel):
    """Base fields shared by modules, packages and models.

    Every identifiable configuration object carries a UID, a semantic
    version, a human-readable label, and a free-form keyword list for
    catalogue / search purposes.
    """

    uid: Uid = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Stable unique identifier. If omitted a UUID4 is generated.",
    )
    name: str = Field("", description="Human-readable display label.")
    version: str = Field(
        "0.0.0",
        repr=True,
        pattern=r"^(\d+)(?:\.(\d+)(?:\.(\d+))?)?(-(?:[a-zA-Z0-9_.-]+))?(\+(?:[a-zA-Z0-9_.-]+))?$",
        examples=["1.2", "0.1.2", "1.23.3-alpha01", "2.0.1+20260101"],
        description="Semantic version: MAJOR[.MINOR[.PATCH]][-PRERELEASE][+BUILD].",
    )
    description: str = Field("", description="Long-form description of the entity.")
    keywords: list[str] = Field([], description="Tags for discovery / filtering.")

    @property
    def format_version(self) -> tuple[int, int, int, str, str]:
        field: FieldInfo = self.__class__.__pydantic_fields__["version"]
        pattern = field.metadata[0].pattern
        match = re.match(pattern, self.version)
        if not match:
            return 0, 0, 0, "", ""
        return (
            int(match[1] or 0),
            int(match[2] or 0),
            int(match[3] or 0),
            match[4] or "",
            match[5] or "",
        )


class Entry(CustomBaseModel):
    """Resolvable Python callable reference.

    Either ``package`` + ``method`` or a fully-qualified ``method`` alone is
    accepted. ``args`` and ``kwargs`` are forwarded verbatim to the resolved
    callable when the runner instantiates a package or model loader.
    """

    package: str | None = Field(
        None,
        examples=["x.y.z"],
        description="Importable module prefix prepended to ``method``.",
    )
    method: str = Field(
        examples=["a.b.c.func"],
        description="Callable attribute path. If ``package`` is set, it is prepended to form the full import path.",
    )
    args: list[Any] = Field([], description="Positional arguments passed to the callable.")
    kwargs: dict[str, Any] = Field({}, description="Keyword arguments passed to the callable.")


class CloudModel(CustomBaseModel):
    """Model fetch descriptor for a cloud model hub (ModelScope / Hugging Face / AI Studio)."""

    host: str = Field(
        examples=["modelscope", "huggingface", "aistudio"],
        description="Cloud hub identifier that owns ``model_id``.",
    )
    model_id: str = Field(description="Repository / model identifier on the target host.")
    revision: str = Field("", description="Optional revision, branch, tag or commit to pin.")
    repo_type: str = Field(
        "",
        description="Repository category on the cloud host (e.g. Hugging Face ``model`` / ``dataset`` / ``space``).",
    )
    allow_patterns: list[str] | None = Field(
        None,
        description="Glob patterns of files to include during download (Hugging Face only).",
    )
    ignore_patterns: list[str] | None = Field(
        None,
        description="Glob patterns of files to exclude during download (Hugging Face only).",
    )
    index: str = Field(
        "",
        description="Relative path inside the cached directory used as a sentinel for the existence check.",
    )
    contains: list[str] = Field(
        [],
        description="Additional relative paths checked after download to confirm a complete cache.",
    )


class DownloadModel(CustomBaseModel):
    """Direct URL download descriptor (HTTP/S or FTP)."""

    index: str = Field(
        description="Relative output path inside the cache; used as the existence sentinel.",
    )
    url: str = Field(description="Direct FTP or HTTP/S download URL; HTTP/S is recommended.")
    md5: str = Field("", description="Expected MD5 hex digest; verified after download if non-empty.")
    sha256: str = Field("", description="Expected SHA-256 hex digest; verified after download if non-empty.")
    unpack: bool = Field(
        False,
        description="If True, treat the download as an archive and decompress it automatically.",
    )
    contains: list[str] = Field(
        [],
        description="Extra relative paths to verify after extraction; meaningful only when ``unpack`` is True.",
    )


class Model(Entity):
    """Acquisition / instantiation configuration for a single algorithm model.

    Exactly one of ``cloud``, ``download`` or ``entry`` must be set:

    * ``cloud`` — fetch from a supported model hub (ModelScope / HF / AI Studio).
    * ``download`` — fetch directly from an HTTP/S or FTP URL.
    * ``entry`` — resolve an in-process callable returning a
      :class:`seetapsych_lib.api.Model`.
    """

    usage: str = Field(
        "",
        description="Slot key that matches a package ``usage_models`` entry in multi-model packages.",
    )
    recommended: bool = Field(
        False,
        description="If True, the solver selects this model automatically when multiple options exist.",
    )
    cloud: CloudModel | None = Field(
        None,
        description="Cloud-hub download descriptor; set when the model lives on a model registry.",
    )
    download: DownloadModel | None = Field(
        None,
        description="Direct URL download descriptor; set when the model is fetched via HTTP/S or FTP.",
    )
    entry: Entry | None = Field(
        None,
        description="Python callable resolved to a :class:`seetapsych_lib.api.Model` (no remote fetch).",
    )
    metadata: dict[str, Any] = Field(
        {},
        description="Free-form hints for the package loader (backbone, preprocessing config, etc.).",
    )

    @model_validator(mode="after")
    def check_not_all_none(self) -> "Model":
        if all(x is None for x in [self.cloud, self.download, self.entry]):
            raise ValueError("cloud, download and entry can not all be None")
        return self


class ParameterType(str, Enum):
    """Value-type discriminator for :class:`Parameter` declarations."""

    Integer = "integer"
    Number = "number"
    String = "string"
    Selection = "selection"
    Boolean = "boolean"
    IntegerArray = "integer[]"
    NumberArray = "number[]"
    StringArray = "string[]"
    SelectionArray = "selection[]"
    Object = "object"


class Parameter(CustomBaseModel):
    """Tunable runtime parameter exposed by a :class:`Package`.

    The parameter UI label is carried by ``text``, while ``description`` provides the
    long-form help text. ``value`` holds the default/current value, and
    ``selection`` enumerates the allowed labels when ``type`` is a selection
    variant.
    """

    name: str = Field(description="Programmatic parameter key used when overriding via Pipeline set_parameters().")
    type: ParameterType = Field(description="Value type; constrains the acceptable ``value`` shape.")

    text: str = Field("", description="Short UI label (one line).")
    description: str = Field("", description="Extended help text shown in tooltips / generated docs.")

    value: None | int | float | str | bool | list[int] | list[float] | list[str] | dict[str, Any] = Field(
        None, description="Default or currently assigned value; shape must agree with ``type``."
    )
    selection: list[str] = Field(
        [], description="Allowed option labels. Used only by ``Selection`` / ``SelectionArray`` types."
    )


class Package(Entity):
    """Loadable algorithm unit: produces ``provides`` attributes from ``requires`` attributes.

    A package is the smallest unit of scheduling in a :class:`Pipeline`; it
    declares its data-flow edges via ``requires``/``provides`` and yields a Python
    :class:`Instance` when the runners instantiate it.
    """

    usage_models: list[str] = Field(
        [],
        description="Model-usage slot keys required at instantiation time; one :class:`Model` selections must match.",
    )
    inputs: list[str] = Field([], description='Input modal names required by this package (``"default"`` if omitted).')
    requires: list[str] = Field(
        [],
        description="Attribute keys produced by upstream packages that must be present in ``report`` before running.",
    )
    provides: list[str] = Field(
        [],
        description="Attribute keys appended to the pipeline ``report`` dict after inference.",
    )
    priority: int = Field(
        0,
        description=("Provider selection tie-breaker when multiple packages declare the same attribute; higher wins."),
    )
    entry: Entry = Field(description="Python callable resolved to a :class:`seetapsych_lib.api.Package` factory.")
    parameters: list[Parameter] = Field(
        [], description="Declared tunable parameters; defaults + runtime overrides live here."
    )
    models: list[Model] = Field(
        [],
        description=(
            "Selectable model configurations; the solver picks from this list "
            "through the Pipeline ``models`` overrides. Empty for model-less packages."
        ),
    )


class GitRef(CustomBaseModel):
    """Alternative Python-package install directive backed by a Git repository.

    Used when a dependency is not available on PyPI and must be pulled directly from
    source during module ``refs`` list on :class:`ModuleSpec`.
    """

    name: str = Field(description="Importable Python package name used for the installed-check lookup.")
    repo: str = Field(description="Git repository URL (any scheme accepted by ``pip install git+...``).")
    require: str | None = Field(
        None, description="Version specifier checked on the installed package (PEP 440), e.g. ``>=1.3,<3``."
    )
    revision: str | None = Field(
        None, description="Branch, tag or commit SHA to pin the checkout to, instead of the default branch."
    )
    subdir: str | None = Field(
        None, description="Sub-directory inside the repo that holds the installable Python package."
    )


class ModuleSpec(Entity):
    """Top-level metadata for a module:class:`Module` (its PyPI/Git dependencies plus metadata.)"""

    requirements: list[str] = Field(
        [], description="PyPI requirement strings (PEP 508 specifiers) installed before loading this module loads."
    )
    refs: list[GitRef] = Field(
        [], description="Additional Git-installed dependencies resolved alongside ``requirements``."
    )


class Module(CustomBaseModel):
    """Top-level module YAML document root.

    Every ``modules/*.yml`` file validates against this model, carrying a
    protocol ``version`` the module-level ``ModuleSpec`` plus its deployable
    :class:`Package` list.
    """

    version: Literal["1.0"] = Field(
        "1.0",
        examples=["1.0"],
        description="Module YAML protocol version (independent of the module's own semantic ``ModuleSpec.version``).",
    )
    module: ModuleSpec = Field(description="Module-level metadata: version, name, dependencies, refs.")
    packages: list[Package] = Field(
        [], description="Algorithm packages exposed by this module, available for Pipeline assembly."
    )


def schema() -> dict[str, Any]:
    return Module.model_json_schema()


def example() -> str:
    return Module.model_construct().model_dump_json(ensure_ascii=False, indent=2)


def parse(obj: dict[str, Any]) -> Module:
    return Module.model_validate(obj)


def test():
    print(json.dumps(schema(), ensure_ascii=False, indent=2))
    print(example())
    t = parse(
        {
            "version": "1.0",
            "module": {"name": "Name", "version": "1.0.0", "description": "No description"},
            "packages": [],
        }
    )
    print(t.module.format_version)

    from seetapsych_lib.utils.markdown import schema2markdown

    md = schema2markdown(Module.model_json_schema())
    print(md)


if __name__ == "__main__":
    test()
