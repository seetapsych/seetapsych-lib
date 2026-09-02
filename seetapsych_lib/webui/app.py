# -*- coding: utf-8 -*-

import argparse
import base64
import json
import os.path
import tempfile
import uuid
from dataclasses import Field, dataclass, field, fields
from functools import partial
from types import TracebackType
from typing import Any, Callable, Protocol, TypeVar, cast

import cv2
import numpy
import streamlit as st
from pydantic import BaseModel
from streamlit.runtime.uploaded_file_manager import UploadedFile

from seetapsych_lib import schema
from seetapsych_lib.runtime import Factory, Pipeline, Runner
from seetapsych_lib.runtime.export import list2csv
from seetapsych_lib.runtime.pipeline import PipelineConfig, UnsatisfactionConfig
from seetapsych_lib.utils.json import sanitize_json
from seetapsych_lib.utils.logger import set_level as set_logger_level
from seetapsych_lib.utils.markdown import schema2markdown

_attribute_schema: dict[str, type[BaseModel]]

try:
    from seetapsych_attributes.schema import schema as _attribute_schema_import

    _attribute_schema = _attribute_schema_import
    has_schema_attributes = True
except ModuleNotFoundError:
    _attribute_schema = {}
    has_schema_attributes = False

attribute_schema: dict[str, type[BaseModel]] = _attribute_schema


ICON_ERROR = "\N{CROSS MARK}"
ICON_PAGE = "\N{FIRE}"


@dataclass
class SessionState:
    log: str | None = None

    page: str = "start"

    cache_dir: str | None = None
    upload_dir: str | None = None

    factory: Factory | None = None
    pipeline: Pipeline | None = None
    runner: Runner | None = None
    runner_signature: str = ""

    event: str = ""
    error: BaseException | str | None = None

    search_package: str = ""
    search_model: str = ""
    package_uid: str | None = None
    satisfied: bool = False
    unsatisfaction: UnsatisfactionConfig | None = None

    file: Any = None
    reports: list[dict[str, Any]] = field(default_factory=lambda: [])
    export_json: str = ""
    export_csv: str = ""

    parameter_search: str = ""
    parameter_show_description: bool = True

    batch_grouped: list[dict[str, Any]] = field(default_factory=lambda: [])
    batch_rows: list[dict[str, Any]] = field(default_factory=lambda: [])


def init_session_state(init: SessionState) -> SessionState:
    for field_attr_untyped in fields(init):
        field_attr = cast(Field[Any], field_attr_untyped)
        if field_attr.name not in st.session_state:
            setattr(st.session_state, field_attr.name, getattr(init, field_attr.name))

    return cast(SessionState, st.session_state)


session_state = init_session_state(SessionState())


def fuzzy_match_package(package: schema.Package, pattern: str) -> bool:
    pattern = pattern.lower()

    def match(s: str | None) -> bool:
        return pattern in s.lower() if s else False

    return (
        any(match(s) for s in (package.name, package.description))
        or any(match(s) for s in package.keywords)
        or any(match(s) for s in package.provides)
    )


def fuzzy_match_model(model: schema.Model, pattern: str) -> bool:
    pattern = pattern.lower()

    def match(s: str | None) -> bool:
        return pattern in s.lower() if s else False

    return any(match(s) for s in (model.name, model.description)) or any(match(s) for s in model.keywords)


@st.dialog(title="Save Config")
def dialog_save_config():
    pipeline = session_state.pipeline
    if pipeline is None:
        st.error("No active pipeline to save.")
        return

    default_name = "New Config"
    filename_key = "save_config_filename"
    if filename_key not in st.session_state:
        st.session_state[filename_key] = default_name

    st.markdown('<span id="sp-save-cfg-marker" style="display:none"></span>', unsafe_allow_html=True)

    try:
        config_data = pipeline.config.model_dump(mode="json")
        config_json = json.dumps(config_data, ensure_ascii=False, indent=2)
    except Exception as e:
        st.error(f"Failed to serialize config: {e}")
        return

    # Wrap input + submit in a form so pressing Enter in the filename field
    # commits the new value before we read it (no blur/flush race).
    with st.form("save_config_form", clear_on_submit=False, border=False):
        filename_input_value = st.text_input(
            "File name",
            key=filename_key,
        )
        filename = filename_input_value if filename_input_value else default_name
        if not filename.endswith(".json"):
            filename += ".json"

        submitted = st.form_submit_button(
            "Download",
            type="primary",
        )

    if submitted:
        # Build a base64 data URL + trigger the download directly in the
        # browser via a transient <a download> node, then close the dialog.
        payload_bytes = config_json.encode("utf-8")
        payload_b64 = base64.b64encode(payload_bytes).decode("ascii")
        data_url = f"data:application/json;base64,{payload_b64}"
        filename_js_literal = json.dumps(filename)
        close_script = r"""
            <script>
            (function() {
                function findDialogRoot() {
                    var marker = document.getElementById("sp-save-cfg-marker");
                    if (!marker) return null;
                    if (marker.closest) {
                        var closest =
                            marker.closest('[data-testid="stDialog"]') ||
                            marker.closest(".stDialog");
                        if (closest) return closest;
                    }
                    var cur = marker;
                    for (var i = 0; i < 20 && cur; i++) {
                        if (
                            cur.nodeType === 1 &&
                            (cur.getAttribute("data-testid") === "stDialog" ||
                                (cur.classList && cur.classList.contains("stDialog")))
                        ) {
                            return cur;
                        }
                        cur = cur.parentElement;
                    }
                    return null;
                }

                function findCloseButton(root) {
                    if (!root) return null;
                    var btn = root.querySelector('button[aria-label="Close"]');
                    if (btn) return btn;
                    var list = root.querySelectorAll("button");
                    for (var i = 0; i < list.length; i++) {
                        var label = (
                            list[i].getAttribute("aria-label") || ""
                        ).toLowerCase();
                        if (label.indexOf("close") !== -1) return list[i];
                    }
                    return null;
                }
                try {
                    var a = document.createElement("a");
                    a.href = "DATA_URL_INJECT";
                    a.download = FILENAME_JS_INJECT;
                    a.rel = "noopener";
                    document.body.appendChild(a);
                    a.click();
                    setTimeout(function() {
                        try { document.body.removeChild(a); } catch (e) {}
                    }, 0);
                } catch (e) {}
                setTimeout(function() {
                    var close = findCloseButton(findDialogRoot());
                    if (close) try { close.click(); } catch (e) {}
                }, 300);
            })();
            </script>
            """.replace("DATA_URL_INJECT", data_url).replace("FILENAME_JS_INJECT", filename_js_literal)
        st.html(close_script, unsafe_allow_javascript=True)

    # Autofocus the filename input on dialog open and select its default text.
    st.html(
        r"""
        <script>
        (function() {
            var INTERVAL_MS = 100;
            var MAX_ATTEMPTS = 50;

            function findDialogRoot() {
                var marker = document.getElementById("sp-save-cfg-marker");
                if (!marker) return null;
                if (marker.closest) {
                    var closest =
                        marker.closest('[data-testid="stDialog"]') ||
                        marker.closest(".stDialog");
                    if (closest) return closest;
                }
                var cur = marker;
                for (var i = 0; i < 20 && cur; i++) {
                    if (
                        cur.nodeType === 1 &&
                        (cur.getAttribute("data-testid") === "stDialog" ||
                            (cur.classList && cur.classList.contains("stDialog")))
                    ) {
                        return cur;
                    }
                    cur = cur.parentElement;
                }
                return null;
            }

            function findTextInput(root) {
                var w = root.querySelector('input[data-testid="stTextInputField"]');
                if (w && w.type === "text") return w;
                w = root.querySelector('[data-testid="stTextInput"] input');
                if (w) return w;
                var list = root.querySelectorAll("input");
                for (var j = 0; j < list.length; j++) {
                    if (!list[j].type || list[j].type === "text") return list[j];
                }
                return null;
            }

            function findFormSubmitButton(root) {
                var w = root.querySelector(
                    '[data-testid="stFormSubmitButton"] button[data-testid="stBaseButton-primary"]'
                );
                if (w) return w;
                w = root.querySelector('[data-testid="stFormSubmitButton"] button');
                if (w) return w;
                var list = root.querySelectorAll("button");
                for (var j = 0; j < list.length; j++) {
                    var txt = (list[j].innerText || list[j].textContent || "").trim();
                    if (txt === "Download") return list[j];
                }
                return null;
            }

            var attempt = 0;
            var misses = 0;
            var intervalId = setInterval(function() {
                attempt += 1;
                var root = findDialogRoot();
                if (!root) {
                    misses += 1;
                    if (attempt >= MAX_ATTEMPTS || misses >= 5) {
                        clearInterval(intervalId);
                    }
                    return;
                }
                misses = 0;
                var input = findTextInput(root);
                var submitBtn = findFormSubmitButton(root);

                if (input && document.activeElement !== input) {
                    try { input.focus({ preventScroll: false }); } catch (e) {}
                    try {
                        input.select();
                        if (input.setSelectionRange) {
                            input.setSelectionRange(0, (input.value || "").length);
                        }
                    } catch (e) {}
                }

                var focused = !!(input && document.activeElement === input);
                var bound = !!submitBtn;
                if ((focused && bound) || attempt >= MAX_ATTEMPTS) {
                    clearInterval(intervalId);
                }
            }, INTERVAL_MS);
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def _apply_loaded_config(config_json_str: str) -> bool:
    factory = session_state.factory
    if factory is None:
        st.error("Factory is not initialized.")
        return False

    try:
        config_dict = json.loads(config_json_str)
        loaded_config = PipelineConfig.model_validate(config_dict)
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON: {e}")
        return False
    except Exception as e:
        st.error(f"Invalid PipelineConfig: {e}")
        return False

    new_pipeline = Pipeline(factory, config=loaded_config)
    session_state.pipeline = new_pipeline
    session_state.runner = None
    session_state.runner_signature = ""
    session_state.reports = []
    session_state.batch_grouped = []
    session_state.batch_rows = []
    session_state.export_json = ""
    session_state.export_csv = ""
    session_state.file = None
    session_state.error = None
    session_state.event = ""
    session_state.package_uid = None
    session_state.satisfied = False
    session_state.unsatisfaction = None
    return True


@st.dialog(title="Load Config")
def dialog_load_config():
    load_key = "load_config_uploader"

    uploaded = st.file_uploader(
        "Select a config JSON file",
        type=["json"],
        key=load_key,
        accept_multiple_files=False,
    )

    st.markdown(
        '<span id="sp-load-cfg-marker" style="display:none"></span>',
        unsafe_allow_html=True,
    )

    if uploaded is not None:
        try:
            raw_bytes = uploaded.read()
            raw_text = raw_bytes.decode("utf-8")
        except Exception as e:
            st.error(f"Failed to read uploaded file: {e}")
            return

        try:
            preview = json.loads(raw_text)
            with st.expander("Config preview", expanded=False):
                st.json(preview)
        except Exception:
            pass

        if st.button("Load and Apply", type="primary", key="load_apply_btn"):
            if _apply_loaded_config(raw_text):
                st.success("Config loaded successfully.")
                # Dismiss the dialog shortly after a successful apply, before
                # the st.rerun() below rebuilds the page.
                st.html(
                    r"""
                    <script>
                    (function() {
                        function findDialogRoot() {
                            var marker = document.getElementById("sp-load-cfg-marker");
                            if (!marker) return null;
                            if (marker.closest) {
                                var closest =
                                    marker.closest('[data-testid="stDialog"]') ||
                                    marker.closest(".stDialog");
                                if (closest) return closest;
                            }
                            var cur = marker;
                            for (var i = 0; i < 20 && cur; i++) {
                                if (
                                    cur.nodeType === 1 &&
                                    (cur.getAttribute("data-testid") === "stDialog" ||
                                        (cur.classList && cur.classList.contains("stDialog")))
                                ) {
                                    return cur;
                                }
                                cur = cur.parentElement;
                            }
                            return null;
                        }
                        function findCloseButton(root) {
                            if (!root) return null;
                            var btn = root.querySelector('button[aria-label="Close"]');
                            if (btn) return btn;
                            var list = root.querySelectorAll("button");
                            for (var i = 0; i < list.length; i++) {
                                var label = (list[i].getAttribute("aria-label") || "").toLowerCase();
                                if (label.indexOf("close") !== -1) return list[i];
                            }
                            return null;
                        }
                        setTimeout(function() {
                            var close = findCloseButton(findDialogRoot());
                            if (close) try { close.click(); } catch (e) {}
                        }, 100);
                    })();
                    </script>
                    """,
                    unsafe_allow_javascript=True,
                )
                st.rerun()
            else:
                st.error("Failed to apply config.")

    # On success the dialog closes quickly, but also bind the close action to
    # the Load and Apply button so a click always dismisses the dialog even if
    # Python rerun timing shifts.
    st.html(
        r"""
        <script>
        (function() {
            var INTERVAL_MS = 100;
            var MAX_ATTEMPTS = 40;
            var LISTENER_KEY = "__spLoadCfgCloseBound_v1";

            function findDialogRoot() {
                var marker = document.getElementById("sp-load-cfg-marker");
                if (!marker) return null;
                if (marker.closest) {
                    var closest =
                        marker.closest('[data-testid="stDialog"]') ||
                        marker.closest(".stDialog");
                    if (closest) return closest;
                }
                var cur = marker;
                for (var i = 0; i < 20 && cur; i++) {
                    if (
                        cur.nodeType === 1 &&
                        (cur.getAttribute("data-testid") === "stDialog" ||
                            (cur.classList && cur.classList.contains("stDialog")))
                    ) {
                        return cur;
                    }
                    cur = cur.parentElement;
                }
                return null;
            }

            function findCloseButton(root) {
                if (!root) return null;
                var btn = root.querySelector('button[aria-label="Close"]');
                if (btn) return btn;
                var list = root.querySelectorAll("button");
                for (var i = 0; i < list.length; i++) {
                    var label = (list[i].getAttribute("aria-label") || "").toLowerCase();
                    if (label.indexOf("close") !== -1) return list[i];
                }
                return null;
            }

            function findLoadApplyBtn(root) {
                if (!root) return null;
                var list = root.querySelectorAll("button");
                for (var i = 0; i < list.length; i++) {
                    var txt = (list[i].innerText || list[i].textContent || "").trim();
                    if (txt === "Load and Apply") return list[i];
                }
                return null;
            }

            var attempt = 0;
            var misses = 0;
            var intervalId = setInterval(function() {
                attempt += 1;
                var root = findDialogRoot();
                if (!root) {
                    misses += 1;
                    if (attempt >= MAX_ATTEMPTS || misses >= 5) {
                        clearInterval(intervalId);
                    }
                    return;
                }
                misses = 0;
                var btn = findLoadApplyBtn(root);
                if (!btn) {
                    if (attempt >= MAX_ATTEMPTS) clearInterval(intervalId);
                    return;
                }
                if (!btn[LISTENER_KEY]) {
                    btn[LISTENER_KEY] = true;
                    btn.addEventListener("click", function() {
                        setTimeout(function() {
                            var close = findCloseButton(findDialogRoot());
                            if (close) try { close.click(); } catch (e) {}
                        }, 80);
                    });
                }
                if (btn[LISTENER_KEY] || attempt >= MAX_ATTEMPTS) {
                    clearInterval(intervalId);
                }
            }, INTERVAL_MS);
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def render_save_config_button(key_suffix: str = "", *, disabled: bool = False):
    key = f"btn_save_config_{session_state.page}{key_suffix}"
    if st.button("Save Config", key=key, disabled=disabled):
        st.session_state.pop("save_config_filename", None)
        dialog_save_config()


def render_load_config_button(key_suffix: str = "", *, disabled: bool = False):
    key = f"btn_load_config_{session_state.page}{key_suffix}"
    if st.button("Load Config", key=key, disabled=disabled):
        dialog_load_config()


def render_back_to_top():
    # Streamlit renders the main page inside a nested layout, but not directly on
    # window, so we enumerate common candidates and pick whichever one that
    # actually has content overflow and a non-zero scrollTop. This covers the
    # stMain / stMainBlockContainer / stApp variants as well as plain
    # window/documentElement fallbacks.
    st.html(
        """
        <div class="back-to-top-wrapper">
            <button id="back-to-top-btn"
                    type="button"
                    title="Back to top"
                    style="opacity:.5; pointer-events:none;
                           transition:opacity .15s, background-color .15s;
                           border:none; background:transparent; cursor:pointer;
                           padding:8px; border-radius:50%;
                           font-size:20px; line-height:1;">
                &#8679;
            </button>
        </div>
        """,
    )
    # Attach scroll listeners to the detected containers so the button is
    # only interactive when the user has scrolled down, and scroll to top
    # on click.
    st.html(
        r"""
        <script>
        (function() {
            var btn = document.getElementById('back-to-top-btn');
            if (!btn) return;

            var THRESHOLD_PX = 60;
            var btnEnabled = false;

            function setEnabled(enabled) {
                if (enabled === btnEnabled) return;
                btnEnabled = enabled;
                if (enabled) {
                    btn.style.opacity = '1';
                    btn.style.pointerEvents = 'auto';
                    btn.style.cursor = 'pointer';
                } else {
                    btn.style.opacity = '.5';
                    btn.style.pointerEvents = 'none';
                    btn.style.cursor = 'default';
                }
            }

            function candidateList() {
                var out = [];
                out.push(window);
                var selectors = [
                    '[data-testid="stMainBlockContainer"]',
                    '[data-testid="stAppViewBlockContainer"]',
                    '[data-testid="stMain"]',
                    'section.main',
                    '.stApp',
                    '[data-testid="stAppViewContainer"]',
                    '#root',
                ];
                for (var i = 0; i < selectors.length; i++) {
                    var list = document.querySelectorAll(selectors[i]);
                    for (var j = 0; j < list.length; j++) out.push(list[j]);
                }
                // Fall back to documentElement/body when none of the wrapper
                // elements actually scroll.
                if (document.documentElement) out.push(document.documentElement);
                if (document.body) out.push(document.body);
                return out;
            }

            function isScrollable(el) {
                if (el === window) {
                    var doc = document.documentElement;
                    return doc && doc.scrollHeight - doc.clientHeight > THRESHOLD_PX * 2;
                }
                if (!el || el.nodeType !== 1) return false;
                var style;
                try { style = window.getComputedStyle ? getComputedStyle(el) : null; }
                catch (e) { style = null; }
                var overflowY = style ? (style.overflowY || el.style.overflowY || '') : '';
                if (overflowY && overflowY !== 'visible' && overflowY !== 'hidden' && overflowY !== 'clip') {
                    // Candidate with explicit scrollable overflow.
                }
                return el.scrollHeight - el.clientHeight > THRESHOLD_PX * 2;
            }

            function getScrollTop(el) {
                if (el === window) {
                    if (window.pageYOffset != null) return window.pageYOffset;
                    return document.documentElement.scrollTop || 0;
                }
                return el.scrollTop || 0;
            }

            function setScrollTop(el, value) {
                if (el === window) {
                    try { window.scrollTo({ top: value, behavior: 'smooth' }); } catch (e) {
                        try { window.scrollTo(0, value); } catch (e2) {}
                    }
                    return;
                }
                try {
                    el.scrollTo({ top: value, behavior: 'smooth' });
                } catch (e) {
                    try { el.scrollTop = value; } catch (e2) {}
                }
            }

            function findActiveScroller() {
                var list = candidateList();
                var best = null;
                var bestTop = -1;
                for (var i = 0; i < list.length; i++) {
                    var el = list[i];
                    if (!isScrollable(el)) continue;
                    var top = getScrollTop(el);
                    if (top > bestTop) {
                        bestTop = top;
                        best = el;
                    }
                }
                if (!best) {
                    var doc = document.documentElement;
                    if (doc && doc.scrollHeight - doc.clientHeight > THRESHOLD_PX) return window;
                }
                return best;
            }

            function refresh() {
                var scroller = findActiveScroller();
                if (!scroller) { setEnabled(false); return; }
                setEnabled(getScrollTop(scroller) > THRESHOLD_PX);
            }

            btn.addEventListener('click', function() {
                var scroller = findActiveScroller();
                if (!scroller) return;
                setScrollTop(scroller, 0);
            });

            // Listen on all common containers (plus window/document) so the
            // button toggles correctly regardless of which one actually
            // overflows.
            var attachTargets = [];
            var sel = [
                '[data-testid="stMainBlockContainer"]',
                '[data-testid="stAppViewBlockContainer"]',
                '[data-testid="stMain"]',
                'section.main',
                '.stApp',
            ];
            for (var k = 0; k < sel.length; k++) {
                var nodes = document.querySelectorAll(sel[k]);
                for (var m = 0; m < nodes.length; m++) attachTargets.push(nodes[m]);
            }
            if (window) attachTargets.push(window);
            if (document) attachTargets.push(document);
            for (var n = 0; n < attachTargets.length; n++) {
                try {
                    attachTargets[n].addEventListener('scroll', refresh, { passive: true });
                } catch (e) {}
            }
            // Initial state, plus a short poll after first render while
            // React mounts its widgets.
            refresh();
            var tries = 0;
            var tid = setInterval(function() {
                tries += 1;
                refresh();
                if (tries >= 25) clearInterval(tid);
            }, 100);
        })();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


@st.dialog(title="Attribute Description")
def show_attribute_description(attr_name: str):
    if not has_schema_attributes:
        st.warning("Failed to import seetapsych_attributes to show schema.")
        return

    model = attribute_schema.get(attr_name, None)
    if model is None:
        st.warning("No schema found!")
        return
    st.markdown(schema2markdown(model.model_json_schema()), unsafe_allow_html=True)


def page_start():
    st.title("Start")

    column_pipeline, column_packages = st.columns([1, 1])

    factory = session_state.factory
    pipeline = session_state.pipeline
    event = session_state.event

    assert factory is not None
    assert pipeline is not None

    with column_packages:
        st.subheader("Packages")

        search_package = st.text_input(
            "Search",
            value=session_state.search_package,
            key="search_package",
            label_visibility="collapsed",
        )
        if search_package != session_state.search_package:
            session_state.search_package = search_package
            st.rerun()

        packages = sorted(
            [p for p in factory.packages if fuzzy_match_package(p, search_package or "")],
            key=lambda p: (not bool(p.provides), tuple(p.provides), -p.priority, p.version, p.name),
        )

        for package in packages:
            with st.container(border=True):
                with st.container(horizontal=True):
                    st.markdown(f"**{package.name}** `v{package.version}`")
                    for i, provide_attr in enumerate(package.provides):
                        if st.button(provide_attr, type="tertiary", key=f"click:{package.uid}:{i}-{provide_attr}"):
                            show_attribute_description(provide_attr)
                with st.container(horizontal=True):
                    for keyword in package.keywords:
                        st.badge(keyword)
                st.write(package.description)
                with st.container(horizontal=True):
                    if st.button("Select", key=f"select:{package.uid}"):
                        pipeline.add_packages(package.uid)
                        st.rerun()

    with column_pipeline:
        st.subheader("Pipeline")

        pipeline_packages = pipeline.packages
        has_packages = bool(pipeline_packages)
        is_busy = bool(event)
        with st.container(horizontal=True):
            render_save_config_button(disabled=(not has_packages or is_busy))
            render_load_config_button(disabled=is_busy)

        if not pipeline_packages:
            st.info("Select package on right side.")

        for package in pipeline_packages:
            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package)
                if st.button("Delete", key=f"delete-package:{package.uid}", type="primary"):
                    pipeline.remove_package(package.uid)
                    st.rerun()

        problem = pipeline.problem()
        has_attribute_problem = bool(problem and (problem.missing_module_packages or problem.attributes))

        if has_attribute_problem:
            assert problem is not None
            with st.container():
                for pkg in problem.missing_module_packages:
                    st.error(f'Missing module for "{pkg.name}"', icon=ICON_ERROR)
                for attr in problem.attributes:
                    st.error(f'Missing required attribute "{attr}"', icon=ICON_ERROR)

        busy = st.empty()

        with st.container(horizontal=True):
            no_solve = bool(event) or not has_attribute_problem
            if st.button("Solve", disabled=no_solve):
                session_state.event = "solve"
                st.rerun()

            st.button("Prev", disabled=True, key="btn_start_prev")

            no_next = bool(event) or has_attribute_problem or not pipeline_packages
            if st.button("Next", disabled=no_next):
                session_state.package_uid = None
                session_state.page = "model"
                session_state.error = None
                st.rerun()

    if event == "solve":
        with busy.spinner("Solving...", show_time=True):
            pipeline.solve(ignore_models=True)
            session_state.event = ""
            st.rerun()


def page_model():
    st.title("Model")

    column_pipeline, column_models = st.columns([1, 1])

    pipeline = session_state.pipeline
    event = session_state.event
    edit_package_uid = session_state.package_uid

    assert pipeline is not None

    edit_package: schema.Package | None = None

    problem = pipeline.problem()
    missing_model_package_ids = set() if not problem else set([p.uid for p in problem.missing_model_packages])

    with column_pipeline:
        st.subheader("Pipeline")
        render_save_config_button(disabled=bool(event))

        for package in pipeline.packages:
            if edit_package_uid and package.uid == edit_package_uid:
                edit_package = package

            has_missing_model = package.uid in missing_model_package_ids

            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package, deletable=True)
                if st.button(
                    "Edit",
                    key=f"edit-model:{package.uid}",
                    type="primary" if has_missing_model else "secondary",
                ):
                    session_state.package_uid = package.uid
                    st.rerun()

        if problem:
            with st.container():
                for p in problem.missing_module_packages:
                    st.error(f'Missing module for "{p.name}"', icon=ICON_ERROR)
                for p in problem.missing_model_packages:
                    st.error(
                        f'Missing model for "{p.name}" where usage = {p.usage_models}',
                        icon=ICON_ERROR,
                    )
                for attr in problem.attributes:
                    st.error(f'Missing required attribute "{attr}"', icon=ICON_ERROR)

        busy = st.empty()

        with st.container(horizontal=True):
            no_solve = bool(event) or problem is None
            if st.button("Solve", disabled=no_solve):
                session_state.event = "solve"
                st.rerun()

            if st.button("Prev", disabled=bool(event)):
                session_state.page = "start"
                session_state.error = None
                st.rerun()

            no_next = bool(event) or problem is not None
            if st.button("Next", disabled=no_next):
                session_state.package_uid = None
                session_state.page = "setting"
                session_state.error = None
                st.rerun()

    with column_models:
        st.subheader("Models")

        if edit_package is None:
            st.info('Click "Edit" to edit package models.')
        else:
            st.markdown(f"**{edit_package.name}**")

        search_model = st.text_input(
            "Search",
            value=session_state.search_model,
            key="search_model",
            label_visibility="collapsed",
        )
        if search_model != session_state.search_model:
            session_state.search_model = search_model
            st.rerun()

        models = edit_package.models if edit_package else []
        models = [m for m in models if fuzzy_match_model(m, search_model or "")]

        for model_item in models:
            with st.container(border=True):
                with st.container(horizontal=True):
                    if model_item.recommended:
                        st.markdown(
                            f'<span style="color: red">*</span>**{model_item.name}** `v{model_item.version}`',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(f"**{model_item.name}** `v{model_item.version}`")
                with st.container(horizontal=True):
                    for keyword in model_item.keywords:
                        st.badge(keyword)
                st.write(model_item.description)
                with st.container(horizontal=True):
                    if st.button("Add", key=f"add-model:{model_item.uid}"):
                        assert edit_package is not None
                        pipeline.add_model(edit_package.uid, model_item.uid)
                        st.rerun()

    if event == "solve":
        with busy.spinner("Solving...", show_time=True):
            pipeline.solve()
            session_state.event = ""
            st.rerun()


def parameter_integer(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    value = st.number_input(
        key=key,
        label=parameter_display_name(param),
        value=cast(int, param.value),
        step=1,
    )
    if value != param.value:
        update = {param.name: int(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_number(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    value = st.number_input(
        key=key,
        label=parameter_display_name(param),
        value=cast(float, param.value),
        format="%f",
        step=1e-9,
    )
    if value != param.value:
        update = {param.name: float(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_string(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    value = st.text_input(
        key=key,
        label=parameter_display_name(param),
        value=cast(str, param.value),
    )
    if value != param.value:
        update = {param.name: str(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_selection(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    try:
        index = param.selection.index(cast(str, param.value))
    except Exception:
        index = 0 if param.selection else 0
    value = st.selectbox(
        key=key,
        label=parameter_display_name(param),
        options=cast(list[Any], param.selection),
        index=index if param.selection else 0,
    )
    if value is not None and value != param.value:
        update = {param.name: str(value)}
        pipeline.set_parameters(package_uid, update)


def parameter_boolean(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    value = st.toggle(
        key=key,
        label=parameter_display_name(param),
        value=cast(bool, param.value),
    )
    if value != param.value:
        update = {param.name: bool(value)}
        pipeline.set_parameters(package_uid, update)


T = TypeVar("T")


def format_array(t: type[T], value: list[T]) -> str:
    return ", ".join(map(str, value))


def parse_array(t: type[T], value: str) -> list[T] | None:
    try:
        t_cast = cast(Callable[[str], T], t)
        return [t_cast(v.strip()) for v in value.split(",") if v]
    except Exception:
        return None


def parameter_integer_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    format_value = format_array(int, cast(list[int], param.value))
    value = st.text_input(
        key=key,
        label=parameter_display_name(param),
        value=format_value,
    )
    if value is not None and value != format_value:
        parse_value = parse_array(int, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f"Invalid {parameter_display_name(param)}: {value}")


def parameter_number_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    format_value = format_array(float, cast(list[float], param.value))
    value = st.text_input(
        key=key,
        label=parameter_display_name(param),
        value=format_value,
    )
    if value is not None and value != format_value:
        parse_value = parse_array(float, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f"Invalid {parameter_display_name(param)}: {value}")


def parameter_string_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    format_value = format_array(str, cast(list[str], param.value))
    value = st.text_input(
        key=key,
        label=parameter_display_name(param),
        value=format_value,
    )
    if value is not None and value != format_value:
        parse_value = parse_array(str, value)
        if parse_value is not None:
            update = {param.name: parse_value}
            pipeline.set_parameters(package_uid, update)
        else:
            st.error(f"Invalid {parameter_display_name(param)}: {value}")


def parameter_selection_array(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    value = st.multiselect(
        key=key,
        label=parameter_display_name(param),
        options=cast(list[Any], param.selection),
        default=cast(list[Any], param.value),
    )
    if value is not None and value != param.value:
        update = {param.name: value}
        pipeline.set_parameters(package_uid, update)


def format_object(value: dict[str, Any]) -> str:
    value = value or {}
    try:
        return json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        return "{}"


def parse_object(value: str) -> dict[str, Any] | None:
    try:
        return cast(dict[str, Any], json.loads(value))
    except Exception:
        return None


def estimate_text_area_height(text: str, min_height: int = 200, max_height: int = 600, line_height: int = 20) -> int:
    if not text:
        return min_height
    line_count = text.count("\n") + 1
    estimated = max(min_height, min(max_height, line_count * line_height + 40))
    return estimated


def parameter_object_format(pipeline_ref: Pipeline, package_uid: str, param_name: str, text_key: str):
    raw_value = st.session_state.get(text_key, "{}")
    parsed = parse_object(raw_value)
    if parsed is None:
        return
    pretty = format_object(parsed)
    pipeline_ref.set_parameters(package_uid, {param_name: parsed})
    # text_area is an input widget (writes_allowed=True at instantiation).
    # Writing to session_state before rendering the widget ensures the next
    # display uses the formatted value. No rerun needed (callbacks run pre-script).
    setattr(st.session_state, text_key, pretty)


def parameter_object_import_json(pipeline_ref: Pipeline, package_uid: str, param_name: str, text_key: str):
    upload_key = "upload:json:" + text_key
    uploaded_file = st.session_state.get(upload_key)
    if uploaded_file is None:
        return
    try:
        raw = read_uploaded_file_bytes(uploaded_file)
        parsed = json.loads(raw.decode("utf-8"))
        if isinstance(parsed, dict):
            pretty = format_object(cast(dict[str, Any], parsed))
            pipeline_ref.set_parameters(package_uid, {param_name: cast(dict[str, Any], parsed)})
            setattr(st.session_state, text_key, pretty)
        else:
            st.error("JSON file must contain an object at top level.")
    except Exception as e:
        st.error(f"Failed to import JSON: {e}")


def parameter_object(pipeline: Pipeline, package_uid: str, param: schema.Parameter):
    key = package_uid + ":" + param.name
    upload_key = "upload:json:" + key
    fmt_key = "fmt:" + key

    format_value = format_object(cast(dict[str, Any], param.value))
    # Pre-instantiate session_state binding if absent.
    if key not in st.session_state:
        setattr(st.session_state, key, format_value)
    # If pipeline value diverges from widget state (e.g. external update), sync into widget.
    if st.session_state.get(key) != format_value and parse_object(st.session_state.get(key, "")) == parse_object(
        format_value
    ):
        setattr(st.session_state, key, format_value)

    display_value = st.session_state.get(key, format_value)
    height = estimate_text_area_height(display_value)

    on_click_fmt = partial(
        parameter_object_format,
        pipeline_ref=pipeline,
        package_uid=package_uid,
        param_name=param.name,
        text_key=key,
    )
    on_change_upload = partial(
        parameter_object_import_json,
        pipeline_ref=pipeline,
        package_uid=package_uid,
        param_name=param.name,
        text_key=key,
    )

    with st.container():
        value = st.text_area(
            key=key,
            label=parameter_display_name(param),
            height=height,
        )
        st.markdown('<div class="param-object-row">', unsafe_allow_html=True)
        with st.container(horizontal=True):
            st.file_uploader(
                "Import JSON",
                type=["json"],
                key=upload_key,
                label_visibility="collapsed",
                accept_multiple_files=False,
                on_change=on_change_upload,
            )
            st.button("Format", key=fmt_key, on_click=on_click_fmt)
        st.markdown("</div>", unsafe_allow_html=True)

    if value is not None and value != format_value:
        parse_value = parse_object(value)
        if parse_value is not None:
            pipeline.set_parameters(package_uid, {param.name: parse_value})
        else:
            st.error(f"Invalid {parameter_display_name(param)}: {value}")


def parameter_display_name(param: schema.Parameter) -> str:
    text = getattr(param, "text", "") or ""
    return text if text else param.name


def component_parameter(
    package_uid: str,
    param: schema.Parameter,
    *,
    show_description: bool = True,
):
    pipeline = session_state.pipeline
    assert pipeline is not None
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
            st.markdown(f"> {param.description}")
        generator = parameter_generators.get(param.type, None)
        if generator is not None:
            generator(pipeline, package_uid, param)
        else:
            st.markdown(f"**{parameter_display_name(param)}**: {param.value}")


def render_package_header(package: schema.Package):
    with st.container(horizontal=True):
        st.markdown(f"**{package.name}** `v{package.version}`")
        for provide_attr in package.provides:
            st.badge(provide_attr)


def render_package_models(pipeline: Pipeline, package: schema.Package, deletable: bool = False):
    models = pipeline.get_models(package.uid)
    for model_item in models:
        with st.container(horizontal=True):
            if model_item.usage:
                st.markdown(f"- **{model_item.usage}** {model_item.name} `v{model_item.version}`")
            else:
                st.markdown(f"- {model_item.name} `v{model_item.version}`")
            if deletable:
                if st.button("Delete", key=f"delete-model:{package.uid}:{model_item.uid}", type="primary"):
                    pipeline.remove_model(package.uid, model_item.uid)
                    st.rerun()


def page_setting():
    st.title("Setting")

    column_pipeline, column_parameters = st.columns([1, 1])

    pipeline = session_state.pipeline
    edit_package_uid = session_state.package_uid
    event = session_state.event

    assert pipeline is not None

    edit_package: schema.Package | None = None

    with column_pipeline:
        st.subheader("Pipeline")
        render_save_config_button(disabled=bool(event))

        for package in pipeline.packages:
            if edit_package_uid and package.uid == edit_package_uid:
                edit_package = package

            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package)
                with st.container(horizontal=True):
                    if st.button("Edit", key=f"edit:{package.uid}"):
                        session_state.package_uid = package.uid
                        st.rerun()

        with st.container(horizontal=True):
            st.button("Solve", disabled=True, key="btn_setting_solve")

            if st.button("Prev", disabled=bool(event)):
                session_state.page = "model"
                session_state.error = None
                st.rerun()

            if st.button("Next", disabled=bool(event)):
                session_state.page = "install"
                session_state.event = "satisfy"
                session_state.error = None
                st.rerun()

    with column_parameters:
        st.subheader("Parameters")

        if edit_package is None:
            st.info('Click "Edit" to edit package parameters.')
        else:
            st.markdown(f"**{edit_package.name}**")

            parameters: list[schema.Parameter] = []
            for p in edit_package.parameters:
                config_parameter = pipeline.get_parameter(edit_package.uid, p.name)
                if config_parameter is None:
                    parameters.append(p.model_copy(deep=True))
                else:
                    parameters.append(p.model_copy(deep=True, update={"value": config_parameter.value}))

            with st.container():
                search_value = st.text_input(
                    "Search parameters",
                    value=session_state.parameter_search,
                    key="parameter_search",
                    label_visibility="collapsed",
                    placeholder="Search parameters...",
                )
                show_description = st.checkbox(
                    "Show descriptions",
                    value=session_state.parameter_show_description,
                    key="parameter_show_description",
                )

                if search_value:
                    s = search_value.strip().lower()
                    parameters = [
                        p
                        for p in parameters
                        if (p.name and s in p.name.lower()) or (p.description and s in p.description.lower())
                    ]

                if not parameters:
                    st.info("No parameters matched.")
                else:
                    parameters = sorted(parameters, key=lambda p: (parameter_display_name(p) or "").lower())
                    for p in parameters:
                        component_parameter(edit_package.uid, p, show_description=show_description)


def page_install():
    st.title("Installation")

    column_pipeline, column_satisfaction = st.columns([1, 1])

    pipeline = session_state.pipeline
    cache_dir = session_state.cache_dir or ""
    satisfied = session_state.satisfied
    unsatisfaction = session_state.unsatisfaction
    error = session_state.error
    event = session_state.event

    assert pipeline is not None

    with column_pipeline:
        st.subheader("Pipeline")
        render_save_config_button(disabled=bool(event))

        for package in pipeline.packages:
            with st.container(border=True):
                render_package_header(package)
                render_package_models(pipeline, package)

        with st.container(horizontal=True):
            st.button("Solve", disabled=True, key="btn_install_solve")

            if st.button("Prev", disabled=bool(event)):
                session_state.page = "setting"
                session_state.error = None
                st.rerun()

            if st.button("Next", disabled=(bool(event) or not satisfied)):
                session_state.page = "run"
                session_state.event = "build"
                session_state.error = None
                st.rerun()

    with column_satisfaction:
        st.subheader("Satisfaction")

        if satisfied:
            st.success("This pipeline is ready for operation.")
        elif event == "satisfy":
            st.warning("Satisfaction still checking...")
        elif not unsatisfaction:
            st.error("This pipeline does not meet the criteria but no report has been issued.")
        else:
            for m in unsatisfaction.modules:
                requirements = "\n".join([f"- {r}" for r in m.requirements])
                st.error(
                    f"Module **{m.name}** `v{m.version}` require:\n\n{requirements}",
                    icon=ICON_ERROR,
                )
            for item in unsatisfaction.imports:
                entry_method, failed_pkg = item[0], item[1]
                st.error(
                    f"Failed to import `{failed_pkg}` when loading entry `{entry_method}`.",
                    icon=ICON_ERROR,
                )
            for entry in unsatisfaction.entries:
                prefix = entry.package or ""
                suffix = "." + entry.method if entry.package else entry.method
                st.error(f"Entry `{prefix}{suffix}` is not callable.", icon=ICON_ERROR)
            for model in unsatisfaction.models:
                st.error(f"Missing cache **{model.name or '<anonymous>'}** `v{model.version}`.", icon=ICON_ERROR)

        busy = st.empty()

        with st.container(horizontal=True):
            no_install = bool(event) or unsatisfaction is None or not unsatisfaction.modules
            if st.button("Install", disabled=no_install):
                session_state.event = "install"
                st.rerun()

            no_download = bool(event) or unsatisfaction is None or not unsatisfaction.models
            if st.button("Download", disabled=no_download):
                session_state.event = "download"
                st.rerun()

    if error is not None:
        if isinstance(error, BaseException):
            st.exception(error)
        else:
            st.error(str(error))

    if event == "satisfy":
        with busy.spinner("Checking...", show_time=True):
            satisfied, unsatisfaction = pipeline.satisfied(cache_dir=cache_dir)
            session_state.satisfied = satisfied
            session_state.unsatisfaction = unsatisfaction
            session_state.event = ""
            st.rerun()

    if event == "install":
        with busy.spinner("Install...", show_time=True):
            try:
                pipeline.install_requirements()
                session_state.error = None
            except Exception as e:
                session_state.error = e
            finally:
                session_state.event = "satisfy"
                st.rerun()

    if event == "download":
        with busy.spinner("Download...", show_time=True):
            try:
                pipeline.cache_models(cache_dir=cache_dir)
                session_state.error = None
            except Exception as e:
                session_state.error = e
            finally:
                session_state.event = "satisfy"
                st.rerun()


def run_image(runner: Runner, file: UploadedFile):
    reports = session_state.reports

    if not reports:
        with st.spinner("Open image...", show_time=True):
            image_bytes = read_uploaded_file_bytes(file)
            img_array = cv2.imdecode(numpy.frombuffer(image_bytes, numpy.uint8), cv2.IMREAD_COLOR)

        with st.spinner("Running...", show_time=True):
            try:
                report = runner.run(
                    {
                        "default": img_array,
                    }
                )
            except Exception as e:
                session_state.error = e
                st.rerun()

        report = sanitize_json(report)
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
            label="Download JSON",
            data=to_json(),
            file_name="report.json",
            mime="text/json",
            key="download_json",
        )

        st.download_button(
            label="Download CSV",
            data=to_csv(),
            file_name="report.csv",
            mime="text/csv",
            key="download_csv",
        )

    st.code(json.dumps(report, indent=2), language="json")


class CacheFile:
    def __init__(
        self,
        file: UploadedFile,
        auto_save: bool = False,
        *,
        temp_dir: str | None = None,
    ):
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
        file_obj = self.__file
        try:
            file_obj.seek(0)
        except Exception:
            pass
        with open(path, "wb") as f:
            while buf := file_obj.read(1024 * 1024):
                f.write(buf)
        try:
            file_obj.seek(0)
        except Exception:
            pass

    def __enter__(self) -> "CacheFile":
        if self.__auto_save:
            self.save()

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        if os.path.exists(self.__path):
            os.remove(self.__path)


class ReleaseCapture:
    def __init__(self, filename: str):
        self.__filename = filename
        self.__capture = cv2.VideoCapture()

    def __enter__(self) -> cv2.VideoCapture:
        self.__capture.open(self.__filename)
        return self.__capture

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        if self.__capture.isOpened():
            self.__capture.release()


def run_video(runner: Runner, file: UploadedFile):
    upload_dir = session_state.upload_dir
    reports = session_state.reports

    if not reports:
        with CacheFile(file, temp_dir=upload_dir) as temp:
            with st.spinner("Save video...", show_time=True):
                temp.save()

            with (
                st.spinner("Process video...", show_time=True),
                ReleaseCapture(temp.path) as capture,
            ):
                progress = st.progress(0)
                n = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                i = 0

                reports = []
                while capture.isOpened():
                    ok = capture.grab()
                    if not ok:
                        break
                    ok, frame_img = capture.retrieve()
                    if not ok:
                        break
                    frame_img = cast(numpy.ndarray, frame_img)
                    i += 1
                    try:
                        report = runner.run(
                            {
                                "default": frame_img,
                            },
                            timestamp=capture.get(cv2.CAP_PROP_POS_MSEC) / 1000,
                        )
                        reports.append(sanitize_json(report))
                    except Exception as e:
                        session_state.error = e
                        st.rerun()
                    ratio = (i / n) if n > 0 else 0.0
                    progress.progress(ratio, text=f"[{i}/{n}]")

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
            label="Download JSON",
            data=to_json(),
            file_name="report.json",
            mime="text/json",
            key="download_json",
        )

        st.download_button(
            label="Download CSV",
            data=to_csv(),
            file_name="report.csv",
            mime="text/csv",
            key="download_csv",
        )

    st.code(json.dumps(reports, indent=2), language="json")


def read_uploaded_file_bytes(file: UploadedFile) -> bytes:
    if hasattr(file, "getvalue"):
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
        "cache_dir": cache_dir or "",
        "pipeline": pipeline.config.model_dump(mode="json"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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
        "file_name": file_name,
        "file_type": file_type,
        "kind": kind,
        "item_index": item_index,
    }
    if frame_index is not None:
        meta["frame_index"] = frame_index
    if timestamp is not None:
        meta["timestamp"] = timestamp
    return {"__meta__": meta, **(report or {})}


def process_image_file(runner: Runner, file: UploadedFile) -> dict[str, Any]:
    image_bytes = read_uploaded_file_bytes(file)
    img_array = cv2.imdecode(numpy.frombuffer(image_bytes, numpy.uint8), cv2.IMREAD_COLOR)
    if img_array is None:
        raise RuntimeError(f"Invalid image: {file.name}")
    return cast(dict[str, Any], sanitize_json(runner.run({"default": img_array})))


def page_run():
    st.title("Run")

    runner = session_state.runner
    pipeline = session_state.pipeline
    cache_dir = session_state.cache_dir or ""
    upload_dir = session_state.upload_dir or ""
    error = session_state.error

    assert pipeline is not None

    event = session_state.event
    busy = st.empty()

    desired_signature = pipeline_signature(pipeline, cache_dir=cache_dir)
    if (
        runner is not None
        and session_state.runner_signature
        and session_state.runner_signature != desired_signature
        and event != "build"
    ):
        try:
            runner.dispose()
        except Exception:
            pass
        session_state.runner = None
        session_state.runner_signature = ""
        session_state.reports = []
        session_state.batch_grouped = []
        session_state.batch_rows = []
        session_state.export_json = ""
        session_state.export_csv = ""
        session_state.error = None
        session_state.event = "build"
        st.rerun()

    if runner is not None:
        st.success("Ready to run.")

        is_busy = bool(event)
        with st.container(horizontal=True):
            if st.button("Prev", key="btn_run_prev", disabled=is_busy):
                session_state.reports = []
                session_state.batch_grouped = []
                session_state.batch_rows = []
                session_state.export_json = ""
                session_state.export_csv = ""
                session_state.file = None
                session_state.error = None
                session_state.page = "install"
                session_state.event = ""
                st.rerun()
            render_save_config_button(disabled=is_busy)

        files = st.file_uploader(
            "Select image/video(s)",
            key="upload_input",
            type=["jpg", "png", "bmp", "mp4", "avi", "wmv"],
            accept_multiple_files=True,
        )
        signature = "|".join([getattr(f, "file_id", "") or f.name for f in files]) if files else ""
        if signature and session_state.file != signature:
            session_state.reports = []
            session_state.batch_grouped = []
            session_state.batch_rows = []
            session_state.export_json = ""
            session_state.export_csv = ""
            session_state.error = None
            session_state.file = signature

        if files:
            if len(files) == 1:
                single_file = files[0]
                if single_file.type.startswith("image/"):
                    st.image(single_file)
                    run_image(runner, single_file)
                elif single_file.type.startswith("video/"):
                    st.video(single_file)
                    run_video(runner, single_file)
            else:
                st.write(f"{len(files)} files selected.")
                if not session_state.batch_grouped:
                    if st.button("Run batch", disabled=bool(event)):
                        session_state.event = "run_batch"
                        st.rerun()
                else:
                    st.success(
                        f"Batch finished. "
                        f"Files: {len(session_state.batch_grouped)}, "
                        f"Rows: {len(session_state.batch_rows)}"
                    )

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
                            label="Download JSON",
                            data=to_json_grouped(),
                            file_name="reports.json",
                            mime="text/json",
                            key="download_json_batch",
                        )
                        st.download_button(
                            label="Download CSV",
                            data=to_csv_rows(),
                            file_name="reports.csv",
                            mime="text/csv",
                            key="download_csv_batch",
                        )

                    for item in session_state.batch_grouped:
                        file_name = item.get("file_name", "<unknown>")
                        kind = item.get("kind", "")
                        if "error" in item:
                            title = f"{file_name} ({kind})"
                        else:
                            count = item.get("count", 1)
                            title = f"{file_name} ({kind}, {count})"
                        with st.expander(title, expanded=False):
                            if "error" in item:
                                st.error(str(item["error"]))
                            elif kind == "image":
                                st.json(item.get("report", {}))
                            elif kind == "video":
                                display_video_reports = item.get("reports", [])
                                if display_video_reports:
                                    st.json(display_video_reports[0])
                                else:
                                    st.info("No frames processed.")

        if event == "run_batch":
            if not files or len(files) <= 1:
                session_state.event = ""
                st.rerun()

            with busy.spinner("Running batch...", show_time=True):
                overall = st.progress(0, text="Preparing...")
                grouped: list[dict[str, Any]] = []
                rows: list[dict[str, Any]] = []

                total = len(files)
                for item_index, f in enumerate(files):
                    overall.progress(item_index / total, text=f"[{item_index + 1}/{total}] {f.name}")
                    try:
                        if f.type.startswith("image/"):
                            report = process_image_file(runner, f)
                            grouped.append(
                                {
                                    "file_name": f.name,
                                    "file_type": f.type,
                                    "kind": "image",
                                    "count": 1,
                                    "report": report,
                                }
                            )
                            rows.append(
                                make_report_row(
                                    report,
                                    file_name=f.name,
                                    file_type=f.type,
                                    kind="image",
                                    item_index=item_index,
                                )
                            )
                        elif f.type.startswith("video/"):
                            progress_slot = st.empty()
                            progress = progress_slot.progress(0, text="[0/?]")
                            with CacheFile(f, temp_dir=upload_dir) as temp:
                                temp.save()
                                with ReleaseCapture(temp.path) as capture:
                                    if not capture.isOpened():
                                        raise RuntimeError(f"Unable to open video: {f.name}")

                                    n = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
                                    i = 0
                                    video_reports: list[dict[str, Any]] = []
                                    while capture.isOpened():
                                        ok = capture.grab()
                                        if not ok:
                                            break
                                        ok, frame_img = capture.retrieve()
                                        if not ok:
                                            break
                                        frame_img = cast(numpy.ndarray, frame_img)
                                        i += 1
                                        timestamp = capture.get(cv2.CAP_PROP_POS_MSEC) / 1000
                                        report = runner.run({"default": frame_img}, timestamp=timestamp)
                                        video_reports.append(sanitize_json(report))
                                        ratio = (i / n) if n > 0 else 0.0
                                        progress.progress(ratio, text=f"[{i}/{n}]")
                            progress_slot.empty()

                            grouped.append(
                                {
                                    "file_name": f.name,
                                    "file_type": f.type,
                                    "kind": "video",
                                    "count": len(video_reports),
                                    "reports": video_reports,
                                }
                            )
                            for frame_index, report in enumerate(video_reports):
                                rows.append(
                                    make_report_row(
                                        report,
                                        file_name=f.name,
                                        file_type=f.type,
                                        kind="video",
                                        item_index=item_index,
                                        frame_index=frame_index,
                                    )
                                )
                        else:
                            grouped.append(
                                {
                                    "file_name": f.name,
                                    "file_type": f.type,
                                    "kind": "unknown",
                                    "error": f"Unsupported file type: {f.type}",
                                }
                            )
                    except Exception as e:
                        grouped.append(
                            {
                                "file_name": f.name,
                                "file_type": f.type,
                                "kind": "error",
                                "error": str(e),
                            }
                        )

                overall.progress(1.0, text="Done")
                session_state.batch_grouped = grouped
                session_state.batch_rows = rows
                session_state.event = ""
                st.rerun()

    if event == "build":
        with busy.spinner("Building...", show_time=True):
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
                session_state.event = ""
                st.rerun()

    if error is not None:
        if isinstance(error, BaseException):
            st.exception(error)
        else:
            st.error(str(error))


@st.cache_resource(show_spinner=True)
def load_factory(
    dirs: list[str] | None = None,
    files: list[str] | None = None,
    urls: list[str] | None = None,
    disable_builtin: bool = False,
    disable_default: bool = False,
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

    if files:
        factory.load_file_modules(*files)

    if urls:
        factory.load_url_modules(*urls)

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

.param-object-row [data-testid="stFileUploaderDropzone"] {
    min-height: 2.4rem;
    padding: 0.2rem 0.6rem;
}
.param-object-row [data-testid="stFileUploaderDropzoneInstructions"] small {
    font-size: 0.7rem;
}
.param-object-row [data-testid="stFileUploaderFileInput"] button,
.param-object-row [data-testid="stFileUploadDropzoneButton"],
.param-object-row section[data-testid="stFileUploader"] button,
.param-object-row .stButton button {
    min-height: 2.2rem;
    padding: 0 0.8rem;
    font-size: 0.85rem;
}

.back-to-top-wrapper {
    position: fixed;
    right: 2rem;
    bottom: 2rem;
    z-index: 9999;
    pointer-events: none;
}

.back-to-top-wrapper button {
    pointer-events: auto;
    width: 3rem;
    height: 3rem;
    border-radius: 50%;
    border: none;
    background: #f0f2f6;
    color: #31333f;
    font-size: 1.2rem;
    cursor: pointer;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.15);
    transition: opacity 0.2s ease, background 0.2s ease;
    opacity: 1;
    display: flex;
    align-items: center;
    justify-content: center;
}

.back-to-top-wrapper button:hover:not(:disabled) {
    background: #e0e4eb;
}

.back-to-top-wrapper button:disabled {
    opacity: 0.35;
    cursor: not-allowed;
}
"""


class Args(Protocol):
    dirs: list[str]
    files: list[str]
    urls: list[str]
    disable_builtin: bool
    disable_default: bool
    cache_dir: str | None
    upload_dir: str | None
    log: str | None


def initialize(args: Args):
    st.set_page_config(
        layout="wide",
        page_title="SeetaPsych WebUI",
        page_icon=ICON_PAGE,
    )
    st.markdown(f"<style>{global_style}</style>", unsafe_allow_html=True)

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
            upload_dir_val = os.path.abspath(args.upload_dir)
        else:
            upload_dir_val = os.path.join(tempfile.gettempdir(), "seetapsych-webui", "upload")
        session_state.upload_dir = upload_dir_val

    if session_state.pipeline is None:
        session_state.pipeline = Pipeline(session_state.factory)


def parse_args() -> Args:
    parser = argparse.ArgumentParser(description="SeetaPsych WebUI via Streamlit.")

    parser.add_argument("--dirs", nargs="+", type=str, default=[], help="Load modules from dirs in factory.")

    parser.add_argument("--files", nargs="+", type=str, default=[], help="Load modules from local files in factory.")

    parser.add_argument("--urls", nargs="+", type=str, default=[], help="Load modules from urls in factory.")

    parser.add_argument("--disable-builtin", action="store_true", help="Diable load builtin modules.")

    parser.add_argument("--disable-default", action="store_true", help="Diable load default modules.")

    parser.add_argument("--cache-dir", type=str, default=None, help="Cache dir to store models.")

    parser.add_argument(
        "--upload-dir",
        type=str,
        default=None,
        help=("Directory to store uploaded files (default: upload subdirectory in current working directory)"),
    )

    parser.add_argument("--log", type=str, default=None, help="string or int, like DEBUG, INFO, WARNING or 10")

    return cast(Args, cast(object, parser.parse_args()))


def main():
    initialize(parse_args())

    pages = {
        "start": page_start,
        "model": page_model,
        "setting": page_setting,
        "install": page_install,
        "run": page_run,
    }

    page = session_state.page
    if page not in pages:
        st.error(f"Can not find page: {page}")
        return

    pages[page]()

    render_back_to_top()


if __name__ == "__main__":
    main()
