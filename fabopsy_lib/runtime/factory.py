# -*- coding: utf-8 -*-

from typing import IO, Iterable

from fabopsy_lib import schema
from fabopsy_lib.utils.pencilbox import unique_list
from fabopsy_lib.runtime.module import (
    LoadedModule, load_builtin_modules,
    load_dir_modules, load_local_module, load_url_module
)

__all__ = [
    'Factory',
]

class Factory(object):
    def __init__(self):
        self.__modules: list[LoadedModule] = []

        self.__module_uid_map: dict[schema.Uid, schema.Module] = {}
        self.__package_uid_map: dict[schema.Uid, schema.Package] = {}
        self.__model_uid_map: dict[schema.Uid, schema.Model] = {}
        self.__package_uid_map_module: dict[schema.Uid, schema.Module] = {}
        self.__model_uid_map_package: dict[schema.Uid, schema.Package] = {}
        self.__parameter_map: dict[tuple[schema.Uid, str], schema.Parameter] = {}

        self.__attribute_providers: dict[str, list[schema.Package]] = {}

    def append(self, module: LoadedModule):
        # TODO: check module has already exists or not
        self.__modules.append(module)

        self.__module_uid_map[module.module.module.uid] = module.module
        for package in module.module.packages:
            self.__package_uid_map[package.uid] = package
            self.__package_uid_map_module[package.uid] = module.module
            for model in package.models:
                self.__model_uid_map[model.uid] = model
                self.__model_uid_map_package[model.uid] = package
            for attr in package.provides:
                providers = self.__attribute_providers.get(attr, None)
                if providers is not None:
                    providers.append(package)
                else:
                    self.__attribute_providers[attr] = [package]
            for param in package.parameters:
                self.__parameter_map[(package.uid, param.name)] = param

    def extend(self, modules: Iterable[LoadedModule]):
        for module in modules:
            self.append(module)

    def load_builtin_modules(self):
        self.extend(load_builtin_modules())

    def load_dir_modules(self, root: str):
        self.extend(load_dir_modules(root))

    def load_local_module(self, f: str | bytes | IO[str] | IO[bytes], extension: str = None):
        module = load_local_module(f, extension)
        if module is not None:
            self.append(module)

    def load_url_module(self, url: str):
        module = load_url_module(url)
        if module is not None:
            self.append(module)

    @property
    def modules(self) -> list[LoadedModule]:
        return self.__modules

    @property
    def packages(self) -> list[schema.Package]:
        return [p for m in self.__modules for p in m.module.packages]

    @property
    def attributes(self) -> list[str]:
        packages = self.packages
        return unique_list([attr for p in packages for attr in p.provides])

    def query_module(self, uid: schema.Uid) -> schema.Module | None:
        return self.__module_uid_map.get(uid, None)

    def query_package(self, uid: schema.Uid) -> schema.Package | None:
        return self.__package_uid_map.get(uid, None)

    def query_model(self, uid: schema.Uid) -> schema.Model | None:
        return self.__model_uid_map.get(uid, None)

    def query_module_of_package(self, uid: schema.Uid) -> schema.Module | None:
        return self.__package_uid_map_module.get(uid, None)

    def query_package_of_model(self, uid: schema.Uid) -> schema.Package | None:
        return self.__model_uid_map_package.get(uid, None)

    def query_attribute_providers(self, attr: str) -> list[schema.Package]:
        return self.__attribute_providers.get(attr, [])

    def query_parameter(self, uid: schema.Uid, name: str) -> schema.Parameter | None:
        return self.__parameter_map.get((uid, name), None)

def test():
    pass


if __name__ == '__main__':
    test()
