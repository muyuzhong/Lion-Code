from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.verify_desktop_delivery import (
    _parse_ready_record,
    _reject_web_members,
    verify_sidecar_layout,
    verify_source_layout,
)


def _source_layout(root: Path, *, desktop_version: str = "1.0.0") -> None:
    desktop = root / "desktop"
    desktop.mkdir(parents=True)
    (desktop / "package.json").write_text(
        json.dumps(
            {
                "version": desktop_version,
                "build": {
                    "files": ["out/**", "THIRD_PARTY_NOTICES.md"],
                    "extraResources": [
                        {
                            "from": "sidecar/lion-sidecar",
                            "to": "sidecar",
                            "filter": ["**/*"],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        '[project]\nname = "lion_code"\nversion = "1.0.0"\n', encoding="utf-8"
    )


def test_source_layout_requires_version_resource_and_web_cutover(
    tmp_path: Path,
) -> None:
    _source_layout(tmp_path)
    verify_source_layout(tmp_path)

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    verify_source_layout(tmp_path)
    (frontend / "index.html").write_text("legacy", encoding="utf-8")
    with pytest.raises(ValueError, match="旧 Web"):
        verify_source_layout(tmp_path)


def test_source_layout_rejects_version_drift(tmp_path: Path) -> None:
    _source_layout(tmp_path, desktop_version="0.9.0")

    with pytest.raises(ValueError, match="版本不一致"):
        verify_source_layout(tmp_path)


def test_sidecar_layout_requires_executable_and_excludes_python_source(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "lion-sidecar.exe"
    executable.write_bytes(b"exe")
    verify_sidecar_layout(tmp_path)

    (tmp_path / "leaked.py").write_text("secret = True", encoding="utf-8")
    with pytest.raises(ValueError, match="Python 源码"):
        verify_sidecar_layout(tmp_path)


def test_distribution_members_reject_removed_web_assets() -> None:
    _reject_web_members(["lion_code/server/app.py"], "wheel")

    with pytest.raises(ValueError, match="旧 Web"):
        _reject_web_members(["lion_code/server/static/index.html"], "wheel")


def test_ready_record_parser_is_strict() -> None:
    assert _parse_ready_record(
        '{"type":"ready","version":1,"port":4312,"capability":"secret"}'
    ) == {
        "type": "ready",
        "version": 1,
        "port": 4312,
        "capability": "secret",
    }

    with pytest.raises(ValueError, match="ready 记录无效"):
        _parse_ready_record(
            '{"type":"ready","version":1,"port":"4312","capability":""}'
        )
