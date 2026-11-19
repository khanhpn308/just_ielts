"""Tests for environment dependency management, lazy imports, and missing-dependency diagnostics."""

from pathlib import Path
import sys
import unittest.mock as mock
import pytest

from harness.dependencies import (
    MissingDependencyError,
    MissingPythonDependencyError,
    MissingSystemDependencyError,
    check_all_dependencies,
    require_python_module,
    require_system_tool,
)


def test_cli_help_works_with_masked_dependencies():
    """Verify CLI --help runs cleanly without any external packages imported."""
    with mock.patch.dict(sys.modules, {"pikepdf": None, "pdfminer": None, "lxml": None}):
        from harness.cli import main

        # Simulate invoking harness --help
        with mock.patch.object(sys, "argv", ["harness", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0


def test_missing_python_dependency_error():
    """Verify actionable diagnostic message when a Python dependency is missing."""
    with pytest.raises(MissingPythonDependencyError) as exc_info:
        require_python_module("nonexistent_package_foo", pip_package="foo-pkg", feature_description="testing")

    err_msg = str(exc_info.value)
    assert "[ERROR: Missing Python Dependency]" in err_msg
    assert "nonexistent_package_foo" in err_msg
    assert "./.venv/bin/pip install foo-pkg" in err_msg
    assert "requirements-harness.txt" in err_msg


def test_missing_system_tool_error():
    """Verify actionable diagnostic message when a system binary is missing from PATH."""
    with pytest.raises(MissingSystemDependencyError) as exc_info:
        require_system_tool("nonexistent_binary_bar", system_package="bar-utils", feature_description="testing")

    err_msg = str(exc_info.value)
    assert "[ERROR: Missing System Dependency]" in err_msg
    assert "nonexistent_binary_bar" in err_msg
    assert "sudo apt-get install -y bar-utils" in err_msg


def test_check_all_dependencies_healthy():
    """Verify environment health check passes in the configured .venv."""
    report = check_all_dependencies()
    assert "python" in report
    assert "system" in report
    assert report["all_satisfied"] is True

    # Assert expected direct packages are present
    for pkg in ["pikepdf", "pdfminer", "lxml", "pydantic", "yaml", "pytest"]:
        assert report["python"][pkg]["installed"] is True

    # Assert expected system tools are present
    for tool in ["file", "pdftoppm", "tesseract"]:
        assert report["system"][tool]["installed"] is True
        assert report["system"][tool]["path"] is not None


def test_docx_adapter_missing_lxml_raises_actionable_error():
    """Verify DocxExtractor raises actionable error when lxml is missing."""
    from harness.adapters.docx import DocxExtractor

    adapter = DocxExtractor()
    fake_source = {
        "file_id": "FILE-test",
        "relative_path": "fake/path.docx",
        "content_sha256": "abcdef",
    }

    with mock.patch.dict(sys.modules, {"lxml.etree": None}):
        with pytest.raises(MissingPythonDependencyError) as exc_info:
            adapter.extract_unit(fake_source, Path("/tmp"), "raw_document")
        assert "pip install lxml" in str(exc_info.value)


def test_pdf_native_missing_pikepdf_raises_actionable_error():
    """Verify PdfNativeExtractor raises actionable error when pikepdf is missing."""
    from harness.adapters.pdf_native import PdfNativeExtractor

    adapter = PdfNativeExtractor()
    fake_source = {
        "file_id": "FILE-test",
        "relative_path": "fake/path.pdf",
        "content_sha256": "abcdef",
    }

    with mock.patch.dict(sys.modules, {"pikepdf": None}):
        with pytest.raises(MissingPythonDependencyError) as exc_info:
            adapter.get_processing_units(fake_source)
        assert "pip install pikepdf" in str(exc_info.value)


def test_pdf_ocr_missing_system_tool_raises_actionable_error():
    """Verify PdfOcrExtractor raises actionable error when pdftoppm is missing from PATH."""
    from harness.adapters.pdf_ocr import PdfOcrExtractor

    adapter = PdfOcrExtractor()
    fake_source = {
        "file_id": "FILE-test",
        "relative_path": "fake/path.pdf",
        "content_sha256": "abcdef",
    }

    with mock.patch("shutil.which", return_value=None):
        with pytest.raises(MissingSystemDependencyError) as exc_info:
            adapter.extract_unit(fake_source, Path("/tmp"), "page_0001")
        assert "sudo apt-get install -y poppler-utils" in str(exc_info.value)
