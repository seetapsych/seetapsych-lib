# -*- coding: utf-8 -*-

from collections import defaultdict
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from seetapsych_lib import schema
from seetapsych_lib.runtime.actions import (
    import_entry,
    install_module_requirements,
    unsatisfied_requirements,
)
from seetapsych_lib.runtime.factory import Factory
from seetapsych_lib.runtime.model import build_model, exists_model
from seetapsych_lib.utils.logger import logger
from seetapsych_lib.utils.pencilbox import unique_list

__all__ = [
    "Pipeline",
    "PipelineConfig",
    "InvalidConfig",
    "ProblemConfig",
    "SolvedConfig",
    "UnsatisfactionConfig",
]


class PipelineConfig(BaseModel):
    """Mutable runtime snapshot of a :class:`Pipeline` ready for :class:`Runner`.

    Carries the ordered package graph, selected module metadata, explicit
    target attributes, and any per-package parameter/model overrides.
    Serialize this object to persist or share a pipeline definition.

    Attributes:
        name: Human-readable pipeline label, for display/logging only.
        description: Free-form textual notes about the pipeline purpose or setup.
        modules: Module metadata for every package currently bound; used to
            check requirements / ownership.
        packages: Topologically ordered packages to be executed by the runner.
        attributes: Target attribute keys requested by the user; a subset of
            the union of ``provides``.
        parameters: Runtime parameter overrides keyed by ``package.uid``.
        models: Selected model configurations keyed by ``package.uid``.
    """

    name: str = Field("", description="Human-readable pipeline label, for display/logging only.")
    description: str = Field("", description="Free-form textual notes about the pipeline purpose or setup.")

    modules: list[schema.ModuleSpec] = Field(
        [],
        description="Module metadata for every package currently bound; used to check requirements / ownership.",
    )
    packages: list[schema.Package] = Field(
        [], description="Topologically ordered packages to be executed by the runner."
    )
    attributes: list[str] = Field(
        [], description="Target attribute keys requested by the user; a subset of the union of ``provides``."
    )

    parameters: dict[schema.Uid, list[schema.Parameter]] = Field(
        {}, description="Runtime parameter overrides keyed by ``package.uid``."
    )
    models: dict[schema.Uid, list[schema.Model]] = Field(
        {}, description="Selected model configurations keyed by ``package.uid``."
    )


class InvalidConfig(BaseModel):
    """Items flagged by :meth:`Pipeline.validate` that could not be matched in the factory.

    Every listed item exists in the pipeline config but has no corresponding
    entry in the bound :class:`Factory`. When ``update`` is True these items
    are dropped/overwritten instead of reported.

    Attributes:
        modules: Module UIDs present in config but absent from the factory.
        packages: Package UIDs present in config but absent from the factory.
        models: Models with unknown UID or mismatched package, grouped by
            ``package.uid``.
        attributes: Requested attribute keys that are not declared by any
            factory-registered provider.
        parameters: Parameter overrides whose name is unknown to the owning
            package, grouped by ``package.uid``.
    """

    modules: list[schema.ModuleSpec] = Field(
        [], description="Module UIDs present in config but absent from the factory."
    )
    packages: list[schema.Package] = Field(
        [], description="Package UIDs present in config but absent from the factory."
    )
    models: dict[schema.Uid, list[schema.Model]] = Field(
        {}, description="Models with unknown UID or mismatched package, grouped by ``package.uid``."
    )
    attributes: list[str] = Field(
        [], description="Requested attribute keys that are not declared by any factory-registered provider."
    )
    parameters: dict[schema.Uid, list[schema.Parameter]] = Field(
        {}, description="Parameter overrides whose name is unknown to the owning package, grouped by ``package.uid``."
    )

    def __bool__(self) -> bool:
        """Return True if any invalid item exists."""
        return bool(self.modules or self.packages or self.models or self.attributes or self.parameters)


class ProblemConfig(BaseModel):
    """Missing dependencies discovered by :meth:`Pipeline.problem`.

    Lists packages whose owning module has not been added, packages still
    missing a model selection for a declared ``usage_models`` slot, and
    attribute keys that are not produced by any currently bound package.

    Attributes:
        missing_module_packages: Packages whose parent :class:`ModuleSpec`
            has not yet been appended to ``modules``.
        missing_model_packages: Packages with at least one empty
            ``usage_models`` slot and no corresponding model selected yet.
        attributes: Attribute keys required (or explicitly targeted) with
            no provider in ``packages``.
    """

    missing_module_packages: list[schema.Package] = Field(
        [], description="Packages whose parent :class:`ModuleSpec` has not yet been appended to ``modules``."
    )
    missing_model_packages: list[schema.Package] = Field(
        [],
        description="Packages with at least one empty ``usage_models`` slot and no corresponding model selected yet.",
    )
    attributes: list[str] = Field(
        [], description="Attribute keys required (or explicitly targeted) with no provider in ``packages``."
    )

    def __bool__(self) -> bool:
        """Return True if any unresolved dependency problem exists."""
        return bool(self.missing_module_packages or self.missing_model_packages or self.attributes)


class SolvedConfig(BaseModel):
    """Audit trail produced by :meth:`Pipeline.solve` describing what was auto-added.

    Enables callers to inspect exactly which modules, packages, attributes
    and models were introduced automatically, plus any sub-problems the
    solver could not fully resolve on its own.

    Attributes:
        add_modules: Module specs inserted into the pipeline config during
            the solve pass.
        add_packages: Packages inserted into the execution order as
            attribute providers.
        add_attributes: Target attribute keys for which a provider was
            successfully added.
        add_models: Model configurations selected automatically from
            package-level ``models`` lists.
        unsolved: Subset of :class:`ProblemConfig` items that the solver
            could not auto-resolve.
    """

    add_modules: list[schema.ModuleSpec] = Field(
        [], description="Module specs inserted into the pipeline config during the solve pass."
    )
    add_packages: list[schema.Package] = Field(
        [], description="Packages inserted into the execution order as attribute providers."
    )
    add_attributes: list[str] = Field(
        [], description="Target attribute keys for which a provider was successfully added."
    )
    add_models: list[schema.Model] = Field(
        [], description="Model configurations selected automatically from package-level ``models`` lists."
    )
    unsolved: ProblemConfig | None = Field(
        None, description="Subset of :class:`ProblemConfig` items that the solver could not auto-resolve."
    )

    def __bool__(self) -> bool:
        """Return True if anything changed or unsolved problems still remain."""
        return bool(self.add_modules or self.add_packages or self.add_attributes or self.add_models or self.unsolved)


class UnsatisfactionConfig(BaseModel):
    """Runtime blockers reported by :meth:`Pipeline.satisfied`.

    Lists modules whose PyPI/Git requirements are still missing, package and
    model :class:`Entry` references that cannot be imported, and models not
    yet on disk. ``imports`` carries diagnostic tuples for the most common
    failure cause (a missing Python package).

    Attributes:
        modules: Modules whose ``requirements`` or ``refs`` are not fully
            installed.
        entries: Package or model :class:`Entry` references that cannot be
            imported / are not callable.
        models: Model configurations whose files cannot be located in the
            local model cache.
        imports: Failed import diagnostics as
            ``[fully_qualified_entry, missing_python_package]`` tuples.
    """

    modules: list[schema.ModuleSpec] = Field(
        [], description="Modules whose ``requirements`` or ``refs`` are not fully installed."
    )
    entries: list[schema.Entry] = Field(
        [], description="Package or model :class:`Entry` references that cannot be imported / are not callable."
    )
    models: list[schema.Model] = Field(
        [], description="Model configurations whose files cannot be located in the local model cache."
    )
    imports: list[list[str]] = Field(
        [],
        description="Failed import diagnostics as ``[fully_qualified_entry, missing_python_package]`` tuples.",
    )

    def __bool__(self) -> bool:
        """Return True if any runtime prerequisite is still unsatisfied."""
        return bool(self.modules or self.entries or self.models)


InstallBackend = Literal["pip"]


class FactoryRequired(Exception):
    """Raised when a factory-dependent operation is called without a factory bound."""


class ModuleNotFound(Exception):
    """Raised when a requested module cannot be found in the factory."""


class PackageNotFound(Exception):
    """Raised when a requested package cannot be found in the factory."""


class ModelNotFound(Exception):
    """Raised when a requested model cannot be found in the factory."""


class AttributeNotProvided(Exception):
    """Raised when a requested attribute has no provider in the factory."""


class Pipeline:
    """A dependency-aware computation graph builder for algorithm packages.

    Declaratively specifies the desired attributes or packages, then resolves
    dependencies, selects models, and produces a runnable configuration for
    :class:`Runner` or :class:`ParallelRunner`.
    """

    def __init__(
        self,
        factory: Factory | None = None,
        *,
        config: PipelineConfig | None = None,
        name: str | None = None,
        description: str | None = None,
        packages: list[schema.Uid] | None = None,
        attributes: list[str] | None = None,
        models: dict[schema.Uid, list[schema.Uid]] | None = None,
        parameters: dict[schema.Uid, dict[str, Any]] | None = None,
    ):
        """Initialize a Pipeline.

        You may either pass a complete ``config`` directly, or supply the
        desired ``packages`` / ``attributes`` along with a ``factory`` so the
        pipeline can search for and wire the required modules automatically.

        Args:
            factory: Factory instance for querying modules, packages and models.
                Required when adding packages/attributes or calling solve().
            config: Pre-built pipeline configuration.
            name: Override pipeline name.
            description: Override pipeline description.
            packages: Initial package UIDs to add from the factory.
            attributes: Initial attribute names to target.
            models: Initial model selection keyed by package UID.
            parameters: Initial parameter overrides keyed by package UID.
        """
        if config is None:
            config = PipelineConfig.model_construct()

        self.__config = config
        self.__factory = factory

        if name is not None:
            self.__config.name = name
        if description is not None:
            self.__config.description = description

        if packages:
            self.add_packages(*packages)
        if attributes:
            self.add_attributes(*attributes)
        if models is not None:
            for package_uid, model_uids in models.items():
                self.set_models(package_uid, model_uids)
        if parameters is not None:
            for package_uid, values in parameters.items():
                self.set_parameters(package_uid, values)

    @property
    def name(self) -> str:
        return self.__config.name

    @name.setter
    def name(self, v: str):
        self.__config.name = v

    @property
    def description(self) -> str:
        return self.__config.description

    @description.setter
    def description(self, v: str):
        self.__config.description = v

    def _query_module(self, uid: schema.Uid) -> schema.ModuleSpec | None:
        return next((m for m in self.__config.modules if m.uid == uid), None)

    def _add_module(self, module: schema.ModuleSpec | None) -> bool:
        if module is None:
            return False
        if self._query_module(module.uid) is None:
            self.__config.modules.append(module.model_copy(deep=True))
            return True
        return False

    def _query_package(self, uid: schema.Uid) -> schema.Package | None:
        return next((p for p in self.__config.packages if p.uid == uid), None)

    def _add_package(self, package: schema.Package | None) -> bool:
        if package is None:
            return False
        if self._query_package(package.uid) is not None:
            return False

        provides = set(package.provides)
        inplace = provides.intersection(set(package.requires))

        packages = self.__config.packages
        insert_index = 0
        while insert_index < len(packages):
            # provide attributes must before other requires
            if any((attr in provides for attr in packages[insert_index].requires)):
                break
            # The package sorting requires considering their own requires and provides
            #   Solve package like in face/detection out face/detection
            if any((attr in inplace for attr in packages[insert_index].provides)):
                insert_index += 1
                break

            insert_index += 1

        self.__config.packages.insert(insert_index, package.model_copy(deep=True))
        return True

    def _has_attribute(self, attribute: str) -> bool:
        return next((a for a in self.__config.attributes if a == attribute), None) is not None

    def _add_attribute(self, attribute: str | None) -> bool:
        if attribute is None:
            return False
        if not self._has_attribute(attribute):
            self.__config.attributes.append(attribute)
            return True
        return False

    def _add_model(self, package_uid: str, model: schema.Model | None) -> bool:
        if model is None:
            return False

        package_models = self.__config.models.get(package_uid, None)
        if package_models is None:
            self.__config.models[package_uid] = [model.model_copy(deep=True)]
            return True

        if next((m for m in package_models if m.uid == model.uid), None) is None:
            package_models.append(model.model_copy(deep=True))
            return True
        return False

    def _remove_model(self, package_uid: str, model_uid: str) -> bool:
        if package_uid not in self.__config.models:
            return False

        package_models = self.__config.models[package_uid]
        model_index: int | None = next((i for i, m in enumerate(package_models) if m.uid == model_uid), None)
        if model_index is None:
            return False

        del package_models[model_index]
        return True

    def _set_parameter(self, package_uid: str, parameter: schema.Parameter | None):
        if parameter is None:
            return

        package_parameters = self.__config.parameters.get(package_uid, None)
        if package_parameters is None:
            self.__config.parameters[package_uid] = [parameter.model_copy(deep=True)]
            return

        parameter_index: int | None = next(
            (i for i, p in enumerate(package_parameters) if p.name == parameter.name), None
        )
        if parameter_index is None:
            package_parameters.append(parameter.model_copy(deep=True))
            return

        package_parameters[parameter_index] = parameter.model_copy(deep=True)

    def add_packages(self, uid: str | Iterable[str], /, *uids: str):
        ids = [uid] if isinstance(uid, str) else list(uid)
        ids = [*ids, *uids]
        if self.__factory is None:
            raise FactoryRequired

        for package_uid in ids:
            # check package exists first
            existing_package = self._query_package(package_uid)
            if existing_package is not None:
                continue
            # query package
            factory_package = self.__factory.query_package(package_uid)
            if factory_package is None:
                raise PackageNotFound(package_uid)
            # append package
            if self._add_package(factory_package):
                logger.debug(f"Add package {package_uid}")
                # append module
                if factory_module := self.__factory.query_module_of_package(package_uid):
                    if self._add_module(factory_module.module):
                        logger.debug(f"Add module {factory_module.module.uid}")

    def get_package(
        self,
        *,
        uid: schema.Uid | None = None,
        name: str | None = None,
        provide: str | None = None,
    ) -> schema.Package | None:
        """Query the first matching package in the current configuration.

        Lookup priority: ``uid`` > ``name`` > ``provide``.

        Args:
            uid: Match by package unique ID.
            name: Match by package display name.
            provide: Match by an attribute the package provides.

        Returns:
            The first matched package, or ``None`` if not found.
        """
        if uid is not None:
            return self._query_package(uid)
        if name is not None:
            return next((p for p in self.__config.packages if p.name == name), None)
        if provide is not None:
            return next((p for p in self.__config.packages if provide in p.provides), None)
        return None

    def add_attributes(self, attr: str | Iterable[str], /, *attrs: str):
        names = [attr] if isinstance(attr, str) else list(attr)
        names = [*names, *attrs]
        if self.__factory is None:
            raise FactoryRequired

        for attr_name in names:
            # check name exists first
            if self._has_attribute(attr_name):
                continue
            # query providers
            providers = self.__factory.query_attribute_providers(attr_name)
            if not providers:
                raise AttributeNotProvided(attr_name)
            # append attributes
            self.__config.attributes.append(attr_name)
            logger.debug(f"Add attribute {attr_name}")

    def add_model(self, package_uid: schema.Uid, model_uid: schema.Uid):
        if self.__factory is None:
            raise FactoryRequired

        model = self.__factory.query_model(model_uid)
        if model is None:
            raise ModelNotFound(model_uid)

        if self._add_model(package_uid, model):
            logger.debug(f"Add model {package_uid} {model_uid}")

    def set_models(self, package_uid: schema.Uid, model_uids: Iterable[schema.Uid]):
        if self.__factory is None:
            raise FactoryRequired

        missing_model_uids: list[schema.Uid] = []
        found_models: list[schema.Model] = []
        for model_uid in model_uids:
            model = self.__factory.query_model(model_uid)
            if model is None:
                missing_model_uids.append(model_uid)
            else:
                found_models.append(model)

        if missing_model_uids:
            raise ModelNotFound(missing_model_uids)

        self.__config.models.clear()
        for model in found_models:
            if self._add_model(package_uid, model):
                logger.debug(f"Set model {package_uid} {model.uid}")

    def remove_model(self, package_uid: schema.Uid, model_uid: schema.Uid):
        if self.__factory is None:
            raise FactoryRequired

        if self._remove_model(package_uid, model_uid):
            logger.debug(f"Remove model {package_uid} {model_uid}")

    def _remove_package(self, package_uid: str) -> bool:
        package_index: int | None = next(
            (i for i, p in enumerate(self.__config.packages) if p.uid == package_uid), None
        )
        if package_index is None:
            return False

        del self.__config.packages[package_index]

        if package_uid in self.__config.models:
            del self.__config.models[package_uid]

        if package_uid in self.__config.parameters:
            del self.__config.parameters[package_uid]

        return True

    def _remove_module(self, module_uid: str) -> bool:
        module_index: int | None = next((i for i, m in enumerate(self.__config.modules) if m.uid == module_uid), None)
        if module_index is None:
            return False

        del self.__config.modules[module_index]
        return True

    def remove_package(self, uid: str | Iterable[str], /, *uids: str):
        ids = [uid] if isinstance(uid, str) else list(uid)
        ids = [*ids, *uids]
        if self.__factory is None:
            raise FactoryRequired

        affected_module_uids: set[str] = set()

        for package_uid in ids:
            if factory_module := self.__factory.query_module_of_package(package_uid):
                affected_module_uids.add(factory_module.module.uid)
            if self._remove_package(package_uid):
                logger.debug(f"Remove package {package_uid}")

        remaining_module_uids: set[str] = set()
        for package in self.__config.packages:
            if factory_module := self.__factory.query_module_of_package(package.uid):
                remaining_module_uids.add(factory_module.module.uid)

        orphan_module_uids = affected_module_uids - remaining_module_uids
        for module_uid in orphan_module_uids:
            if self._remove_module(module_uid):
                logger.debug(f"Remove module {module_uid}")

    def set_parameters(self, package_uid: schema.Uid, values: dict[str, Any]):
        if self.__factory is None:
            raise FactoryRequired

        for name, value in values.items():
            factory_parameter = self.__factory.query_parameter(package_uid, name)
            if factory_parameter is None:
                sp_kwargs: dict[str, Any] = {"name": name, "value": value}
                parameter = schema.Parameter(**sp_kwargs)
            else:
                parameter = factory_parameter.model_copy(deep=True, update={"value": value})
            self._set_parameter(package_uid, parameter)
            logger.debug(f"Set parameter {package_uid} {name}={value}")

    def reset_parameters(self, package_uid: schema.Uid, values: dict[str, Any]):
        self.clear_parameters(package_uid)
        self.set_parameters(package_uid, values)

    def clear_parameters(self, package_uid: schema.Uid):
        logger.debug(f"Clear parameters of package ({package_uid})")
        if package_uid in self.__config.parameters:
            del self.__config.parameters[package_uid]

    @property
    def config(self) -> PipelineConfig:
        """Return the current working pipeline configuration.

        You can persist this object to a file and reconstruct the pipeline
        from it later. Avoid mutating the returned value directly unless you
        are aware of the consistency implications.

        Returns:
            Current working pipeline configuration.
        """
        return self.__config

    @property
    def packages(self) -> list[schema.Package]:
        """Return the ordered list of packages in the pipeline."""
        return self.__config.packages

    @property
    def attributes(self) -> list[str]:
        """Return the explicitly requested attribute names."""
        return self.__config.attributes

    @property
    def hidden_attributes(self) -> list[str]:
        """Return attributes provided by packages but not explicitly requested."""
        packages = self.__config.packages
        pipeline_attributes = unique_list([attr for p in packages for attr in p.provides])

        current_attributes = set(self.__config.attributes)
        return [k for k in pipeline_attributes if k not in current_attributes]

    @property
    def inputs(self) -> list[str]:
        """Return the required input modal names.

        Returns:
            Input modal names. Falls back to ``["default"]`` when no package
            declares a specific input.
        """
        packages = self.__config.packages

        inputs = [input_name for p in packages for input_name in p.inputs]

        inputs = unique_list(inputs)

        return ["default"] if not inputs else inputs

    def requirements(self) -> list[str]:
        """Return all Python package requirements across included modules.

        Returns:
            Deduplicated list of requirement strings.
        """
        modules = self.__config.modules
        requirements = [req for m in modules for req in m.requirements]

        return unique_list(requirements)

    def get_models(self, package_uid: schema.Uid) -> list[schema.Model]:
        return self.__config.models.get(package_uid, [])

    def get_parameters(self, package_uid: schema.Uid) -> list[schema.Parameter]:
        return self.__config.parameters.get(package_uid, [])

    def get_parameter(self, package_uid: schema.Uid, name: str) -> schema.Parameter | None:
        parameters = self.get_parameters(package_uid)
        for p in parameters:
            if p.name == name:
                return p
        return None

    def validate(self, *, update: bool = False) -> InvalidConfig | None:
        """Validate pipeline items against the factory.

        Checks include:
            1. Optionally updates modules/packages/models to factory versions.
            2. Verifies attributes/parameters exist in the factory.

        Note:
            This method only validates structural integrity; it does **not**
            perform dependency analysis. Call :meth:`solve` to add missing
            dependencies automatically.

        Args:
            update: When True, overwrite existing config entries with fresh
                copies from the factory where possible.

        Returns:
            :class:`InvalidConfig` with invalid items, or ``None`` if valid.

        Raises:
            FactoryRequired: If no factory is bound to the pipeline.
        """
        if self.__factory is None:
            raise FactoryRequired

        # check modules
        invalid_modules: list[schema.ModuleSpec] = []
        modules = self.__config.modules
        for i, m in enumerate(modules):
            fm = self.__factory.query_module(m.uid)
            if fm is None:
                logger.warning(f"Found invalid module [{m.name}]({m.uid})")
                invalid_modules.append(m)
                continue
            if update:
                modules[i] = fm.module.model_copy(deep=True)

        # check packages
        invalid_packages: list[schema.Package] = []
        packages = self.__config.packages
        for i, p in enumerate(packages):
            fp = self.__factory.query_package(p.uid)
            if fp is None:
                logger.warning(f"Found invalid package [{p.name}]({p.uid})")
                invalid_packages.append(p)
                continue
            if update:
                packages[i] = fp.model_copy(deep=True)

        # check models
        invalid_models: dict[schema.Uid, list[schema.Model]] = defaultdict(list)
        package_models = self.__config.models
        for package_uid, models in package_models.items():
            package = self.__factory.query_package(package_uid)
            if package is None:
                logger.warning(f"Found non exists package ({package_uid}) in models config")
                invalid_models[package_uid] = models
                continue
            for i, model in enumerate(models):
                factory_model = self.__factory.query_model(model.uid)
                factory_package = self.__factory.query_package_of_model(model.uid)
                if factory_model is None or package.uid != factory_package:
                    logger.warning(
                        f"Found package [{package.name}]({package.uid}) invalid model [{model.name}]({model.uid})"
                    )
                    invalid_models[package_uid].append(model)
                    continue
                if update:
                    models[i] = factory_model.model_copy(deep=True)

        # check attributes
        invalid_attributes: list[str] = []
        factory_attributes = set(self.__factory.attributes)
        for attr in self.__config.attributes:
            if attr not in factory_attributes:
                logger.warning(f"Found invalid attribute {attr}")
                invalid_attributes.append(attr)

        # check parameters
        invalid_parameters: dict[schema.Uid, list[schema.Parameter]] = defaultdict(list)
        package_parameters = self.__config.parameters
        for package_uid, parameters in package_parameters.items():
            factory_package = self.__factory.query_package(package_uid)
            if factory_package is None:
                logger.warning(f"Found non exists package ({package_uid}) in parameters config")
                invalid_parameters[package_uid] = parameters
                continue
            for i, param in enumerate(parameters):
                factory_param = self.__factory.query_parameter(package_uid, param.name)
                if factory_param is None:
                    logger.warning(
                        f"Found package [{factory_package.name}]({factory_package.uid})"
                        f" invalid parameter {param.name}={param.value}"
                    )
                    invalid_parameters[package_uid].append(param)
                    continue
                if update:
                    parameters[i] = factory_param.model_copy(deep=True, update={"value": param.value})

        invalid = invalid_modules or invalid_packages or invalid_models or invalid_attributes or invalid_parameters

        if not invalid:
            return None

        return InvalidConfig(
            modules=invalid_modules,
            packages=invalid_packages,
            models={**invalid_models},
            attributes=invalid_attributes,
            parameters={**invalid_parameters},
        )

    def problem(self) -> ProblemConfig | None:
        """Check for missing attribute providers, modules, or model selections.

        Returns:
            :class:`ProblemConfig` describing the issues, or ``None`` if all
            dependencies are satisfied.

        Raises:
            FactoryRequired: If no factory is bound to the pipeline.
        """
        if self.__factory is None:
            raise FactoryRequired

        # TODO: check sort of packages, prevent provided attributes are later than requires.

        # check attributes
        problem_attributes: list[str] = []
        packages = self.__config.packages
        provide_attributes = set([attr for p in packages for attr in set(p.provides) - set(p.requires)])
        require_attributes = unique_list([attr for p in packages for attr in p.requires])

        check_attributes = unique_list(self.__config.attributes + require_attributes)
        for attr in check_attributes:
            if attr not in provide_attributes:
                problem_attributes.append(attr)

        # check modules
        modules = self.__config.modules
        module_packages: list[schema.Package] = []
        for module in modules:
            factory_module = self.__factory.query_module(module.uid)
            if factory_module is None:
                continue
            module_packages.extend(factory_module.packages)

        module_packages_uids = set([p.uid for p in module_packages])
        missing_module_packages: list[schema.Package] = []
        for package in packages:
            if package.uid not in module_packages_uids:
                logger.debug(f"Found missing module package [{package.name}]({package.uid})")
                missing_module_packages.append(package.model_copy(deep=True))

        # check models
        missing_model_packages: list[schema.Package] = []
        for package in packages:
            problem_models: list[str] = []
            usage_models = package.usage_models
            config_models = self.__config.models.get(package.uid, [])

            if not config_models:
                if package.models:
                    problem_models.extend(usage_models if usage_models else ["*"])
            else:
                config_model_usages = set([m.usage for m in config_models])
                for usage in usage_models:
                    if usage not in config_model_usages:
                        problem_models.append(usage)

            if problem_models:
                log_models = ", ".join(problem_models)
                logger.debug(f"Found package [{package.name}]({package.uid}) mising models: {log_models}")
                missing_model_packages.append(package.model_copy(deep=True, update={"usage_models": problem_models}))

        if problem_attributes:
            log_attributes = ", ".join(problem_attributes)
            logger.debug(f"Found not provided attributes {log_attributes}")

        has_problem = missing_module_packages or missing_model_packages or problem_attributes

        if not has_problem:
            return None

        return ProblemConfig(
            missing_module_packages=missing_module_packages,
            missing_model_packages=missing_model_packages,
            attributes=problem_attributes,
        )

    def solve(self, ignore_models: bool = False) -> SolvedConfig | None:
        """Resolve missing dependencies by adding packages, modules, and models.

        Iteratively adds attribute providers and their parent modules until
        all requested attributes can be produced. Then fills in missing model
        selections using recommended defaults from the factory.

        Args:
            ignore_models: When True, skip automatic model selection and only
                resolve packages/modules.

        Returns:
            :class:`SolvedConfig` describing what was added (and any
            remaining unsolved problems), or ``None`` if nothing changed.

        Raises:
            FactoryRequired: If no factory is bound to the pipeline.
        """
        problem = self.problem()
        if problem is None:
            return None

        if self.__factory is None:
            raise FactoryRequired

        solved = SolvedConfig.model_construct()
        unsolved = ProblemConfig.model_construct()

        handled_attributes: set[str] = set()
        while True:
            # solve attributes
            problem_attributes = [attr for attr in problem.attributes if attr not in handled_attributes]
            if not problem_attributes:
                break

            package_added = False
            for attr in problem_attributes:
                handled_attributes.add(attr)

                providers = self.__factory.query_attribute_providers(attr)
                if not providers:
                    unsolved.attributes.append(attr)
                    continue

                # select provider
                provider = max(providers, key=lambda x: (x.priority, x.format_version))
                if self._add_package(provider):
                    logger.info(f"Solve required package [{provider.name}]({provider.uid}) for attribute {attr}")
                    solved.add_packages.append(provider.model_copy(deep=True))
                    package_added = True

                # solved this attributes
                solved.add_attributes.append(attr)

                # add provider's module
                factory_module = self.__factory.query_module_of_package(provider.uid)
                if factory_module is not None:
                    if self._add_module(factory_module.module):
                        module_spec = factory_module.module
                        logger.info(
                            f"Solve required module [{module_spec.name}]({module_spec.uid}) "
                            f"for package [{provider.name}]({provider.uid})"
                        )
                        solved.add_modules.append(factory_module.module.model_copy(deep=True))

            if package_added:
                problem = self.problem()
                if problem is None:
                    break

        # check problem has solved
        if problem is None:
            solved.unsolved = unsolved if unsolved else None
            return solved if solved else None

        # solve modules
        for package in problem.missing_module_packages:
            factory_module = self.__factory.query_module_of_package(package.uid)
            if factory_module is None:
                unsolved.missing_module_packages.append(package)
                continue
            # add module
            if self._add_module(factory_module.module):
                module_spec = factory_module.module
                logger.info(
                    f"Solve required module [{module_spec.name}]({module_spec.uid})"
                    f" for package [{package.name}]({package.uid})"
                )
                solved.add_modules.append(factory_module.module.model_copy(deep=True))

        # ignore models
        if ignore_models:
            solved.unsolved = unsolved if unsolved else None
            return solved if solved else None

        # solve models
        for package in problem.missing_model_packages:
            factory_package = self.__factory.query_package(package.uid)
            if factory_package is None or not factory_package.models:
                unsolved.missing_model_packages.append(package)
                continue

            package_models: list[schema.Model] = factory_package.models
            package_recommended_models: list[schema.Model] = []

            package_usage_models: dict[str, list[schema.Model]] = defaultdict(list)
            package_recommended_usage_models: dict[str, list[schema.Model]] = defaultdict(list)

            for factory_model in factory_package.models:
                package_usage_models[factory_model.usage].append(factory_model)
                if factory_model.recommended:
                    package_recommended_models.append(factory_model)
                    package_recommended_usage_models[factory_model.usage].append(factory_model)

            still_missing_model_usages: list[str] = []
            prepare_models: list[schema.Model] = []
            for model_usage in package.usage_models:
                if model_usage == "*":
                    selected_model = package_recommended_models[0] if package_recommended_models else package_models[0]
                    prepare_models.append(selected_model)
                    continue

                current_recommended_models = package_recommended_usage_models.get(model_usage, None)
                current_models = package_usage_models.get(model_usage, None)
                if not current_models:
                    still_missing_model_usages.append(model_usage)
                    continue

                selected_model = current_recommended_models[0] if current_recommended_models else current_models[0]
                prepare_models.append(selected_model)

            if still_missing_model_usages:
                unsolved.missing_model_packages.append(
                    package.model_copy(deep=True, update={"usage_models": still_missing_model_usages})
                )

            for model in prepare_models:
                if self._add_model(package_uid=package.uid, model=model):
                    logger.info(
                        f"Solve package [{package.name}]({package.uid}) required model [{model.name}]({model.uid})"
                    )
                    solved.add_models.append(model.model_copy(deep=True))

        if unsolved:
            logger.warning(f"Pipeline still has unsolved problem: {unsolved}")

        # return solve report
        solved.unsolved = unsolved if unsolved else None
        return solved if solved else None

    def satisfied(self, *, cache_dir: str | None = None) -> tuple[bool, UnsatisfactionConfig | None]:
        """Check whether the pipeline is ready to run.

        Verifies:
            1. All module Python package requirements are installed.
            2. Package and model entry points can be imported successfully.
            3. All configured models are present in the local cache.

        Args:
            cache_dir: Override the model cache directory for this check.

        Returns:
            A 2-tuple ``(ready, report)`` where ``ready`` is ``True`` when the
            pipeline can be executed, and ``report`` is either
            :class:`UnsatisfactionConfig` describing blockers or ``None``.
        """
        un_imports: list[list[str]] = []
        un_modules: list[schema.ModuleSpec] = []
        for module in self.__config.modules:
            un_requirements = unsatisfied_requirements(module)
            if not un_requirements:
                continue
            log_requirements = " ".join(un_requirements)
            logger.debug(f"Unsatisfied module [{module.name}]({module.uid}) requirements: {log_requirements}")
            un_modules.append(module.model_copy(deep=True, update={"requirements": un_requirements}))

        un_entries: list[schema.Entry] = []
        for package in self.__config.packages:
            package_entry, pname = import_entry(package.entry)
            if package_entry is None:
                entry_method = package.entry.method
                if package.entry.package:
                    entry_method = ".".join([package.entry.package, entry_method])

                if pname:
                    logger.debug(
                        f'Can not import package entry "{entry_method}", because it has failed to import "{pname}"'
                    )
                    un_imports.append([entry_method, pname])

                logger.debug(f"Unsatisfied package entry method {entry_method}")
                un_entries.append(package.entry)

        un_models: list[schema.Model] = []
        for models in self.__config.models.values():
            for model in models:
                # check model entry
                if model.entry is not None:
                    model_entry, pname = import_entry(model.entry)
                    if model_entry is None:
                        entry_method = model.entry.method
                        if model.entry.package:
                            entry_method = ".".join([model.entry.package, entry_method])

                        if pname:
                            logger.debug(
                                f'Can not import model entry "{entry_method}"'
                                f', because it has failed to import "{pname}"'
                            )
                            un_imports.append([entry_method, pname])

                        logger.debug(f"Unsatisfied model entry method {entry_method}")
                        un_entries.append(model.entry)
                        continue
                # check model exists
                if not exists_model(model, cache_dir=cache_dir):
                    logger.debug(f"Unsatisfied uncached model [{model.name}]({model.uid})")
                    un_models.append(model)

        unsatisfied = un_modules or un_entries or un_models or un_imports

        if not unsatisfied:
            return True, None

        return False, UnsatisfactionConfig(modules=un_modules, entries=un_entries, models=un_models, imports=un_imports)

    def install_requirements(self, *, backend: InstallBackend = "pip"):
        """Install Python package requirements for all included modules.

        Args:
            backend: Reserved for future backend selection; currently uses
                pip regardless of this value.
        """
        for module in self.__config.modules:
            log_requirements = " ".join(module.requirements)
            logger.info(f"Install requirements of module [{module.name}]({module.uid}): {log_requirements}")
            install_module_requirements(module)

    def cache_models(self, *, cache_dir: str | None = None):
        """Download and cache all selected models locally.

        Args:
            cache_dir: Override the model cache directory.

        Raises:
            Exception: Propagates any download/build error from the model.
                (Not caught in the current implementation.)
        """
        for models in self.__config.models.values():
            for model_config in models:
                logger.info(f"Cache model [{model_config.name}]({model_config.uid})")
                # Exceptions may be thrown by build model and cache,
                # which are not handled in the current version
                model = build_model(model_config, cache_dir=cache_dir)
                model.cache()


def test():
    pass


if __name__ == "__main__":
    test()
