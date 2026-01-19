# -*- coding: utf-8 -*-

from collections import defaultdict
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field

from fabopsy_lib import schema
from fabopsy_lib.runtime.factory import Factory
from fabopsy_lib.runtime.model import build_model, exists_model
from fabopsy_lib.utils.pencilbox import unique_list
from fabopsy_lib.runtime.actions import unsatisfied_requirements, install_requirements, import_entry

__all__ = [
    'Pipeline',
]

class PipelineConfig(BaseModel):
    name: str = Field('')
    description: str = Field('')

    modules: list[schema.ModuleSpec] = Field([])
    packages: list[schema.Package] = Field([])
    attributes: list[str] = Field([])

    parameters: dict[str, list[schema.Parameter]] = Field({})
    models: dict[schema.Uid, list[schema.Model]] = Field({})


class InvalidConfig(BaseModel):
    modules: list[schema.ModuleSpec] = Field([])
    packages: list[schema.Package] = Field([])
    models: dict[schema.Uid, list[schema.Model]] = Field({})
    attributes: list[str] = Field([])
    parameters: dict[schema.Uid, list[schema.Parameter]] = Field({})

    def __bool__(self):
        return bool(self.modules or self.packages or self.models or self.attributes or self.parameters)


class ProblemConfig(BaseModel):
    missing_module_packages: list[schema.Package] = Field(
        [], description='no module contains those packages')
    missing_model_packages: list[schema.Package] = Field(
        [], description='missing model in usage_models')
    attributes: list[str] = Field(
        [], description='attributes required but not provided in packages')

    def __bool__(self):
        return bool(self.missing_module_packages or self.missing_model_packages or self.attributes)


class SolvedConfig(BaseModel):
    add_modules: list[schema.ModuleSpec] = Field([])
    add_packages: list[schema.Package] = Field([])
    add_attributes: list[str] = Field([])
    add_models: list[schema.Model] = Field([])

    unsolved: ProblemConfig | None = Field(None)

    def __bool__(self):
        return bool(self.add_modules or self.add_packages or self.add_attributes or self.add_models or self.unsolved)


class UnsatisfactoryConfig(BaseModel):
    modules: list[schema.ModuleSpec] = Field(
        [], description='module requirement has not satisfied')
    entries: list[schema.Entry] = Field(
        [], description='package/model entry is not callable')
    models: list[schema.Model] = Field(
        [], description='model did not exists in cache')

    def __bool__(self):
        return bool(self.modules or self.entries or self.models)


InstallBackend = Literal['pip']


class FactoryRequired(Exception):
    pass


class ModuleNotFound(Exception):
    pass


class PackageNotFound(Exception):
    pass


class ModelNotFound(Exception):
    pass


class AttributeNotProvided(Exception):
    pass


class Pipeline(object):
    def __init__(self,
                 factory: Factory = None,
                 *,
                 config: PipelineConfig = None,
                 name: str = None,
                 description: str = None,
                 packages: list[schema.Uid] = None,
                 attributes: list[str] = None,
                 models: dict[schema.Uid, list[schema.Uid]] = None,
                 parameters: dict[schema.Uid, dict[str, Any]] = None):
        """
        To initialize a pipeline, you can either directly provide a config.
        Or supply the required packages or attributes,
            then we will then search for and construct the pipeline in the factory.
        :param factory:
        :param config: Pipeline config.
        :param packages:
        :param attributes:
        :param name:
        :param description:
        TODO: Add log in validate, solve, install and cache
        """
        if config is None:
            config = PipelineConfig(**{})

        self.__config = config
        self.__factory = factory

        if name is not None:
            self.__config.name = name
        if description is not None:
            self.__config.description = description

        if packages is not None:
            self.add_packages(*packages)
        if attributes is not None:
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
            self.__config.modules.append(module.model_copy())
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

        packages = self.__config.packages
        insert_index = 0
        while insert_index < len(packages):
            if any((attr in provides for attr in packages[insert_index].requires)):
                break
            insert_index += 1

        self.__config.packages.insert(insert_index, package.model_copy())
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
            self.__config.models[package_uid] = [model.model_copy()]
            return True

        if next((m for m in self.__config.models if m.uid == model.uid), None) is None:
            package_models.append(model)
            return True

        return False

    def _set_parameter(self, package_uid: str, parameter: schema.Parameter | None):
        if parameter is None:
            return

        pacakge_parameters = self.__config.parameters.get(package_uid, None)
        if pacakge_parameters is None:
            self.__config.parameters[package_uid] = [parameter.model_copy()]
            return

        parameter_index: int | None = next(
            (i for i, p in enumerate(pacakge_parameters) if p.name == parameter.name), None)
        if parameter_index is None:
            pacakge_parameters.append(parameter.model_copy())
            return

        pacakge_parameters[parameter_index] = parameter.model_copy()

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
            self.__config.packages.append(factory_package)
            # query the module
            factory_module = self.__factory.query_module_of_package(package_uid)
            # append module
            if factory_module:
                self._add_module(factory_module.module)

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

    def add_model(self, package_uid: schema.Uid, model_uid: schema.Uid):
        if self.__factory is None:
            raise FactoryRequired

        model = self.__factory.query_model(model_uid)
        if model is None:
            raise ModelNotFound(model_uid)

        self._add_model(package_uid, model)

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
            self._add_model(package_uid, model)

    def set_parameters(self, package_uid: schema.Uid, values: dict[str, Any]):
        if self.__factory is None:
            raise FactoryRequired

        for name, value in values.items():
            factory_parameter = self.__factory.query_parameter(package_uid, name)
            if factory_parameter is None:
                self._set_parameter(package_uid, schema.Parameter(name=name, value=value, **{}))
            else:
                self._set_parameter(package_uid, factory_parameter.model_copy(update={'value': value}))

    def reset_parameters(self, package_uid: schema.Uid, values: dict[str, Any]):
        self.clear_parameters(package_uid)
        self.set_parameters(package_uid, values)

    def clear_parameters(self, package_uid: schema.Uid):
        if package_uid in self.__config.parameters:
            del self.__config.parameters[package_uid]

    @property
    def config(self) -> PipelineConfig:
        """
        Current working pipeline.
        You can persist this object to a file and reconstruct it.
        However, do not directly modify the return value here unless you are fully aware of what you are doing.
        :return: Current working pipeline.
        """
        return self.__config

    @property
    def packages(self) -> list[schema.Package]:
        return self.__config.packages

    @property
    def attributes(self) -> list[str]:
        return self.__config.attributes

    @property
    def hidden_attributes(self) -> list[str]:
        packages = self.__config.packages
        pipeline_attributes = unique_list([attr for p in packages for attr in p.provides])

        current_attributes = set(self.__config.attributes)
        return [k for k in pipeline_attributes if k not in current_attributes]

    @property
    def inputs(self) -> list[str]:
        """
        Get input modals, default is ['default']
        :return:
        """
        packages = self.__config.packages

        inputs = [input_name for p in packages for input_name in p.inputs]

        inputs = unique_list(inputs)

        return ['default'] if not inputs else inputs

    def requirements(self) -> list[str]:
        """
        Get all module requirements
        :return:
        """
        modules = self.__config.modules
        requirements = [req for m in modules for req in m.requirements]

        return unique_list(requirements)

    def validate(self, *, update: bool = False) -> InvalidConfig | None:
        """
        Validate pipeline with factory modules, include:
            1. Update modules/packages/models if they were in factory
            2. Check attributes/parameters exists or not
        Notice: This function will change config via factory.
        Notice: This function supports verifying whether the configuration is valid,
            and does not perform dependency analysis.
            If missing dependencies need to be added, the `solve` method should be called.
        :param update: If update config according to factory
        :return:
        """
        if self.__factory is None:
            raise FactoryRequired

        # check modules
        invalid_modules: list[schema.ModuleSpec] = []
        modules = self.__config.modules
        for i, m in enumerate(modules):
            fm = self.__factory.query_module(m.uid)
            if fm is None:
                invalid_modules.append(m)
                continue
            if update:
                modules[i] = fm.module.model_copy()

        # check packages
        invalid_packages: list[schema.Package] = []
        packages = self.__config.packages
        for i, p in enumerate(packages):
            fp = self.__factory.query_package(p.uid)
            if fp is None:
                invalid_packages.append(p)
                continue
            if update:
                packages[i] = fp.model_copy()

        # check models
        invalid_models: dict[schema.Uid, list[schema.Model]] = defaultdict([])
        package_models = self.__config.models
        for package_uid, models in package_models.items():
            package = self.__factory.query_package(package_uid)
            if package is None:
                invalid_models[package_uid] = models
                continue
            for i, model in enumerate(models):
                fmodel = self.__factory.query_model(model.uid)
                fpackage = self.__factory.query_package_of_model(model.uid)
                if fmodel is None or package.uid != fpackage:
                    invalid_models[package_uid].append(model)
                    continue
                if update:
                    models[i] = fmodel.model_copy()

        # check attributes
        invalid_attributes: list[str] = []
        factory_attributes = set(self.__factory.attributes)
        for attr in self.__config.attributes:
            if attr not in factory_attributes:
                invalid_attributes.append(attr)

        # check parameters
        invalid_parameters: dict[schema.Uid, list[schema.Parameter]] = defaultdict([])
        package_parameters = self.__config.parameters
        for package_uid, parameters in package_parameters.items():
            factory_package = self.__factory.query_package(package_uid)
            if factory_package is None:
                invalid_parameters[package_uid] = parameters
                continue
            for i, param in enumerate(parameters):
                factory_param = self.__factory.query_parameter(package_uid, param.name)
                if factory_param is None:
                    invalid_parameters[package_uid].append(param)
                    continue
                if update:
                    parameters[i] = factory_param.model_copy(update={'value': param.value})

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
        """
        Check whether the current pipeline lacks attribute dependencies or model dependencies.
        :return:
        """
        if self.__factory is None:
            raise FactoryRequired

        # check attributes
        problem_attributes: list[str] = []
        packages = self.__config.packages
        provide_attributes = set([attr for p in packages for attr in p.provides])
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
                missing_module_packages.append(package.model_copy())

        # check models
        missing_model_packages: list[schema.Package] = []
        for package in packages:
            problem_models: list[str] = []
            usage_models = package.usage_models
            config_models = self.__config.models.get(package.uid, [])

            if not config_models:
                if package.models:
                    problem_models.extend(usage_models if usage_models else ['*'])
            else:
                config_model_usages = set([m.usage for m in config_models])
                for usage in usage_models:
                    if usage not in config_model_usages:
                        problem_models.append(usage)

            if problem_models:
                missing_model_packages.append(package.model_copy(update={'usage_models': problem_models}))

        has_problem = missing_module_packages or missing_model_packages or problem_attributes

        if not has_problem:
            return None

        return ProblemConfig(
            missing_module_packages=missing_module_packages,
            missing_model_packages=missing_model_packages,
            attributes=problem_attributes,
        )

    def solve(self) -> SolvedConfig | None:
        """
        For modules loaded through factory, check for missing attributes or package dependencies.
        Supplement models that have not been selected.
        :return: If nothing is done, it will return None.
        """
        problem = self.problem()
        if problem is None:
            return None

        if self.__factory is None:
            raise FactoryRequired

        solved = SolvedConfig(**{})
        unsolved = ProblemConfig(**{})

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
                # TODO: Design a more reasonable algorithm to select providers
                provider = max(providers, key=lambda x: x.format_version)
                if self._add_package(provider) is not None:
                    solved.add_packages.append(provider.model_copy())
                    package_added = True

                # solved this attributes
                solved.add_attributes.append(attr)

                # add provider's module
                factory_module = self.__factory.query_module_of_package(provider.uid)
                if factory_module is not None:
                    if self._add_module(factory_module.module) is not None:
                        solved.add_modules.append(factory_module.module.model_copy())

            if package_added:
                problem = self.problem()

        # solve modules
        for package in problem.missing_module_packages:
            factory_module = self.__factory.query_module_of_package(package.uid)
            if factory_module is None:
                unsolved.missing_module_packages.append(package)
                continue
            # add module
            if self._add_module(factory_module.module) is not None:
                solved.add_modules.append(factory_module.module.model_copy())

        # solve models
        for package in problem.missing_model_packages:
            factory_package = self.__factory.query_package(package.uid)
            if factory_package is None or not factory_package.models:
                unsolved.missing_model_packages.append(package)
                continue

            # TODO: use recommended model by default
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
                if model_usage == '*':
                    selected_model = package_recommended_models[0] \
                        if package_recommended_models else package_models[0]
                    prepare_models.append(selected_model)
                    continue

                current_recommended_models = package_recommended_usage_models.get(model_usage, None)
                current_models = package_usage_models.get(model_usage, None)
                if not current_models:
                    still_missing_model_usages.append(model_usage)
                    continue

                selected_model = current_recommended_models[0] \
                    if current_recommended_models else current_models[0]
                prepare_models.append(selected_model)

            if still_missing_model_usages:
                unsolved.missing_model_packages.append(package.model_copy(
                    update={'usage_models': still_missing_model_usages}))

            for model in prepare_models:
                if self._add_model(package_uid=package.uid, model=model):
                    solved.add_models.append(model.model_copy())

        # return solve report
        solved.unsolved = unsolved if unsolved else None
        return solved if solved else None

    def satisfied(self, *, cache_dir: str = None) -> tuple[bool, UnsatisfactoryConfig | None]:
        """
        To check whether the current pipeline is ready to start running, the following conditions will be checked:
            1. Whether the requirements of all modules have been met.
            2. Whether the entries of packages and models can be imported and the calling functions can be obtained.
        :return:
        """
        un_modules: list[schema.ModuleSpec] = []
        for module in self.__config.modules:
            un_requirements = unsatisfied_requirements(module)
            if not un_requirements:
                continue
            un_modules.append(module.model_copy(update={'requirements': un_requirements}))

        un_entries: list[schema.Entry] = []
        for package in self.__config.packages:
            package_entry = import_entry(package.entry)
            if package_entry is None:
                un_entries.append(package.entry)

        un_models: list[schema.Model] = []
        for models in self.__config.models.values():
            for model in models:
                # check model entry
                if model.entry is not None:
                    model_entry = import_entry(model.entry)
                    if model_entry is None:
                        un_entries.append(model.entry)
                        continue
                # check model exists
                if not exists_model(model, cache_dir=cache_dir):
                    un_models.append(model)

        unsatisfied = un_modules or un_entries or un_models

        if not unsatisfied:
            return True, None

        return False, UnsatisfactoryConfig(
            modules=un_modules,
            entries=un_entries,
            models=un_models,
        )

    def install_requirements(self, *, backend: InstallBackend = 'pip'):
        """
        Install all unsatisfied requirements
        :param backend: This parameter is retained but currently has no effect.
        :return:
        """
        for module in self.__config.modules:
            install_requirements(module)

    def cache_models(self, *, cache_dir: str = None):
        """
        Cache all selected models
        :param cache_dir:
        :return:
        """
        for models in self.__config.models.values():
            for model_config in models:
                model = build_model(model_config, cache_dir=cache_dir)
                model.cache()


def test():
    pass


if __name__ == '__main__':
    test()
