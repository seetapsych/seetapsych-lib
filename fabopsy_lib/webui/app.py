# -*- coding: utf-8 -*-

import json
import uuid
import argparse
import tempfile
import os.path
from dataclasses import dataclass, fields, field, Field
from typing import cast, Any, Protocol, TypeVar

import numpy
import cv2
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from fabopsy_lib.runtime import Factory, Pipeline, Runner
from fabopsy_lib.runtime.pipeline import UnsatisfactionConfig
from fabopsy_lib.runtime.export import list2csv
from fabopsy_lib import schema
from fabopsy_lib.utils.logger import set_level as set_logger_level
from fabopsy_lib.utils.markdown import schema2markdown

try:
    from fabopsy_attributes.schema import schema as attribute_schema
    has_schema_attributes = True
except ModuleNotFoundError:
    # sys.stderr.write("[WARNING] Failed to import fabopsy_attributes. Install that to enable attribute schema viewer.\n")
    from pydantic import BaseModel
    attribute_schema: dict[str, type[BaseModel]] = {}
    has_schema_attributes = False


ICON_ERROR = "\N{CROSS MARK}"
ICON_PAGE = "\N{FIRE}"


@dataclass
class SessionState(object):
    log: str | None = None

    page: str = 'start'

    cache_dir: str = ''
    upload_dir: str = ''

    factory: Factory | None = None
    pipeline: Pipeline | None = None
    runner: Runner | None = None
    runner_signature: str = ''

    event: str = ''
    error: BaseException | str | None = None

    search_package: str = ''
    search_model: str = ''
    package_uid: str = ''
    satisfied: bool = False
    unsatisfaction: UnsatisfactionConfig | None = None

    file: Any = None
    reports: list[dict[str, Any]] = field(default_factory=lambda: [])
    export_json: str = ''
    export_csv: str = ''

    parameter_search: str = ''
    parameter_show_description: bool = True

    batch_grouped: list[dict[str, Any]] = field(default_factory=lambda: [])
    batch_rows: list[dict[str, Any]] = field(default_factory=lambda: [])


def init_session_state(init: SessionState) -> SessionState:
    for attr in fields(init):
        attr: Field
        if attr.name not in st.session_state:
            setattr(st.session_state, attr.name, getattr(init, attr.name))

    return st.session_state


session_state = init_session_state(SessionState())


def fuzzy_match_package(package: schema.Package, pattern: str):
    pattern = pattern.lower()

    def match(s: str | None):
        return pattern in s.lower() if s else False

    return (
        any(match(s) for s in (package.name, package.description)) or 
        any(match(s) for s in package.keywords) or 
        any(match(s) for s in package.provides))


def fuzzy_match_model(model: schema.Model, pattern: str):
    pattern = pattern.lower()

    def match(s: str | None):
        return pattern in s.lower() if s else False

    return (
        any(match(s) for s in (model.name, model.description)) or 
        any(match(s) for s in model.keywords))


@st.dialog(title='Attribute Description')
def show_attribute_description(attr: str):
    if not has_schema_attributes:
        st.warning('Failed to import fabopsy_attributes to show schema.')
        return

    model = attribute_schema.get(attr, None)
    if model is None:
        st.warning('No schema found!')
        return
    st.markdown(schema2markdown(model.model_json_schema()), unsafe_allow_html=True)


def page_start():
    st.title('Start')

    column_pipeline, column_packages = st.columns([1, 1])

    factory = session_state.factory
    pipeline = session_state.pipeline
    event = session_state.event

    with column_packages:
        st.subheader('Packages')

        search_package = st.text_input(
            'Search', value=session_state.search_package, key="search_package",
            label_visibility='collapsed')
        if search_package != session_state.search_package:
            session_state.search_package = search_package
            st.rerun()

        packages = [p for p in factory.packages if fuzzy_match_package(p, search_package or '')]

        for package in packages:
            with st.container(border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{package.name}** `v{package.version}`")
                    for i, attr in enumerate(package.provides):
                        if st.button(attr, type='tertiary', key=f'click:{package.uid}:{i}-{attr}'):
                            show_attribute_description(attr)
                with st.container(horizontal=True):
                    for keyword in package.keywords:
                        st.badge(keyword)
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
                render_package_header(package)
                render_package_models(pipeline, package)

        problem = pipeline.problem()
        has_attribute_problem = bool(problem and (problem.missing_module_packages or problem.attributes))

        if has_attribute_problem:
            # list errors
            with st.container():
                for p in problem.missing_module_packages:
                    st.error(f'Missing module for "{p.name}"', icon=ICON_ERROR)
                # for p in problem.missing_model_packages:
                #     st.error(f'Missing model for "{p.name}" where usage = {p.usage_models}', icon=ICON_ERROR)
                for p in problem.attributes:
                    st.error(f'Missing required attribute "{p}"', icon=ICON_ERROR)

        busy = st.empty()

        with st.container(horizontal=True):
            no_solve = bool(event) or problem is None
            if st.button('Solve', disabled=no_solve):
                session_state.event = 'solve'
                st.rerun()

            no_next = bool(event) or has_attribute_problem or not pipeline_packages
            if st.button('Next', disabled=no_next):
                session_state.package_uid = None
                session_state.page = 'model'
                session_state.error = None
                st.rerun()

    if event == 'solve':
        with busy.spinner('Solving...', show_time=True):
            pipeline.solve(ignore_models=True)
            session_state.event = ''
            st.rerun()


def page_model():
    st.title('Model')

    column_pipeline, column_models = st.columns([1, 1])

    factory = session_state.factory
    pipeline = session_state.pipeline
    event = session_state.event
    edit_package_uid = session_state.package_uid

    edit_package: schema.Package | None = None

    problem = pipeline.problem()
    missing_model_package_ids = {} if not problem else set([p.uid for p in problem.missing_model_packages])

    with column_pipeline:
        st.subheader('Pipeline')

        for package in pipeline.packages:
            if edit_package_uid and package.uid == edit_package_uid:
                edit_package = package

            has_missing_model = package.uid in missing_model_package_ids

            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package, deletable=True)
                if st.button('Edit', key=f'edit-model:{package.uid}',
                             type='primary' if has_missing_model else 'secondary'):
                    session_state.package_uid = package.uid
                    st.rerun()

        if problem:
            # list errors
            with st.container():
                for p in problem.missing_module_packages:
                    st.error(f'Missing module for "{p.name}"', icon=ICON_ERROR)
                for p in problem.missing_model_packages:
                    st.error(f'Missing model for "{p.name}" where usage = {p.usage_models}', icon=ICON_ERROR)
                for p in problem.attributes:
                    st.error(f'Missing required attribute "{p}"', icon=ICON_ERROR)

        busy = st.empty()

        with st.container(horizontal=True):
            no_solve = bool(event) or problem is None
            if st.button('Solve', disabled=no_solve):
                session_state.event = 'solve'
                st.rerun()

            if st.button('Prev'):
                session_state.page = 'start'
                session_state.error = None
                st.rerun()

            no_next = bool(event) or problem is not None
            if st.button('Next', disabled=no_next):
                session_state.package_uid = None
                session_state.page = 'setting'
                session_state.error = None
                st.rerun()

    with column_models:
        st.subheader('Models')

        if edit_package is None:
            st.info('Click "Edit" to edit package models.')
        else:
            st.markdown(f'**{edit_package.name}**')

        search_model = st.text_input(
            'Search', value=session_state.search_model, key="search_model",
            label_visibility='collapsed')
        if search_model != session_state.search_model:
            session_state.search_model = search_model
            st.rerun()

        models = edit_package.models if edit_package else []
        models = [m for m in models if fuzzy_match_model(m, search_model or '')]

        for model in models:
            with st.container(border=True):
                with st.container(horizontal=True):
                    if model.recommended:
                        st.markdown(
                            '<span style="color: red">*</span>'
                            f"**{model.name}** `v{model.version}`",
                            unsafe_allow_html=True)
                    else:
                        st.markdown(f"**{model.name}** `v{model.version}`")
                with st.container(horizontal=True):
                    for keyword in model.keywords:
                        st.badge(keyword)
                st.write(model.description)
                with st.container(horizontal=True):
                    if st.button('Add', key=f'add-model:{model.uid}'):
                        pipeline.add_model(edit_package.uid, model.uid)
                        st.rerun()

    if event == 'solve':
        with busy.spinner('Solving...', show_time=True):
            pipeline.solve()
            session_state.event = ''
            st.rerun()


def parameter_integer(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.number_input(key=key, label=parameter_display_name(param), value=param.value, step=1)
    if value != param.value:
        update = {param.name: int(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_number(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.number_input(key=key, label=parameter_display_name(param), value=param.value, format='%f', step=1e-9)
    if value != param.value:
        update = {param.name: float(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_string(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.text_input(key=key, label=parameter_display_name(param), value=param.value)
    if value != param.value:
        update = {param.name: str(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_selection(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    try:
        index = param.selection.index(param.value)
    except Exception:
        index = 0 if param.selection else 0
    value = st.selectbox(
        key=key,
        label=parameter_display_name(param),
        options=param.selection,
        index=index if param.selection else 0,
    )
    if value is not None and value != param.value:
        update = {param.name: str(value)}
        pipeline.set_parameters(package_uid, update)

def parameter_boolean(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.toggle(key=key, label=parameter_display_name(param), value=param.value)
    if value != param.value:
        update = {param.name: bool(value)}
        pipeline.set_parameters(package_uid, update)


T = TypeVar('T')


def format_array(t: type[T], value: list[T]) -> str:
    return ', '.join(map(str, value))


def parse_array(t: type[T], value: str) -> list[T] | None:
    try:
        return [t(v.strip()) for v in value.split(',') if v]
    except Exception:
        return None


def parameter_integer_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_array(int, param.value)
    value = st.text_input(key=key, label=parameter_display_name(param), value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_array(int, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {parameter_display_name(param)}: {value}')


def parameter_number_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_array(float, param.value)
    value = st.text_input(key=key, label=parameter_display_name(param), value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_array(float, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {parameter_display_name(param)}: {value}')


def parameter_string_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    format_value = format_array(str, param.value)
    value = st.text_input(key=key, label=parameter_display_name(param), value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_array(str, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {parameter_display_name(param)}: {value}')


def parameter_selection_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ':' + param.name
    value = st.multiselect(key=key, label=parameter_display_name(param), options=param.selection, default=param.value)
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
    value = st.text_area(key=key, label=parameter_display_name(param), value=format_value)
    if value is not None and value != format_value:
        parse_value = parse_object(value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f'Invalid {parameter_display_name(param)}: {value}')

def parameter_display_name(param: schema.Parameter) -> str:
    text = getattr(param, 'text', '') or ''
    return text if text else param.name


def component_parameter(package_uid: str, param: schema.Parameter, *, show_description: bool = True):
    pipeline = session_state.pipeline
    parameter_generators = {
        schema.ParameterType.Integer: parameter_integer,
        schema.ParameterType.Number: parameter_number,
        schema.ParameterType.String: parameter_string,
        schema.ParameterType.Selection: parameter_selection,
        schema.ParameterType.Boolean: parameter_boolean,
        schema.ParameterType.IntegerArray: parameter_integer_array,
        schema.ParameterType.NumberArray: parameter_number_array,
        schema.ParameterType.StringArray: parameter_string_array,
        schema.ParameterType.SelectionArray: parameter_selection_array,
        schema.ParameterType.Object: parameter_object,
    }
    with st.container():
        if show_description and param.description:
            st.markdown(f'> {param.description}')
        generator = parameter_generators.get(param.type, None)
        if generator is not None:
            generator(pipeline, package_uid, param)
        else:
            st.markdown(f'**{parameter_display_name(param)}**: {param.value}')

def render_package_header(package: schema.Package):
    with st.container(horizontal=True):
        st.markdown(f"**{package.name}** `v{package.version}`")
        for attr in package.provides:
            st.badge(attr)


def render_package_models(pipeline: Pipeline, package: schema.Package, deletable: bool = False):
    models = pipeline.get_models(package.uid)
    for model in models:
        with st.container(horizontal=True):
            if model.usage:
                st.markdown(f"- **{model.usage}** {model.name} `v{model.version}`")
            else:
                st.markdown(f"- {model.name} `v{model.version}`")
            if deletable:
                if st.button('Delete', key=f'delete-model:{package.uid}:{model.uid}', type='primary'):
                    pipeline.remove_model(package.uid, model.uid)
                    st.rerun()


def page_setting():
    st.title('Setting')

    column_pipeline, column_parameters = st.columns([1, 1])

    pipeline = session_state.pipeline
    edit_package_uid = session_state.package_uid

    edit_package: schema.Package | None = None

    with column_pipeline:
        st.subheader('Pipeline')

        for package in pipeline.packages:
            if edit_package_uid and package.uid == edit_package_uid:
                edit_package = package

            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package)
                with st.container(horizontal=True):
                    if st.button('Edit', key=f'edit:{package.uid}'):
                        session_state.package_uid = package.uid
                        st.rerun()

        with st.container(horizontal=True):
            if st.button('Prev'):
                session_state.page = 'model'
                session_state.error = None
                st.rerun()

            if st.button('Next'):
                session_state.page = 'install'
                session_state.event = 'satisfy'
                session_state.error = None
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
                    parameters.append(p.model_copy(deep=True))
                else:
                    parameters.append(p.model_copy(deep=True, update={'value': config_parameter.value}))

            with st.container():
                search_value = st.text_input(
                    'Search parameters',
                    value=session_state.parameter_search,
                    key='parameter_search',
                    label_visibility='collapsed',
                    placeholder='Search parameters...',
                )
                show_description = st.checkbox(
                    'Show descriptions',
                    value=session_state.parameter_show_description,
                    key='parameter_show_description',
                )

                if search_value:
                    s = search_value.strip().lower()
                    parameters = [
                        p for p in parameters
                        if (p.name and s in p.name.lower()) or (p.description and s in p.description.lower())
                    ]

                if not parameters:
                    st.info('No parameters matched.')
                else:
                    parameters = sorted(parameters, key=lambda p: (parameter_display_name(p) or '').lower())
                    for p in parameters:
                        component_parameter(edit_package.uid, p, show_description=show_description)


def page_install():
    st.title('Installation')

    column_pipeline, column_satisfaction = st.columns([1, 1])

    pipeline = session_state.pipeline
    cache_dir = session_state.cache_dir
    satisfied = session_state.satisfied
    unsatisfaction = session_state.unsatisfaction
    error = session_state.error
    event = session_state.event

    with column_pipeline:
        st.subheader('Pipeline')

        for package in pipeline.packages:
            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package)

        with st.container(horizontal=True):
            if st.button('Prev', disabled=bool(event)):
                session_state.page = 'setting'
                session_state.error = None
                st.rerun()

            if st.button('Next', disabled=not satisfied):
                session_state.page = 'run'
                session_state.event = 'build'
                session_state.error = None
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
                st.error(f'Module **{m.name}** `v{m.version}` require:\n\n{requirements}', icon=ICON_ERROR)
            for m in unsatisfaction.entries:
                prefix = m.package or ''
                suffix = '.' + m.method if m.package else m.method
                st.error(f'Entry `{prefix}{suffix}` is not callable.', icon=ICON_ERROR)
            for m in unsatisfaction.models:
                st.error(f'Missing cache **{m.name or "<anonymous>"}** `v{m.version}`.', icon=ICON_ERROR)

        busy = st.empty()

        with st.container(horizontal=True):
            no_install = bool(event) or unsatisfaction is None or not unsatisfaction.modules
            if st.button('Install', disabled=no_install):
                session_state.event = 'install'
                st.rerun()

            no_download = bool(event) or unsatisfaction is None or not unsatisfaction.models
            if st.button('Download', disabled=no_download):
                session_state.event = 'download'
                st.rerun()

    if error is not None:
        if isinstance(error, BaseException):
            st.exception(error)
        else:
            st.error(str(error))

    if event == 'satisfy':
        with busy.spinner('Checking...', show_time=True):
            satisfied, unsatisfaction = pipeline.satisfied(cache_dir=cache_dir)
            session_state.satisfied = satisfied
            session_state.unsatisfaction = unsatisfaction
            session_state.event = ''
            st.rerun()

    if event == 'install':
        with busy.spinner('Install...', show_time=True):
            try:
                pipeline.install_requirements()
                session_state.error = None
            except Exception as e:
                session_state.error = e
            finally:
                session_state.event = 'satisfy'
                st.rerun()

    if event == 'download':
        with busy.spinner('Download...', show_time=True):
            try:
                pipeline.cache_models(cache_dir=cache_dir)
                session_state.error = None
            except Exception as e:
                session_state.error = e
            finally:
                session_state.event = 'satisfy'
                st.rerun()


def run_image(runner: Runner, file: UploadedFile):
    reports = session_state.reports

    if not reports:
        with st.spinner('Open image...', show_time=True):
            image_bytes = read_uploaded_file_bytes(file)
            image = cv2.imdecode(numpy.frombuffer(image_bytes, numpy.uint8), cv2.IMREAD_COLOR)

        with st.spinner('Running...', show_time=True):
            try:
                report = runner.run({
                    'default': image,
                })
            except Exception as e:
                session_state.error = e
                st.rerun()

        session_state.reports = [report]
    else:
        report = reports[0]

    def to_json() -> str:
        content = session_state.export_json
        if not content:
            content = json.dumps(report, ensure_ascii=False, indent=2)
            session_state.export_json = content
        return content

    def to_csv() -> str:
        content = session_state.export_csv
        if not content:
            content = list2csv([report])
            session_state.export_csv = content
        return content

    with st.container(horizontal=True):
        st.download_button(
            label='Download JSON',
            data=to_json(),
            file_name='report.json',
            mime='text/json',
            key='download_json',
        )

        st.download_button(
            label='Download CSV',
            data=to_csv(),
            file_name='report.csv',
            mime='text/csv',
            key='download_csv',
        )

    st.code(json.dumps(report, indent=2), language='json')


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
        try:
            file.seek(0)
        except Exception:
            pass
        with open(path, "wb") as f:
            while buf := file.read(1024 * 1024):
                f.write(buf)
        try:
            file.seek(0)
        except Exception:
            pass

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
    upload_dir = session_state.upload_dir
    reports = session_state.reports

    if not reports:
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
                        }, timestamp=capture.get(cv2.CAP_PROP_POS_MSEC) / 1000)
                        reports.append(report)
                    except Exception as e:
                        session_state.error = e
                        st.rerun()
                    ratio = (i / n) if n > 0 else 0.0
                    progress.progress(ratio, text=f'[{i}/{n}]')

        session_state.reports = reports

    def to_json() -> str:
        content = session_state.export_json
        if not content:
            content = json.dumps(reports, ensure_ascii=False, indent=2)
            session_state.export_json = content
        return content

    def to_csv() -> str:
        content = session_state.export_csv
        if not content:
            content = list2csv(reports)
            session_state.export_csv = content
        return content

    with st.container(horizontal=True):
        st.download_button(
            label='Download JSON',
            data=to_json(),
            file_name='report.json',
            mime='text/json',
            key='download_json',
        )

        st.download_button(
            label='Download CSV',
            data=to_csv(),
            file_name='report.csv',
            mime='text/csv',
            key='download_csv',
        )

    st.code(json.dumps(reports, indent=2), language='json')

def read_uploaded_file_bytes(file: UploadedFile) -> bytes:
    if hasattr(file, 'getvalue'):
        return file.getvalue()
    try:
        file.seek(0)
    except Exception:
        pass
    data = file.read()
    try:
        file.seek(0)
    except Exception:
        pass
    return data

def pipeline_signature(pipeline: Pipeline, *, cache_dir: str) -> str:
    payload = {
        'cache_dir': cache_dir or '',
        'pipeline': pipeline.config.model_dump(mode='json'),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def make_report_row(
        report: dict[str, Any],
        *,
        file_name: str,
        file_type: str,
        kind: str,
        item_index: int,
        frame_index: int | None = None,
        timestamp: float | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        'file_name': file_name,
        'file_type': file_type,
        'kind': kind,
        'item_index': item_index,
    }
    if frame_index is not None:
        meta['frame_index'] = frame_index
    if timestamp is not None:
        meta['timestamp'] = timestamp
    return {'__meta__': meta, **(report or {})}

def process_image_file(runner: Runner, file: UploadedFile) -> dict[str, Any]:
    image_bytes = read_uploaded_file_bytes(file)
    image = cv2.imdecode(numpy.frombuffer(image_bytes, numpy.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f'Invalid image: {file.name}')
    return runner.run({'default': image})


def page_run():
    st.title('Run')

    runner = session_state.runner
    pipeline = session_state.pipeline
    cache_dir = session_state.cache_dir
    upload_dir = session_state.upload_dir
    error = session_state.error

    event = session_state.event
    busy = st.empty()

    desired_signature = pipeline_signature(pipeline, cache_dir=cache_dir)
    if (
            runner is not None and
            session_state.runner_signature and
            session_state.runner_signature != desired_signature and
            event != 'build'
    ):
        try:
            runner.dispose()
        except Exception:
            pass
        session_state.runner = None
        session_state.runner_signature = ''
        session_state.reports = []
        session_state.batch_grouped = []
        session_state.batch_rows = []
        session_state.export_json = ''
        session_state.export_csv = ''
        session_state.error = None
        session_state.event = 'build'
        st.rerun()

    if runner is not None:
        st.success('Ready to run.')

        files = st.file_uploader(
            'Select image/video(s)',
            key='upload_input',
            type=['jpg', 'png', 'bmp', 'mp4', 'avi', 'wmv'],
            accept_multiple_files=True,
        )
        signature = '|'.join([getattr(f, 'file_id', '') or f.name for f in files]) if files else ''
        if signature and session_state.file != signature:
            session_state.reports = []
            session_state.batch_grouped = []
            session_state.batch_rows = []
            session_state.export_json = ''
            session_state.export_csv = ''
            session_state.error = None
            session_state.file = signature

        if files:
            if len(files) == 1:
                file = files[0]
                if file.type.startswith('image/'):
                    st.image(file)
                    run_image(runner, file)
                elif file.type.startswith('video/'):
                    st.video(file)
                    run_video(runner, file)
            else:
                st.write(f'{len(files)} files selected.')
                if not session_state.batch_grouped:
                    if st.button('Run batch', disabled=bool(event)):
                        session_state.event = 'run_batch'
                        st.rerun()
                else:
                    st.success(f'Batch finished. Files: {len(session_state.batch_grouped)}, Rows: {len(session_state.batch_rows)}')

                    def to_json_grouped() -> str:
                        content = session_state.export_json
                        if not content:
                            content = json.dumps(session_state.batch_grouped, ensure_ascii=False, indent=2)
                            session_state.export_json = content
                        return content

                    def to_csv_rows() -> str:
                        content = session_state.export_csv
                        if not content:
                            content = list2csv(session_state.batch_rows)
                            session_state.export_csv = content
                        return content

                    with st.container(horizontal=True):
                        st.download_button(
                            label='Download JSON',
                            data=to_json_grouped(),
                            file_name='reports.json',
                            mime='text/json',
                            key='download_json_batch',
                        )
                        st.download_button(
                            label='Download CSV',
                            data=to_csv_rows(),
                            file_name='reports.csv',
                            mime='text/csv',
                            key='download_csv_batch',
                        )

                    for item in session_state.batch_grouped:
                        file_name = item.get('file_name', '<unknown>')
                        kind = item.get('kind', '')
                        if 'error' in item:
                            title = f'{file_name} ({kind})'
                        else:
                            count = item.get('count', 1)
                            title = f'{file_name} ({kind}, {count})'
                        with st.expander(title, expanded=False):
                            if 'error' in item:
                                st.error(str(item['error']))
                            elif kind == 'image':
                                st.json(item.get('report', {}))
                            elif kind == 'video':
                                reports = item.get('reports', [])
                                if reports:
                                    st.json(reports[0])
                                else:
                                    st.info('No frames processed.')

        if event == 'run_batch':
            if not files or len(files) <= 1:
                session_state.event = ''
                st.rerun()

            with busy.spinner('Running batch...', show_time=True):
                overall = st.progress(0, text='Preparing...')
                grouped: list[dict[str, Any]] = []
                rows: list[dict[str, Any]] = []

                total = len(files)
                for item_index, f in enumerate(files):
                    overall.progress(item_index / total, text=f'[{item_index + 1}/{total}] {f.name}')
                    try:
                        if f.type.startswith('image/'):
                            report = process_image_file(runner, f)
                            grouped.append({
                                'file_name': f.name,
                                'file_type': f.type,
                                'kind': 'image',
                                'count': 1,
                                'report': report,
                            })
                            rows.append(make_report_row(
                                report,
                                file_name=f.name,
                                file_type=f.type,
                                kind='image',
                                item_index=item_index,
                            ))
                        elif f.type.startswith('video/'):
                            progress_slot = st.empty()
                            progress = progress_slot.progress(0, text='[0/?]')
                            with CacheFile(f, temp_dir=upload_dir) as temp:
                                temp.save()
                                with ReleaseCapture(temp.path) as capture:
                                    if not capture.isOpened():
                                        raise RuntimeError(f'Unable to open video: {f.name}')

                                    n = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                                    i = 0
                                    video_reports: list[dict[str, Any]] = []
                                    while capture.isOpened():
                                        ok = capture.grab()
                                        if not ok:
                                            break
                                        ok, image = capture.retrieve()
                                        if not ok:
                                            break
                                        image = cast(numpy.ndarray, image)
                                        i += 1
                                        timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                                        report = runner.run({'default': image}, timestamp=timestamp)
                                        video_reports.append(report)
                                        ratio = (i / n) if n > 0 else 0.0
                                        progress.progress(ratio, text=f'[{i}/{n}]')
                            progress_slot.empty()

                            grouped.append({
                                'file_name': f.name,
                                'file_type': f.type,
                                'kind': 'video',
                                'count': len(video_reports),
                                'reports': video_reports,
                            })
                            for frame_index, report in enumerate(video_reports):
                                rows.append(make_report_row(
                                    report,
                                    file_name=f.name,
                                    file_type=f.type,
                                    kind='video',
                                    item_index=item_index,
                                    frame_index=frame_index,
                                ))
                        else:
                            grouped.append({
                                'file_name': f.name,
                                'file_type': f.type,
                                'kind': 'unknown',
                                'error': f'Unsupported file type: {f.type}',
                            })
                    except Exception as e:
                        grouped.append({
                            'file_name': f.name,
                            'file_type': f.type,
                            'kind': 'error',
                            'error': str(e),
                        })

                overall.progress(1.0, text='Done')
                session_state.batch_grouped = grouped
                session_state.batch_rows = rows
                session_state.event = ''
                st.rerun()

    if event == 'build':
        with busy.spinner('Building...', show_time=True):
            try:
                if session_state.runner is not None and session_state.runner_signature == desired_signature:
                    session_state.error = None
                else:
                    if session_state.runner is not None:
                        try:
                            session_state.runner.dispose()
                        except Exception:
                            pass
                    session_state.runner = Runner(pipeline, device=None, cache_dir=cache_dir)
                    session_state.runner_signature = desired_signature
                    session_state.error = None
            except Exception as e:
                session_state.error = e
            finally:
                session_state.event = ''
                st.rerun()

    if error is not None:
        if isinstance(error, BaseException):
            st.exception(error)
        else:
            st.error(str(error))


@st.cache_resource(show_spinner=True)
def load_factory(
        dirs: list[str] = None, files: list[str] = None, urls: list[str] = None,
        disable_builtin: bool = False, disable_default: bool = False,
) -> Factory:
    dirs = dirs or []
    files = files or []
    urls = urls or []

    factory = Factory(
        disable_builtin=disable_builtin,
        disable_default=disable_default,
    )

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

.stButton button[kind="tertiary"] {
    min-height: unset;
    color: #409EFF;
}
"""


class Args(Protocol):
    dirs: list[str]
    files: list[str]
    urls: list[str]
    disable_builtin: bool = False
    disable_default: bool = False
    cache_dir: str = None
    upload_dir: str = None
    log: str = None


def initialize(args: Args):
    # set streamlit config
    st.set_page_config(
        layout="wide",
        page_title="Fabopsy WebUI",
        page_icon=ICON_PAGE,
    )
    st.markdown(f'<style>{global_style}</style>', unsafe_allow_html=True)

    if session_state.log is None and args.log:
        set_logger_level(args.log)
        session_state.log = args.log

    if session_state.factory is None:
        session_state.factory = load_factory(
            dirs=args.dirs,
            files=args.files,
            urls=args.urls,
            disable_builtin=args.disable_builtin,
            disable_default=args.disable_default,
        )
    if session_state.cache_dir is None and args.cache_dir:
        session_state.cache_dir = args.cache_dir
    if session_state.upload_dir is None:
        if args.upload_dir:
            upload_dir = os.path.abspath(args.upload_dir)
        else:
            upload_dir = os.path.join(tempfile.gettempdir(), 'fabopsy-webui', 'upload')
        session_state.upload_dir = upload_dir

    # initialize pipeline
    if session_state.pipeline is None:
        session_state.pipeline = Pipeline(session_state.factory)


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
        '--disable-default',
        action='store_true',
        help='Diable load default modules.'
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

    parser.add_argument(
        '--log',
        type=str,
        default=None,
        help='string or int, like DEBUG, INFO, WARNING or 10'
    )

    return cast(Args, cast(object, parser.parse_args()))


def main():
    initialize(parse_args())

    pages = {
        'start': page_start,
        'model': page_model,
        'setting': page_setting,
        'install': page_install,
        'run': page_run,
    }

    page = session_state.page
    if page not in pages:
        st.error(f'Can not find page: {page}')
        return

    pages[page]()


if __name__ == '__main__':
    main()
