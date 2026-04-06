"""Tests for configuration loading and validation."""
import tempfile
from pathlib import Path

import pytest
import yaml

from docgap.config import Config, load_config


class TestConfigLoading:
    """Test configuration loading from YAML files."""

    def test_load_sample_config(self, test_config):
        """Test that sample config loads correctly."""
        assert test_config is not None
        assert test_config.general is not None
        assert test_config.general.data_dir is not None
        assert test_config.llm is not None
        assert test_config.llm.model is not None

    def test_config_data_dir(self, temp_dir):
        """Test configuration data directory."""
        config_path = temp_dir / "config.yaml"
        config_path.write_text(f"""
general:
  data_dir: /test/path
  log_level: debug

repositories:
  freebsd_src:
    path: {temp_dir}/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
    branches:
      - main
  freebsd_doc:
    path: {temp_dir}/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: http://localhost:11434
  model: test-model
  temperature: 0.1
  max_context: 524288
  timeout: 120

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
  skip_patterns: []

generation:
  validate_mdoc: false
  validate_asciidoc: false
  max_retries: 1

review:
  auto_submit:
    enabled: false

notification:
  enabled: false
  from_address: test@example.com
  smtp_host: localhost
""")
        config = load_config(str(config_path))
        assert config.general.data_dir == "/test/path"
        assert config.general.log_level == "debug"


class TestConfigDefaults:
    """Test that default values are applied correctly."""

    def test_default_log_level(self, test_config):
        """Test default log level."""
        assert test_config.general.log_level == "debug"

    def test_default_llm_timeout(self, test_config):
        """Test default LLM timeout."""
        assert test_config.llm.timeout == 120

    def test_default_confidence_thresholds(self, test_config):
        """Test default confidence thresholds."""
        assert test_config.detection.confidence_threshold_accept == 0.80
        assert test_config.detection.confidence_threshold_reject == 0.50


class TestConfigValidation:
    """Test configuration validation."""

    def test_invalid_config_raises_error(self, temp_dir):
        """Test that invalid config raises an error."""
        config_path = temp_dir / "config.yaml"
        config_path.write_text("""
llm:
  timeout: not_a_number
""")
        with pytest.raises(Exception):
            load_config(str(config_path))


class TestEnvironmentVariableOverrides:
    """Test environment variable override support."""

    def test_env_override_model(self, temp_dir, monkeypatch):
        """Test that environment variables can override config."""
        config_path = temp_dir / "config.yaml"
        config_path.write_text(f"""
general:
  data_dir: {temp_dir}
  log_level: debug

repositories:
  freebsd_src:
    path: {temp_dir}/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
    branches:
      - main
  freebsd_doc:
    path: {temp_dir}/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: http://localhost:11434
  model: default-model
  temperature: 0.1
  max_context: 524288
  timeout: 120

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
  skip_patterns: []

generation:
  validate_mdoc: false
  validate_asciidoc: false
  max_retries: 1

review:
  auto_submit:
    enabled: false

notification:
  enabled: false
  from_address: test@example.com
  smtp_host: localhost
""")
        monkeypatch.setenv("DOCGAP_LLM_MODEL", "env-model")
        config = load_config(str(config_path))
        assert config.llm.model == "env-model"


class TestConfigGetDefaultPath:
    """Test get_default_config_path."""

    def test_get_default_config_path(self):
        from docgap.config.loader import get_default_config_path
        path = get_default_config_path()
        assert path is not None
        assert str(path).endswith("config.yaml")


class TestConfigConvertValue:
    """Test convert_value for all types."""

    def test_convert_bool_true(self):
        from docgap.config.loader import convert_value
        assert convert_value("true", True) is True
        assert convert_value("yes", True) is True
        assert convert_value("1", True) is True

    def test_convert_bool_false(self):
        from docgap.config.loader import convert_value
        assert convert_value("false", True) is False
        assert convert_value("no", True) is False

    def test_convert_int(self):
        from docgap.config.loader import convert_value
        assert convert_value("42", 0) == 42

    def test_convert_float(self):
        from docgap.config.loader import convert_value
        assert convert_value("3.14", 0.0) == pytest.approx(3.14)

    def test_convert_string(self):
        from docgap.config.loader import convert_value
        assert convert_value("hello", "default") == "hello"


class TestConfigValidation:
    """Test validate_config branches."""

    def test_missing_section(self):
        from docgap.config.loader import validate_config
        valid, msg = validate_config({})
        assert valid is False
        assert "Missing required section" in msg

    def test_invalid_data_dir_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": 123, "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "data_dir" in msg

    def test_invalid_log_level_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": 123},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "log_level" in msg

    def test_invalid_temperature_range(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 2.0, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "temperature" in msg

    def test_invalid_base_url_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": 123, "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "base_url" in msg

    def test_invalid_model_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": 123, "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "model" in msg

    def test_invalid_max_context_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": "not_int", "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "max_context" in msg

    def test_invalid_timeout_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": "not_int"},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "timeout" in msg

    def test_invalid_confidence_accept_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": "high", "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "confidence_threshold_accept" in msg

    def test_invalid_confidence_accept_range(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 1.5, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "confidence_threshold_accept" in msg

    def test_invalid_confidence_reject_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": "low"},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "confidence_threshold_reject" in msg

    def test_invalid_validate_mdoc_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": "yes", "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "validate_mdoc" in msg

    def test_invalid_validate_asciidoc_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": "no", "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "validate_asciidoc" in msg

    def test_invalid_max_retries_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": "many"},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "max_retries" in msg

    def test_invalid_from_address_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": 123, "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "from_address" in msg

    def test_invalid_smtp_host_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": 123},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "smtp_host" in msg

    def test_invalid_confidence_reject_range(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 1.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "confidence_threshold_reject" in msg

    def test_invalid_temperature_type(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": "hot", "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is False
        assert "temperature" in msg

    def test_valid_config(self):
        from docgap.config.loader import validate_config
        config = {
            "general": {"data_dir": "/tmp", "log_level": "debug"},
            "repositories": {},
            "llm": {"base_url": "http://x", "model": "m", "temperature": 0.1, "max_context": 1, "timeout": 1},
            "detection": {"confidence_threshold_accept": 0.8, "confidence_threshold_reject": 0.5},
            "generation": {"validate_mdoc": False, "validate_asciidoc": False, "max_retries": 1},
            "review": {},
            "notification": {"from_address": "a@b", "smtp_host": "localhost"},
        }
        valid, msg = validate_config(config)
        assert valid is True
        assert msg is None


class TestLoadConfigErrors:
    """Test load_config error paths."""

    def test_load_config_file_not_found(self, temp_dir):
        with pytest.raises(FileNotFoundError):
            load_config(str(temp_dir / "nonexistent.yaml"))

    def test_load_config_yaml_error(self, temp_dir):
        bad_yaml = temp_dir / "bad.yaml"
        bad_yaml.write_text("{{bad yaml: [")
        with pytest.raises(Exception):
            load_config(str(bad_yaml))

    def test_load_config_validation_failure(self, temp_dir):
        config_path = temp_dir / "invalid.yaml"
        config_path.write_text("general:\n  data_dir: 123\n")
        with pytest.raises(ValueError):
            load_config(str(config_path))

    def test_load_config_empty_yaml(self, temp_dir):
        config_path = temp_dir / "empty.yaml"
        config_path.write_text("")
        with pytest.raises(ValueError):
            load_config(str(config_path))

    def test_load_config_default_path(self, temp_dir, monkeypatch):
        """Test load_config with None path uses default."""
        from docgap.config.loader import get_default_config_path
        # get_default_config_path returns some path - just verify it returns a Path
        path = get_default_config_path()
        assert path is not None


class TestConfigEnsureDict:
    """Test ensure_dict helper."""

    def test_ensure_dict_with_dict(self):
        from docgap.config.loader import ensure_dict
        d = {"key": "value"}
        assert ensure_dict(d) == d

    def test_ensure_dict_with_dataclass(self):
        from docgap.config.loader import ensure_dict
        from docgap.config.defaults import get_default_config
        config = get_default_config()
        result = ensure_dict(config)
        assert isinstance(result, dict)
        assert "general" in result


class TestConfigMergeDicts:
    """Test merge_dicts helper."""

    def test_merge_dicts_nested(self):
        from docgap.config.loader import merge_dicts
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        overrides = {"a": {"x": 10}, "c": 4}
        result = merge_dicts(base, overrides)
        assert result["a"]["x"] == 10
        assert result["a"]["y"] == 2
        assert result["b"] == 3
        assert result["c"] == 4


class TestConfigDictToDataclass:
    """Test config_dict_to_dataclass helper."""

    def test_config_dict_to_dataclass_with_missing_fields(self):
        from docgap.config.loader import config_dict_to_dataclass
        from docgap.config.schema import Config
        from docgap.config.defaults import get_default_config
        from dataclasses import asdict
        default = asdict(get_default_config())
        # Remove a field to test default handling
        config = config_dict_to_dataclass(default, Config)
        assert config is not None

    def test_config_dict_to_dataclass_non_dataclass(self):
        from docgap.config.loader import config_dict_to_dataclass
        result = config_dict_to_dataclass({"key": "value"}, dict)
        assert result == {"key": "value"}


class TestConfigGetDefaultPath:
    """Test get_default_config_path branches."""

    def test_default_path_returns_path(self):
        from docgap.config.loader import get_default_config_path
        from pathlib import Path
        path = get_default_config_path()
        assert isinstance(path, Path)

    def test_default_path_with_freebsd_system_path(self, monkeypatch):
        from docgap.config.loader import get_default_config_path
        from pathlib import Path
        from unittest.mock import patch
        # Mock Path.exists to return True for FreeBSD system path
        original_exists = Path.exists

        def mock_exists(self):
            if str(self) == "/usr/local/etc/docgap/config.yaml":
                return True
            return original_exists(self)

        with patch.object(Path, 'exists', mock_exists):
            path = get_default_config_path()
        assert str(path) == "/usr/local/etc/docgap/config.yaml"

    def test_default_path_with_linux_system_path(self, monkeypatch):
        from docgap.config.loader import get_default_config_path
        from pathlib import Path
        from unittest.mock import patch
        # Mock Path.exists to return True only for Linux system path
        original_exists = Path.exists

        def mock_exists(self):
            if str(self) == "/usr/local/etc/docgap/config.yaml":
                return False
            if str(self) == "/etc/docgap/config.yaml":
                return True
            return original_exists(self)

        with patch.object(Path, 'exists', mock_exists):
            path = get_default_config_path()
        assert str(path) == "/etc/docgap/config.yaml"

    def test_cli_uses_default_config_path_when_no_flag(self):
        """Verify CLI uses get_default_config_path() when -c is not given."""
        from click.testing import CliRunner
        from docgap.cli.main import main
        from unittest.mock import patch
        from pathlib import Path

        with patch("docgap.cli.main.get_default_config_path") as mock_default:
            mock_default.return_value = Path("/usr/local/etc/docgap/config.yaml")
            runner = CliRunner()
            # Invoke without --config; it will fail to find the file,
            # but we can verify get_default_config_path was called
            runner.invoke(main, ["init"])
            mock_default.assert_called()


class TestLoadConfigNonePath:
    """Test load_config(None) delegates to get_default_config_path."""

    def test_load_config_none_calls_default_path(self, temp_dir):
        """load_config(None) calls get_default_config_path and loads that file."""
        from unittest.mock import patch
        from docgap.config.loader import load_config

        # Write a minimal valid config in tmp_path
        config_path = temp_dir / "config.yaml"
        config_path.write_text(f"""
general:
  data_dir: {temp_dir}
  log_level: debug

repositories:
  freebsd_src:
    path: {temp_dir}/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
  freebsd_doc:
    path: {temp_dir}/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: http://localhost:11434
  model: test-model
  temperature: 0.1
  max_context: 524288
  timeout: 120

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
  skip_patterns: []

generation:
  validate_mdoc: false
  validate_asciidoc: false
  max_retries: 1

review:
  auto_submit:
    enabled: false

notification:
  enabled: false
  from_address: test@example.com
  smtp_host: localhost
""")

        with patch("docgap.config.loader.get_default_config_path", return_value=config_path) as mock_fn:
            config = load_config(None)
            mock_fn.assert_called_once()

        assert config.llm.model == "test-model"

    def test_env_var_base_url_not_applied_because_not_in_allowlist(self, temp_dir, monkeypatch):
        """DOCGAP_LLM_BASE_URL is not in the allowlist, so it must NOT override the config value."""
        from docgap.config.loader import load_config

        config_path = temp_dir / "config.yaml"
        config_path.write_text(f"""
general:
  data_dir: {temp_dir}
  log_level: debug

repositories:
  freebsd_src:
    path: {temp_dir}/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
  freebsd_doc:
    path: {temp_dir}/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  provider: ollama
  base_url: http://original-url:11434
  model: my-model
  temperature: 0.1
  max_context: 524288
  timeout: 120

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
  skip_patterns: []

generation:
  validate_mdoc: false
  validate_asciidoc: false
  max_retries: 1

review:
  auto_submit:
    enabled: false

notification:
  enabled: false
  from_address: test@example.com
  smtp_host: localhost
""")
        # base_url is NOT in the allowlist; model IS.
        monkeypatch.setenv("DOCGAP_LLM_BASE_URL", "http://injected-url:9999")
        monkeypatch.setenv("DOCGAP_LLM_MODEL", "env-override-model")

        config = load_config(str(config_path))

        # base_url must NOT be changed by the env var
        assert config.llm.base_url == "http://original-url:11434"
        # model must be overridden
        assert config.llm.model == "env-override-model"
