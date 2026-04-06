"""Configuration schema definitions using dataclasses."""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class RepositoryConfig:
    """Configuration for a single repository."""
    path: str
    remote: str
    branches: List[str] = field(default_factory=list)


@dataclass
class RepositoriesConfig:
    """Configuration for all repositories."""
    freebsd_src: RepositoryConfig
    freebsd_doc: RepositoryConfig


@dataclass
class LLMConfig:
    """Configuration for LLM provider (Ollama)."""
    provider: str
    base_url: str
    model: str
    temperature: float
    max_context: int
    timeout: int


@dataclass
class DetectionConfig:
    """Configuration for detection stage."""
    confidence_threshold_accept: float
    confidence_threshold_reject: float
    skip_patterns: List[str] = field(default_factory=list)
    skip_paths: List[str] = field(default_factory=list)
    skip_files: List[str] = field(default_factory=list)


@dataclass
class GenerationConfig:
    """Configuration for generation stage."""
    enabled: bool = True
    validate_mdoc: bool = True
    validate_asciidoc: bool = True
    max_retries: int = 1


@dataclass
class AutoSubmitConfig:
    """Configuration for auto-submit feature."""
    enabled: bool
    hold_period_hours: int
    categories: dict = field(default_factory=dict)


@dataclass
class ReviewConfig:
    """Configuration for human review process."""
    auto_submit: AutoSubmitConfig


@dataclass
class NotificationConfig:
    """Configuration for email notifications."""
    enabled: bool = False
    doceng_recipients: List[str] = field(default_factory=list)
    committer_notify: bool = False
    digest_only_if_findings: bool = True
    from_address: str = "docgap@FreeBSD.org"
    smtp_host: str = "localhost"


@dataclass
class DebugConfig:
    """Configuration for debug/diagnostic features."""
    llm_logging: bool = False
    log_dir: str = ""
    max_debug_entries: int = 500
    include_config_snapshot: bool = True


@dataclass
class GeneralConfig:
    """General configuration settings."""
    data_dir: str
    log_level: str


@dataclass
class Config:
    """Main configuration object with all sections."""
    general: GeneralConfig
    repositories: RepositoriesConfig
    llm: LLMConfig
    detection: DetectionConfig
    generation: GenerationConfig
    review: ReviewConfig
    notification: NotificationConfig
    debug: DebugConfig = field(default_factory=DebugConfig)
