"""Configuration loading and management."""
import dataclasses
import os
import sys
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import yaml

from docgap.config.defaults import get_default_config
from docgap.config.schema import Config


def get_default_config_path() -> Path:
    """Get the default configuration file path.

    Search order:
      1. /usr/local/etc/docgap/config.yaml  (FreeBSD)
      2. /etc/docgap/config.yaml             (Linux)
      3. {project_root}/config/config.yaml   (development)
      4. Falls back to FreeBSD system path   (will raise FileNotFoundError later)
    """
    # FreeBSD system path
    freebsd_path = Path("/usr/local/etc/docgap/config.yaml")
    if freebsd_path.exists():  # pragma: no cover
        return freebsd_path  # pragma: no cover

    # Linux system path
    linux_path = Path("/etc/docgap/config.yaml")
    if linux_path.exists():  # pragma: no cover
        return linux_path  # pragma: no cover

    # Fall back to local config for development
    local_path = Path(__file__).parent.parent.parent.parent / "config" / "config.yaml"
    if local_path.exists():  # pragma: no cover
        return local_path  # pragma: no cover

    return freebsd_path  # pragma: no cover — local config/config.yaml always exists in dev


def load_env_overrides(
    config_dict: Dict[str, Any], prefix: str = "DOCGAP_"
) -> Dict[str, Any]:
    """Apply environment variable overrides to config dict.
    
    Environment variables follow format: DOCGAMECTION_KEY
    Example: DOCGAP_GENERAL_DATA_DIR=/new/path
    
    Args:
        config_dict: Current configuration dictionary
        prefix: Environment variable prefix
        
    Returns:
        Config dict with environment overrides applied
    """
    env_overrides = {}

    # Get all env vars that start with our prefix
    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Convert DOCGAP_GENERAL_DATA_DIR -> general.data_dir
            var_name = key[len(prefix):].lower()
            parts = var_name.split("_")
            if len(parts) >= 2:
                section = parts[0]
                field_name = ".".join(parts[1:])
                if section not in env_overrides:
                    env_overrides[section] = {}
                env_overrides[section][field_name] = value

    # Apply overrides recursively
    for section, overrides in env_overrides.items():
        if section in config_dict:
            for field, value in overrides.items():
                if field in config_dict[section]:
                    config_dict[section][field] = convert_value(value, config_dict[section][field])

    return config_dict


def convert_value(value: str, target_type: Any) -> Any:
    """Convert string value to appropriate type."""
    if isinstance(target_type, bool):
        return value.lower() in ("true", "yes", "1")
    elif isinstance(target_type, int):
        return int(value)
    elif isinstance(target_type, float):
        return float(value)
    else:
        return value


def validate_config(config_dict: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Validate configuration dictionary.
    
    Args:
        config_dict: Configuration dictionary to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check required sections
    required_sections = ["general", "repositories", "llm", "detection", "generation", "review", "notification"]
    for section in required_sections:
        if section not in config_dict:
            return False, f"Missing required section: {section}"

    # Validate types
    # General config
    if not isinstance(config_dict.get("general", {}).get("data_dir"), str):
        return False, "general.data_dir must be a string"
    if not isinstance(config_dict.get("general", {}).get("log_level"), str):
        return False, "general.log_level must be a string"

    # LLM config
    llm = config_dict.get("llm", {})
    if not isinstance(llm.get("base_url"), str):
        return False, "llm.base_url must be a string"
    if not isinstance(llm.get("model"), str):
        return False, "llm.model must be a string"
    if not isinstance(llm.get("temperature"), (int, float)):
        return False, "llm.temperature must be a number"
    if not (0.0 <= llm.get("temperature", 0) <= 1.0):
        return False, "llm.temperature must be between 0.0 and 1.0"
    if not isinstance(llm.get("max_context"), int):
        return False, "llm.max_context must be an integer"
    if not isinstance(llm.get("timeout"), int):
        return False, "llm.timeout must be an integer"

    # Detection config
    detection = config_dict.get("detection", {})
    if not isinstance(detection.get("confidence_threshold_accept"), (int, float)):
        return False, "detection.confidence_threshold_accept must be a number"
    if not (0.0 <= detection.get("confidence_threshold_accept", 0) <= 1.0):
        return False, "detection.confidence_threshold_accept must be between 0.0 and 1.0"
    if not isinstance(detection.get("confidence_threshold_reject"), (int, float)):
        return False, "detection.confidence_threshold_reject must be a number"
    if not (0.0 <= detection.get("confidence_threshold_reject", 0) <= 1.0):
        return False, "detection.confidence_threshold_reject must be between 0.0 and 1.0"

    # Generation config
    generation = config_dict.get("generation", {})
    if not isinstance(generation.get("validate_mdoc"), bool):
        return False, "generation.validate_mdoc must be a boolean"
    if not isinstance(generation.get("validate_asciidoc"), bool):
        return False, "generation.validate_asciidoc must be a boolean"
    if not isinstance(generation.get("max_retries"), int):
        return False, "generation.max_retries must be an integer"

    # Notification config
    notification = config_dict.get("notification", {})
    if not isinstance(notification.get("from_address"), str):
        return False, "notification.from_address must be a string"
    if not isinstance(notification.get("smtp_host"), str):
        return False, "notification.smtp_host must be a string"

    return True, None


def load_config(config_path: Optional[str] = None) -> Config:
    """Load configuration from YAML file with environment override support.
    
    Args:
        config_path: Path to config file. If None, uses default path.
        
    Returns:
        Config object with all settings
        
    Raises:
        FileNotFoundError: If config file not found
        ValueError: If config validation fails
    """
    # Determine config path
    if config_path is None:
        config_path = str(get_default_config_path())
    
    file_path = Path(config_path)
    
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    # Load YAML
    try:
        with open(file_path, "r") as f:
            config_dict = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse configuration file: {e}")

    if config_dict is None:
        config_dict = {}

    # Convert to dict structure (handle nested dataclasses)
    config_dict = ensure_dict(config_dict)

    # Apply environment variable overrides
    config_dict = load_env_overrides(config_dict)

    # Validate
    is_valid, error_msg = validate_config(config_dict)
    if not is_valid:
        raise ValueError(f"Configuration validation failed: {error_msg}")

    # Apply defaults for missing values
    default_config = get_default_config()
    default_dict = ensure_dict(asdict(default_config))

    # Merge defaults with loaded config (loaded config takes precedence)
    config_dict = merge_dicts(default_dict, config_dict)

    # Convert to Config dataclass
    try:
        config = config_dict_to_dataclass(config_dict, Config)
    except Exception as e:  # pragma: no cover
        raise ValueError(f"Failed to create Config object: {e}")

    return config


def ensure_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass to dict if needed."""
    if hasattr(obj, "__dataclass_fields__"):  # pragma: no cover
        return asdict(obj)  # pragma: no cover
    return obj


def merge_dicts(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge override dict into base dict."""
    result = base.copy()
    for key, value in overrides.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dicts(result[key], value)
        else:
            result[key] = value
    return result


def config_dict_to_dataclass(data: Dict[str, Any], dataclass_type: type) -> Any:
    """Convert dictionary to dataclass recursively."""
    if not hasattr(dataclass_type, "__dataclass_fields__"):  # pragma: no cover
        return data  # pragma: no cover

    field_types = {
        f.name: f.type  # type: ignore
        for f in fields(dataclass_type)
        if f.init  # Only include fields that are part of __init__
    }

    kwargs: Dict[str, Any] = {}
    for field_name, field_type in field_types.items():
        if field_name in data:
            field_value = data[field_name]
            if hasattr(field_type, "__dataclass_fields__"):
                kwargs[field_name] = config_dict_to_dataclass(field_value, field_type)  # type: ignore
            else:
                kwargs[field_name] = field_value
        else:
            # Use default from dataclass
            field = next((f for f in fields(dataclass_type) if f.name == field_name), None)  # pragma: no cover
            if field and field.default_factory != dataclasses.MISSING:  # pragma: no cover
                kwargs[field_name] = field.default_factory()  # pragma: no cover
            elif field and field.default != dataclasses.MISSING:  # pragma: no cover
                kwargs[field_name] = field.default  # pragma: no cover
            else:  # pragma: no cover
                kwargs[field_name] = None  # pragma: no cover

    return dataclass_type(**kwargs)
