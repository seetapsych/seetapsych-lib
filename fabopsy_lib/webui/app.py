# -*- coding: utf-8 -*-

import json
import uuid
import argparse
import tempfile
import os.path
from typing import cast, Any, Protocol, TypeVar

import numpy
import cv2
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from fabopsy_lib.runtime import Factory, Pipeline, Runner
from fabopsy_lib.runtime.pipeline import UnsatisfactionConfig
from fabopsy_lib import schema


def fuzzy_match_package(package: schema.Package, pattern: str):
    pattern = pattern.lower()

    def match(s: str | None):
        return pattern in s.lower() if s else False

    return any(match(s) for s in (package.name, package.description)) or any(match(s) for s in package.provides)


def page_start():
    st.title('Start')

    column_pipeline, column_packages = st.columns([1, 1])

    factory: Factory = st.session_state['factory']
    pipeline: Pipeline = st.session_state['pipeline']
    event = st.session_state['event']

    with column_packages:
        st.subheader('Packages')

        search_package = st.text_input(
            'Search', value=st.session_state['search_package'], key="search_package",
            label_visibility='collapsed')
        if search_package != st.session_state['search_package']:
            st.session_state['search_package'] = search_package
            st.rerun()

        packages = [p for p in factory.packages if fuzzy_match_package(p, search_package)]

        for package in packages:
            with st.container(border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{package.name}** `v{package.version}`")
                    for attr in package.provides:
                        st.badge(attr)
                st.write(package.description)
                with st.container(horizontal=True):
                    if st.button('Select', key=f'select:{package.uid}'):
                        pipeline.add_packages(package.uid)
                        st.rerun()

    with column_pipeline:
        st.subheader('Pipeline')

        pipeline_packages = pipeline.packages
        if not pipeline_packages:
            st.info('Select package on right side.')

        for package in pipeline_packages:
            with st.container(border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{package.name}** `v{package.version}`")
                    for attr in package.provides:
                        st.badge(attr)
                models = pipeline.get_models(package.uid)
                for model in models:
                    if model.usage:
                        st.markdown(f"- **{model.usage}** {model.name} `v{model.version}`")
                    else:
                        st.markdown(f"- {model.name}` v{model.version}`")

        problem = pipeline.problem()

        if problem:
            # list errors
            with st.container():
                for p in problem.missing_module_packages:
                    st.error(f'Missing module for "{p.name}"', icon='❌')
                for p in problem.missing_model_packages:
                    st.error(f'Missing model for "{p.name}" where usage = {p.usage_models}', icon='❌')
                for p in problem.attributes:
                    st.error(f'Missing required attribute "{p}"', icon='❌')

        busy = st.empty()

        with st.container(horizontal=True):
            no_solve = bool(event) or problem is None
            if st.button('Solve', disabled=no_solve):
                st.session_state['event'] = 'solve'
                st.rerun()

            no_next = bool(event) or problem is not None or not pipeline_packages
            if st.button('Next', disabled=no_next):
                st.session_state['page'] = 'setting'
                st.session_state['error'] = None
                st.rerun()

    if event == 'solve':
        with busy.spinner('Solving...', show_time=True):
            pipeline.solve()
            st.session_state['event'] = ''
            st.rerun()


def parameter_integer(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.number_input(key=key, label=param.name, value=param.value, step=1)
    if value != param.value:
        update = {param.name: int(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_number(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.number_input(key=key, label=param.name, value=param.value, format='%f', step=1e-9)
    if value != param.value:
        update = {param.name: float(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_string(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.text_input(key=key, label=param.name, value=param.value)
    if value != param.value:
        update = {param.name: str(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_selection(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    index: int | None = param.selection.index(param.value)
    if index < 0:
        index = None
    value = st.selectbox(key=key, label=param.name, options=param.selection, index=index)
    if value is not None and value != param.value:
        update = {param.name: str(value)}
        pipeline.set_parameters(package_uid, update)


T = TypeVar('T')
def format_array(t: type[T],  value: list[T]) -> str:
    return ', '.join(map(str, value))


def parse_array(t: type[T], value: str) -> list[T] | None:
    try:
        return [t(v.strip()) for v in value.split(',') if v]
    except Exception:
        return None


def parameter_integer_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_array(int, param.value)
    value = st.text_input(key=key, label=param.name, value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_array(int, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {param.name}: {value}')


def parameter_number_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_array(float, param.value)
    value = st.text_input(key=key, label=param.name, value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_array(float, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {param.name}: {value}')


def parameter_string_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_array(str, param.value)
    value = st.text_input(key=key, label=param.name, value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_array(str, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {param.name}: {value}')


def parameter_selection_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.multiselect(key=key, label=param.name, options=param.selection, default=param.value)
    if value is not None and value != param.value:
        update = {param.name: value}
        pipeline.set_parameters(package_uid, update)


def format_object(value: dict[str, Any]) -> str:
    value = value or {}
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return '{}'


def parse_object(value: str) -> dict[str, Any] | None:
    try:
        return json.loads(value)
    except Exception:
        return None


def parameter_object(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_object(param.value)
    value = st.text_area(key=key, label=param.name, value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_object(value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {param.name}: {value}')


def component_parameter(package_uid: str, param: schema.Parameter):
    pipeline: Pipeline = st.session_state['pipeline']
    parameter_generators = {
        schema.ParameterType.Integer: parameter_integer,
        schema.ParameterType.Number: parameter_number,
        schema.ParameterType.String: parameter_string,
        schema.ParameterType.Selection: parameter_selection,
        schema.ParameterType.IntegerArray: parameter_integer_array,
        schema.ParameterType.NumberArray: parameter_number_array,
        schema.ParameterType.StringArray: parameter_string_array,
        schema.ParameterType.SelectionArray: parameter_selection_array,
        schema.ParameterType.Object: parameter_object,
    }
    with st.container():
        st.markdown(f'> {param.description}')
        generator = parameter_generators.get(param.type, None)
        if generator is not None:
            generator(pipeline, package_uid, param)
        else:
            st.markdown(f'**{param.name}**: {param.value}')


def page_setting():
    st.title('Setting')

    column_pipeline, column_parameters = st.columns([1, 1])

    pipeline: Pipeline = st.session_state['pipeline']
    edit_package_uid = st.session_state['package_uid']

    edit_package: schema.Package | None = None

    with column_pipeline:
        st.subheader('Pipeline')

        for package in pipeline.packages:
            if edit_package_uid and package.uid == edit_package_uid:
                edit_package = package

            with st.container(border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{package.name}** `v{package.version}`")
                    for attr in package.provides:
                        st.badge(attr)
                models = pipeline.get_models(package.uid)
                for model in models:
                    if model.usage:
                        st.markdown(f"- **{model.usage}** {model.name} `v{model.version}`")
                    else:
                        st.markdown(f"- {model.name}` v{model.version}`")
                with st.container(horizontal=True):
                    if st.button('Edit', key=f'edit:{package.uid}'):
                        st.session_state['package_uid'] = package.uid
                        st.rerun()

        with st.container(horizontal=True):
            if st.button('Prev'):
                st.session_state['page'] = 'start'
                st.session_state['error'] = None
                st.rerun()

            if st.button('Next'):
                st.session_state['page'] = 'install'
                st.session_state['event'] = 'satisfy'
                st.session_state['error'] = None
                st.rerun()

    with column_parameters:
        st.subheader('Parameters')

        if edit_package is None:
            st.info('Click "Edit" to edit package parameters.')
        else:
            st.markdown(f'**{edit_package.name}**')

            parameters: list[schema.Parameter] = []
            for p in edit_package.parameters:
                config_parameter = pipeline.get_parameter(edit_package.uid, p.name)
                if config_parameter is None:
                    parameters.append(p.model_copy())
                else:
                    parameters.append(p.model_copy(update={'value': config_parameter.value}))

            # show parameters
            with st.container():
                for p in parameters:
                    component_parameter(edit_package.uid, p)


def page_install():
    st.title('Installation')

    column_pipeline, column_satisfaction = st.columns([1, 1])

    pipeline: Pipeline = st.session_state['pipeline']
    cache_dir: str = st.session_state['cache_dir']
    satisfied: bool = st.session_state['satisfied']
    unsatisfaction: UnsatisfactionConfig | None = st.session_state['unsatisfaction']
    error: Any | None = st.session_state['error']
    event = st.session_state['event']

    with column_pipeline:
        st.subheader('Pipeline')

        for package in pipeline.packages:
            with st.container(border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{package.name}** `v{package.version}`")
                    for attr in package.provides:
                        st.badge(attr)
                models = pipeline.get_models(package.uid)
                for model in models:
                    if model.usage:
                        st.markdown(f"- **{model.usage}** {model.name} `v{model.version}`")
                    else:
                        st.markdown(f"- {model.name}` v{model.version}`")

        with st.container(horizontal=True):
            if st.button('Prev', disabled=bool(event)):
                st.session_state['page'] = 'setting'
                st.session_state['error'] = None
                st.rerun()

            if st.button('Next', disabled=not satisfied):
                st.session_state['page'] = 'run'
                st.session_state['event'] = 'build'
                st.session_state['error'] = None
                st.rerun()

    with column_satisfaction:
        st.subheader('Satisfaction')

        if satisfied:
            st.success('This pipeline is ready for operation.')
        elif event == 'satisfy':
            st.warning('Satisfaction still checking...')
        elif not unsatisfaction:
            st.error('This pipeline does not meet the criteria but no report has been issued.')
        else:
            for m in unsatisfaction.modules:
                requirements = '\n'.join([f'- {r}' for r in m.requirements])
                st.error(f'Module **{m.name}** `v{m.version}` require:\n\n{requirements}', icon='❌')
            for m in unsatisfaction.entries:
                prefix = m.package or ''
                suffix = '.' + m.method if m.package else m.method
                st.error(f'Entry `{prefix}{suffix}` is not callable.', icon='❌')
            for m in unsatisfaction.models:
                st.error(f'Missing cache **{m.name or "<anonymous>"}** `v{m.version}`.', icon='❌')

        busy = st.empty()

        with st.container(horizontal=True):
            no_install = bool(event) or unsatisfaction is None or not unsatisfaction.modules
            if st.button('Install', disabled=no_install):
                st.session_state['event'] = 'install'
                st.rerun()

            no_download = bool(event) or unsatisfaction is None or not unsatisfaction.models
            if st.button('Download', disabled=no_download):
                st.session_state['event'] = 'download'
                st.rerun()

    if error is not None:
        if isinstance(error, BaseException):
            st.exception(error)
        else:
            st.error(str(error))

    if event == 'satisfy':
        with busy.spinner('Checking...', show_time=True):
            satisfied, unsatisfaction = pipeline.satisfied(cache_dir=cache_dir)
            st.session_state['satisfied'] = satisfied
            st.session_state['unsatisfaction'] = unsatisfaction
            st.session_state['event'] = ''
            st.rerun()

    if event == 'install':
        with busy.spinner('Install...', show_time=True):
            try:
                pipeline.install_requirements()
                st.session_state['error'] = None
            except Exception as e:
                st.session_state['error'] = e
            finally:
                st.session_state['event'] = 'satisfy'
                st.rerun()

    if event == 'download':
        with busy.spinner('Download...', show_time=True):
            try:
                pipeline.cache_models(cache_dir=cache_dir)
                st.session_state['error'] = None
            except Exception as e:
                st.session_state['error'] = e
            finally:
                st.session_state['event'] = 'satisfy'
                st.rerun()


def run_image(runner: Runner, file: UploadedFile):
    with st.spinner('Open image...', show_time=True):
        image_bytes = file.read()
        image = cv2.imdecode(numpy.frombuffer(image_bytes, numpy.uint8), cv2.IMREAD_COLOR)

    with st.spinner('Running...', show_time=True):
        try:
            report = runner.run({
                'default': image,
            })
            st.code(json.dumps(report, indent=2), language='json')
        except Exception as e:
            st.session_state['error'] = e


class CacheFile(object):
    def __init__(self, file: UploadedFile, auto_save: bool = False, *, temp_dir: str = None):
        if not temp_dir:
            temp_dir = tempfile.gettempdir()

        ext = os.path.splitext(file.name)[-1]
        path = os.path.join(temp_dir, str(uuid.uuid4()) + ext)

        self.__auto_save = auto_save
        self.__file = file
        self.__path = path

    @property
    def path(self) -> str:
        return self.__path

    def save(self):
        if os.path.exists(self.__path):
            return
        
        dirname = os.path.dirname(self.__path)
        if dirname:
            os.makedirs(dirname, exist_ok=True)

        path = self.__path
        file = self.__file
        with open(path, "wb") as f:
            while buf := file.read(1024 * 1024):
                f.write(buf)

    def __enter__(self):
        if self.__auto_save:
            self.save()
            
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if os.path.exists(self.__path):
            os.remove(self.__path)


class ReleaseCapture(object):
    def __init__(self, filename: str):
        self.__filename = filename
        self.__capture = cv2.VideoCapture()

    def __enter__(self) -> cv2.VideoCapture:
        self.__capture.open(self.__filename)
        return self.__capture

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.__capture.isOpened():
            self.__capture.release()


def run_video(runner: Runner, file: UploadedFile):
    upload_dir = st.session_state['upload_dir']

    with CacheFile(file, temp_dir=upload_dir) as temp:
        with st.spinner('Save video...', show_time=True):
            temp.save()

        with st.spinner('Process video...', show_time=True), ReleaseCapture(temp.path) as capture:
            progress = st.progress(0)
            n = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            i = 0

            reports = []
            while capture.isOpened():
                ok = capture.grab()
                if not ok:
                    break
                ok, image = capture.retrieve()
                if not ok:
                    break
                image: numpy.ndarray
                i += 1
                try:
                    report = runner.run({
                        'default': image,
                    })
                    reports.append(report)
                except Exception as e:
                    st.session_state['error'] = e
                progress.progress(i / n, text=f'[{i}/{n}]')

            st.code(json.dumps(reports, indent=2), language='json')


def page_run():
    st.title('Run')

    runner: Runner | None = st.session_state['runner']
    pipeline: Pipeline = st.session_state['pipeline']
    cache_dir: str = st.session_state['cache_dir']
    error: Any | None = st.session_state['error']

    event = st.session_state['event']
    busy = st.empty()

    if runner is not None:
        st.success('Ready to run.')

        file = st.file_uploader(
            'Select image/video',
            key=f'upload_input',
            type=['jpg', 'png', 'bmp', 'wav', 'mp4', 'avi', 'wmv'],
        )
        if file is not None:
            if file.type.startswith('image/'):
                st.image(file)
                run_image(runner, file)
            elif file.type.startswith('video/'):
                st.video(file)
                run_video(runner, file)

    if event == 'build':
        with busy.spinner('Building...', show_time=True):
            try:
                building_runner = Runner(pipeline, device=None, cache_dir=cache_dir)
                st.session_state['runner'] = building_runner
                st.session_state['error'] = None
            except Exception as e:
                st.session_state['error'] = e
            finally:
                st.session_state['event'] = ''
                st.rerun()

    if error is not None:
        if isinstance(error, BaseException):
            st.exception(error)
        else:
            st.error(str(error))


@st.cache_data(show_spinner=True)
def load_factory(
        dirs: list[str] = None, files: list[str] = None, urls: list[str] = None,
        disable_builtin: bool = False
) -> Factory:
    dirs = dirs or []
    files = files or []
    urls = urls or []

    factory = Factory()

    if not disable_builtin:
        factory.load_builtin_modules()

    for d in dirs:
        factory.load_dir_modules(d)

    for f in files:
        factory.load_local_module(f)

    for u in urls:
        factory.load_url_module(u)

    return factory


global_style = """
.stImage img {
    max-width: 50vh;
    max-height: 50vh;
}

.stVideo {
    max-width: 50vh;
    max-height: 50vh;
}

@media (orientation: portrait) {
  .stImage img {
    max-width: 50vw;
    max-height: 50vw;
  }
  .stVideo {
    max-width: 50vw;
    max-height: 50vw;
  }
}
"""


class Args(Protocol):
    dirs: list[str]
    files: list[str]
    urls: list[str]
    disable_builtin: bool = False
    cache_dir: str = None
    upload_dir: str = None


def initialize(args: Args):
    # set streamlit config
    st.set_page_config(
        layout="wide",
        page_title="Fabopsy WebUI",
        page_icon="🕯️"
    )
    st.markdown(f'<style>{global_style}</style>', unsafe_allow_html=True)

    # initialize factory and cache dir
    if 'factory' not in st.session_state:
        st.session_state['factory'] = load_factory(
            dirs=args.dirs,
            files=args.files,
            urls=args.urls,
            disable_builtin=args.disable_builtin,
        )
    if 'cache_dir' not in st.session_state:
        st.session_state['cache_dir'] = args.cache_dir
    if 'upload_dir' not in st.session_state:
        if args.upload_dir:
            upload_dir = os.path.abspath(args.upload_dir)
        else:
            upload_dir = os.path.join(tempfile.gettempdir(), 'fabopsy-webui', 'upload')
        st.session_state['upload_dir'] = upload_dir

    # initialize pipeline
    factory = st.session_state['factory']
    if 'pipeline' not in st.session_state:
        st.session_state['pipeline'] = Pipeline(factory)

    # initialize values
    if 'page' not in st.session_state:
        st.session_state['page'] = 'start'
    if 'search_package' not in st.session_state:
        st.session_state['search_package'] = ''
    if 'event' not in st.session_state:
        st.session_state['event'] = ''

    if 'package_uid' not in st.session_state:
        st.session_state['package_uid'] = ''

    if 'satisfied' not in st.session_state:
        st.session_state['satisfied'] = False
    if 'unsatisfaction' not in st.session_state:
        st.session_state['unsatisfaction'] = None
    if 'error' not in st.session_state:
        st.session_state['error'] = None

    if 'runner' not in st.session_state:
        st.session_state['runner'] = None


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description='Fabopsy WebUI via Streamlit.')

    parser.add_argument(
        '--dirs',
        nargs='+',
        type=str,
        default=[],
        help='Load modules from dirs in factory.'
    )

    parser.add_argument(
        '--files',
        nargs='+',
        type=str,
        default=[],
        help='Load modules from local files in factory.'
    )

    parser.add_argument(
        '--urls',
        nargs='+',
        type=str,
        default=[],
        help='Load modules from urls in factory.'
    )

    parser.add_argument(
        '--disable-builtin',
        action='store_true',
        help='Diable load builtin modules.'
    )

    parser.add_argument(
        '--cache-dir',
        type=str,
        default=None,
        help='Cache dir to store models.'
    )

    parser.add_argument(
        '--upload-dir',
        type=str,
        default=None,
        help='Directory to store uploaded files (default: upload subdirectory in current working directory)'
    )

    return cast(Args, cast(object, parser.parse_args()))


def main():
    initialize(parse_args())

    pages = {
        'start': page_start,
        'setting': page_setting,
        'install': page_install,
        'run': page_run,
    }

    page = st.session_state['page']
    if page not in pages:
        st.error(f'Can not find page: {page}')
        return

    pages[page]()


if __name__ == '__main__':
    main()
