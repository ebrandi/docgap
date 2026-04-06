"""Default configuration values."""
from docgap.config.schema import (
    AutoSubmitConfig,
    Config,
    DebugConfig,
    DetectionConfig,
    GenerationConfig,
    GeneralConfig,
    LLMConfig,
    NotificationConfig,
    RepositoriesConfig,
    RepositoryConfig,
    ReviewConfig,
)


def get_default_config() -> Config:
    """Return default configuration values."""
    return Config(
        general=GeneralConfig(
            data_dir="/var/db/docgap",
            log_level="info",
        ),
        repositories=RepositoriesConfig(
            freebsd_src=RepositoryConfig(
                path="/var/db/docgap/repos/freebsd-src",
                remote="https://github.com/freebsd/freebsd-src.git",
                branches=["main"],
            ),
            freebsd_doc=RepositoryConfig(
                path="/var/db/docgap/repos/freebsd-doc",
                remote="https://github.com/freebsd/freebsd-doc.git",
                branches=["main"],
            ),
        ),
        llm=LLMConfig(
            provider="ollama",
            base_url="http://localhost:11434",
            model="qwen3-coder-next-512k",
            temperature=0.1,
            max_context=524288,
            timeout=120,
        ),
        detection=DetectionConfig(
            confidence_threshold_accept=0.80,
            confidence_threshold_reject=0.50,
            skip_patterns=["^Merge ", "^MFC ", "^MFS ", "^Revert "],
            skip_paths=["contrib/", "sys/contrib/", ".github/"],
            skip_files=["Makefile", ".gitignore", "UPDATING", "ObsoleteFiles.inc"],
        ),
        generation=GenerationConfig(
            validate_mdoc=True,
            validate_asciidoc=True,
            max_retries=1,
        ),
        review=ReviewConfig(
            auto_submit=AutoSubmitConfig(
                enabled=False,
                hold_period_hours=72,
                categories={
                    "new_flag": False,
                    "new_command": False,
                    "changed_default": False,
                    "new_syscall": False,
                    "new_sysctl": False,
                    "changed_output": False,
                    "new_ioctl": False,
                    "api_change": False,
                },
            ),
        ),
        notification=NotificationConfig(
            doceng_recipients=["doceng@FreeBSD.org"],
            committer_notify=True,
            digest_only_if_findings=True,
            from_address="docgap@FreeBSD.org",
            smtp_host="localhost",
        ),
        debug=DebugConfig(),
    )
