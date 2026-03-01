"""Tests for orchestrator.project — atomic writes and manifest handling."""

import json
import tempfile
from pathlib import Path

import pytest

from orchestrator.project import save_manifest, load_manifest


class TestAtomicManifestWrite:
    def test_write_and_read_manifest(self, tmp_path):
        manifest = {
            "project": "test",
            "topic": "test topic",
            "status": "created",
        }
        save_manifest(tmp_path, manifest)
        loaded = load_manifest(tmp_path)
        assert loaded == manifest

    def test_no_temp_file_left_behind(self, tmp_path):
        manifest = {"project": "test"}
        save_manifest(tmp_path, manifest)
        files = list(tmp_path.iterdir())
        names = [f.name for f in files]
        assert "manifest.json" in names
        assert "manifest.tmp" not in names

    def test_overwrite_preserves_atomicity(self, tmp_path):
        # Write first version
        save_manifest(tmp_path, {"version": 1})
        # Overwrite
        save_manifest(tmp_path, {"version": 2})
        loaded = load_manifest(tmp_path)
        assert loaded["version"] == 2

    def test_unicode_content(self, tmp_path):
        manifest = {"topic": "Análisis de gobernanza — áéíóú"}
        save_manifest(tmp_path, manifest)
        loaded = load_manifest(tmp_path)
        assert loaded["topic"] == "Análisis de gobernanza — áéíóú"


class TestLoadManifest:
    def test_load_nonexistent_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_manifest(tmp_path / "nonexistent")
