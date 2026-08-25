# -*- coding: utf-8 -*-

import os
import sys
from datetime import datetime

from seetapsych_configs import ConfigInfo, configs


TEMPLATE_NAME = 'template_doc_configs.md'
OUTPUT_NAME = 'CONFIGS.md'

SLOT_TABLE = '{{CONFIGS_TABLE}}'
SLOT_COUNT = '{{CONFIGS_COUNT}}'
SLOT_GENERATED_AT = '{{GENERATED_AT}}'


def _escape_md(text: str) -> str:
    return (
        text.replace('|', '\\|')
            .replace('\n', ' ')
            .strip()
    )


def _homepage_cell(cfg: ConfigInfo) -> str:
    return f'[Homepage]({cfg["homepage"]})' if cfg['homepage'] else '-'


def _download_cell(cfg: ConfigInfo) -> str:
    return f'[Download]({cfg["download_url"]})'


def render_table(cfgs: list[ConfigInfo]) -> str:
    lines: list[str] = [
        '| Name | Version | Description | Download | Homepage |',
        '| --- | --- | --- | --- | --- |',
    ]
    for cfg in cfgs:
        lines.append(
            '| {name} | {version} | {desc} | {dl} | {hp} |'.format(
                name=_escape_md(cfg['name']),
                version=_escape_md(cfg['version']),
                desc=_escape_md(cfg['description']),
                dl=_download_cell(cfg),
                hp=_homepage_cell(cfg),
            )
        )
    return '\n'.join(lines)


def load_template(scripts_dir: str) -> str:
    tpl_path = os.path.join(scripts_dir, TEMPLATE_NAME)
    with open(tpl_path, 'r', encoding='utf-8') as f:
        return f.read()


def render_md(cfgs: list[ConfigInfo], template: str) -> str:
    return (
        template
        .replace(SLOT_TABLE, render_table(cfgs))
        .replace(SLOT_COUNT, str(len(cfgs)))
        .replace(SLOT_GENERATED_AT, datetime.now().isoformat(timespec='seconds'))
    )


def main() -> int:
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(scripts_dir)

    template = load_template(scripts_dir)
    content = render_md(configs, template)

    output_path = os.path.join(project_root, OUTPUT_NAME)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(content)

    rel = os.path.relpath(output_path, os.getcwd())
    print(f'Wrote {len(configs)} config entries -> {rel}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
