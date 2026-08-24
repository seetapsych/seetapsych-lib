# -*- coding: utf-8 -*-

from platformdirs import PlatformDirs


appdirs = PlatformDirs(appname='Fabopsy', appauthor='Levalup')


def test():
    print(appdirs.user_cache_dir)
    print(appdirs.user_data_dir)


if __name__ == '__main__':
    test()
