# -*- coding: utf-8 -*-

import os
import sys


from streamlit.web import cli as stcli


def main():
    app_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app.py')

    sys.argv = ['streamlit', 'run', app_path, '--', *sys.argv[1:]]
    stcli.main()


if __name__ == '__main__':
    main()
