"""Configuration management package for docgap."""

from docgap.config.schema import Config
from docgap.config.loader import load_config, get_default_config_path

__all__ = ["Config", "load_config", "get_default_config_path"]
