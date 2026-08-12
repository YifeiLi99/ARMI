"""Stable package entry point for the ARMI kernel."""

from .config_yaml import load_yaml_file, load_yaml_mapping

__all__ = ("load_yaml_file", "load_yaml_mapping")
