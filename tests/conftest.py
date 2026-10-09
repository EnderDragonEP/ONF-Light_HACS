"""Test setup: import the integration's pure modules without Home Assistant.

The package's __init__.py imports Home Assistant, so we register a bare
package object pointing at the source folder. Only modules that don't import
Home Assistant (const, helpers) can be imported this way.
"""
import sys
import types
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "onf_light"

if "onf_light" not in sys.modules:
    package = types.ModuleType("onf_light")
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules["onf_light"] = package
