"""Dependency management, lazy loader, and diagnostic error utilities for Harness V0.1."""

import importlib
from pathlib import Path
import shutil
import sys
from typing import Any, Dict, Optional


class MissingDependencyError(RuntimeError):
    """Base exception for missing software dependencies."""
    pass


class MissingPythonDependencyError(MissingDependencyError):
    """Raised when an optional or required Python package is not found in the environment."""
    pass


class MissingSystemDependencyError(MissingDependencyError):
    """Raised when an external system binary is not found in PATH."""
    pass


def require_python_module(
    module_name: str,
    pip_package: Optional[str] = None,
    feature_description: Optional[str] = None,
) -> Any:
    """
    Lazily imports a Python module.
    If the module is missing, raises an actionable MissingPythonDependencyError.
    """
    pkg_name = pip_package or module_name
    feat = f" ({feature_description})" if feature_description else ""

    try:
        return importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError) as err:
        msg = (
            f"\n[ERROR: Missing Python Dependency]{feat}\n"
            f"The Python module '{module_name}' is not installed in the current environment ({sys.executable}).\n"
            f"To resolve this, install the package using the project virtual environment:\n"
            f"    ./.venv/bin/pip install {pkg_name}\n"
            f"Or install all harness requirements:\n"
            f"    ./.venv/bin/pip install -r requirements-harness.txt\n"
            f"Original error: {err}"
        )
        raise MissingPythonDependencyError(msg) from err


def require_system_tool(
    binary_name: str,
    system_package: Optional[str] = None,
    feature_description: Optional[str] = None,
) -> str:
    """
    Checks if an external system executable exists in PATH.
    Returns the resolved path or raises an actionable MissingSystemDependencyError.
    """
    path = shutil.which(binary_name)
    if path:
        return path

    pkg_name = system_package or binary_name
    feat = f" ({feature_description})" if feature_description else ""

    msg = (
        f"\n[ERROR: Missing System Dependency]{feat}\n"
        f"The system command '{binary_name}' was not found in PATH.\n"
        f"To resolve this on Ubuntu / Debian (WSL2), run:\n"
        f"    sudo apt-get update && sudo apt-get install -y {pkg_name}\n"
    )
    raise MissingSystemDependencyError(msg)


def check_all_dependencies() -> Dict[str, Any]:
    """Inspects the state of all direct Python and system dependencies."""
    python_deps = {
        "pikepdf": ("pikepdf", "pikepdf", "PDF parsing and inspection"),
        "pdfminer": ("pdfminer", "pdfminer.six", "PDF text stream extraction"),
        "lxml": ("lxml", "lxml", "OpenXML DOCX and XLSX processing"),
        "pydantic": ("pydantic", "pydantic", "Schema validation"),
        "yaml": ("yaml", "PyYAML", "YAML configuration parsing"),
        "pytest": ("pytest", "pytest", "Automated test suite"),
    }

    system_deps = {
        "file": ("file", "file", "Audio/media header detection"),
        "pdftoppm": ("pdftoppm", "poppler-utils", "PDF rasterization for OCR"),
        "tesseract": ("tesseract", "tesseract-ocr tesseract-ocr-eng tesseract-ocr-vie", "Optical character recognition"),
    }

    report = {"python": {}, "system": {}, "all_satisfied": True}

    for key, (mod, pkg, desc) in python_deps.items():
        try:
            importlib.import_module(mod)
            report["python"][key] = {"installed": True, "package": pkg, "desc": desc}
        except Exception:
            report["python"][key] = {"installed": False, "package": pkg, "desc": desc}
            report["all_satisfied"] = False

    for key, (bin_name, pkg, desc) in system_deps.items():
        p = shutil.which(bin_name)
        if p:
            report["system"][key] = {"installed": True, "path": p, "package": pkg, "desc": desc}
        else:
            report["system"][key] = {"installed": False, "path": None, "package": pkg, "desc": desc}
            report["all_satisfied"] = False

    return report
