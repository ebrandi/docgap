# FreeBSD Documentation Gap Detector (docgap)

A Python CLI tool that monitors FreeBSD commits and generates documentation patches using LLM inference via Ollama (local or remote).

## Overview

docgap is a batch-processing pipeline that:

1. **Fetches** new commits from the FreeBSD source repository
2. **Detects** commits requiring documentation updates using a local LLM
3. **Generates** draft documentation patches in mdoc(7) or AsciiDoc format
4. **Stores** results in SQLite database and output directory

docgap bridges the documentation gap by identifying source code changes that need documentation updates before they're merged, reducing manual review workload for the FreeBSD Documentation Engineering team.

## Features

- **Two-Stage Detection Pipeline**:
  - Stage 1: Fast classification using LLM to identify documentation needs
  - Stage 2: Generates draft documentation patches for flagged commits
- **Configuration Control**: YAML-based configuration with environment variable overrides
- **SQLite State Management**: Tracks runs, commits, and notifications
- **Email Notifications**: Optional email alerts via sendmail
- **FreeBSD Integration**: rc.d service and cron job support
- **Human Review Gate**: Manual approval workflow for generated documentation
- **Resilience & Self-Healing**: Reprocess failed commits, detect stale runs, and auto-repair pipeline interruptions
- **LLM Debug Logging**: Optional capture of all LLM prompts and responses for cross-model performance evaluation

## System Requirements

### Hardware

- **Minimum** (remote Ollama): 4 GB RAM, 50 GB free disk space
- **Recommended** (local Ollama): 32+ GB RAM, 100+ GB free disk space
- **VRAM** (local Ollama only): See [Recommended LLM Models](#recommended-llm-models) below

### Software

| Package | Purpose | Version |
|------|-----|----|
| Python | Runtime environment | 3.11+ |
| Git | Repository management | 2.27+ |
| mandoc | mdoc validation | Latest (optional) |
| sendmail | Email notifications | Latest (optional) |

### LLM Inference (Ollama)

docgap requires access to an Ollama server for LLM inference. You have two options:

- **Local Ollama**: Install Ollama on the same machine. Best for air-gapped environments or when you have sufficient VRAM. See [Recommended LLM Models](#recommended-llm-models) for hardware requirements.
- **Remote Ollama**: Use an existing Ollama server on your network. No local GPU or VRAM needed — just set `llm.base_url` in `config.yaml` to point to the remote server (e.g., `http://your-server:11434`).

Installing Ollama locally is **optional** if you already have access to a remote Ollama server.

### FreeBSD Compatibility

- FreeBSD 14.3+ (primary target)
- FreeBSD 15 (tested)
- Compatible with Ubuntu 24.04+ (see install instructions)

## Installation

### Prerequisites

#### FreeBSD

```bash
# Update package repository
pkg update

# Install required packages
pkg install python311 py311-sqlite3 py311-yaml py311-click \
    py311-requests py311-click git mandoc

# (Optional) Install Ollama locally — skip if using a remote Ollama server
pkg install ollama
ollama pull qwen3.5:32b    # See "Recommended LLM Models" for options
ollama list                 # Verify the model is available
```

#### Using a Remote Ollama Server

If you have access to a remote Ollama server, you do not need to install Ollama
locally. After installing docgap, edit `config.yaml` and set the remote URL:

```yaml
llm:
  base_url: http://your-ollama-server:11434
  model: qwen3.5:32b    # Must match a model available on the remote server
```

Test connectivity with:

```bash
curl -s http://your-ollama-server:11434/api/tags | head -1
```

### Quick Install (Using Script)

```bash
# Clone the repository
git clone https://github.com/ebrandi/docgap.git
cd docgap

# Run the installation script
sudo ./scripts/install.sh
```

### Manual Install

```bash
# Clone and enter
git clone https://github.com/ebrandi/docgap.git
cd docgap

# Install Python package
pip install -e .

# Create data directories
mkdir -p /var/db/docgap/{repos,output,reports,logs}
chown -R nobody:nobody /var/db/docgap

# Copy and edit configuration
cp config/config.yaml.sample /usr/local/etc/docgap/config.yaml
# Edit /usr/local/etc/docgap/config.yaml with your settings
```

## Configuration

### Basic Configuration

Edit `/usr/local/etc/docgap/config.yaml`:

```yaml
general:
  data_dir: /var/db/docgap
  log_level: info

repositories:
  freebsd_src:
    path: /var/db/docgap/repos/freebsd-src
    remote: https://github.com/freebsd/freebsd-src.git
  freebsd_doc:
    path: /var/db/docgap/repos/freebsd-doc
    remote: https://github.com/freebsd/freebsd-doc.git

llm:
  base_url: http://localhost:11434
  model: qwen3-coder-next-512k
  timeout: 120

detection:
  confidence_threshold_accept: 0.80
  confidence_threshold_reject: 0.50
```

### Advanced Configuration

#### Skipping Patterns

```yaml
detection:
  skip_patterns:
    - "^Merge "          # Skip merge commits
    - "^MFC "            # Skip MFC commits
    - "^MFS "            # Skip MFS commits
    - "^Revert "         # Skip revert commits
  skip_paths:
    - contrib/           # Skip contrib directory
    - sys/contrib/       # Skip sys/contrib directory
  skip_files:
    - Makefile           # Skip Makefiles
    - .gitignore
    - UPDATING
```

#### Generation Settings

```yaml
generation:
  validate_mdoc: true
  validate_asciidoc: true
  max_retries: 1
```

#### Notification Settings

```yaml
notification:
  enabled: true
  doceng_recipients:
    - doceng@FreeBSD.org
  committer_notify: true
  digest_only_if_findings: true
  from_address: docgap@FreeBSD.org
  smtp_host: localhost
```

#### Debug Settings

```yaml
debug:
  # Save all LLM prompts and responses to disk
  llm_logging: false
  # Directory for debug logs (defaults to {data_dir}/debug)
  # log_dir: /var/db/docgap/debug
  # Maximum number of debug entries to keep
  max_debug_entries: 500
  # Include config snapshot in metadata.json
  include_config_snapshot: true
```

When enabled, LLM debug logging saves each prompt and response to:
```
/var/db/docgap/debug/<commit-hash>/
├── 01-stage1-detection-prompt.txt
├── 02-stage1-detection-response.txt
├── 03-stage2-generation-prompt.txt
├── 04-stage2-generation-response.txt
└── metadata.json
```

The `metadata.json` file includes the model name, pipeline version, timestamps, and a config snapshot. This makes it easy to compare results across different LLM models.

## Recommended LLM Models

docgap works with any Ollama-compatible model that supports chat and JSON output.
The model needs strong code comprehension and the ability to produce mdoc(7) or
AsciiDoc markup. Larger models produce better results but require more VRAM.

The following models are recommended, ordered from smallest to largest:

| Model | Parameters | Min VRAM | Context | Best For |
|-------|-----------|----------|---------|----------|
| `qwen3:8b` | 8B | 6 GB | 128k | Testing and evaluation on consumer hardware. Acceptable for Stage 1 detection; limited Stage 2 quality. |
| `qwen3.5:32b` | 32B | 20 GB | 128k | **Recommended starting point.** Good balance of quality and resource usage. Suitable for both detection and generation on workstation GPUs. |
| `llama4-scout:109b` | 109B (MoE) | 48 GB | 512k | High-quality results with large context window. Requires a workstation or server GPU (e.g., 2x RTX 4090 or A6000). |
| `qwen3.5:122b-96g-128k` | 122B | 96 GB | 128k | Production-grade quality. Used in the docgap development environment on GMKtec EVO-X2 (96 GB unified VRAM). Best accuracy for both detection and generation. |

**How to install a model:**

```bash
# On the machine running Ollama (local or remote)
ollama pull qwen3.5:32b

# Verify it's available
ollama list
```

**Tips:**

- Start with `qwen3.5:32b` if unsure — it runs on most modern workstations with a 24 GB GPU
- If you only have a CPU (no GPU), `qwen3:8b` will still work but inference will be significantly slower
- Set the model name in `config.yaml` under `llm.model` to match whatever you pulled
- The `max_context` setting in `config.yaml` must not exceed the model's supported context window

## Usage

### Basic Commands

```bash
# Run the full pipeline
docgap run

# Run from a specific date (backfill)
docgap run --since 2026-04-01T00:00:00Z

# Dry run - analyze without storing results
docgap run --dry-run

# Check system status
docgap status

# Query commit logs
docgap log
docgap log --since 2026-04-01 --status needs_doc
```

### Review Workflow

```bash
# List commits needing documentation
docgap review list

# View details of a specific commit
docgap review show <commit-hash>

# Approve a commit for documentation update
docgap review approve <commit-hash>
docgap review approve <commit-hash> --reviewer jdoe

# Bulk approve all pending reviews
docgap review approve --all
docgap review approve --all --since 2026-04-01T00:00:00Z

# Reject a commit (no documentation needed)
docgap review reject <commit-hash>
docgap review reject <commit-hash> --reason "not user-visible" --reviewer jdoe
```

### Resilience Commands

```bash
# Reprocess a specific commit through both stages
docgap reprocess <commit-hash>

# Reprocess only Stage 1 (detection) or Stage 2 (generation)
docgap reprocess --stage1 <commit-hash>
docgap reprocess --stage2 <commit-hash>

# Reprocess all failed commits
docgap reprocess --failed

# Reprocess all pending commits (needs_doc without doc_generated)
docgap reprocess --pending

# Reprocess commits since a date
docgap reprocess --since 2026-04-01T00:00:00Z

# Dry-run to see what would be reprocessed
docgap reprocess --failed --dry-run

# Detect pipeline issues (stale runs, stuck commits)
docgap heal

# Auto-fix detected issues
docgap heal --fix

# Check system integrity (config, DB, repos, LLM)
docgap validate

# Reset a commit to pending for full reprocessing
docgap reset <commit-hash>

# Clean old data from database
docgap purge --before 2026-01-01T00:00:00Z

# Purge with output directory cleanup
docgap purge --before 2026-01-01T00:00:00Z --include-output --confirm
```

### Report Generation

```bash
# Generate summary report (text)
docgap report

# Machine-readable JSON output for monitoring scripts
docgap report --format json
```

### Initialization

```bash
# Initialize database and directories
docgap init

# Initialize with custom config
docgap --config /path/to/config.yaml init
```

### Cron Setup

Add to `/etc/crontab` to run every 6 hours:

```bash
# Run docgap every 6 hours (4 times per day)
0 */6 * * * root /usr/local/bin/docgap run >> /var/db/docgap/logs/cron.log 2>&1
```

Or use the provided cron file:

```bash
cp scripts/cron.d/docgap /usr/local/etc/cron.d/docgap
service cron start
```

### Service Setup

```bash
# Install the rc.d service
cp scripts/rc.d/docgap /usr/local/etc/rc.d/docgap
chmod +x /usr/local/etc/rc.d/docgap

# Enable in rc.conf
echo 'docgap_enable="YES"' >> /etc/rc.conf

# Start the service
service docgap start

# Check status
service docgap status
```

## Daily Operations

### Typical Doceng Workflow

1. **Check for new findings**: `docgap review list`
2. **Review each finding**: `docgap review show <hash>`
3. **Approve valid findings**: `docgap review approve <hash>`
4. **Reject false positives**: `docgap review reject <hash> --reason "not user-visible"`
5. **Bulk approve reviewed items**: `docgap review approve --all`

### Backfilling After Downtime

If docgap was offline or the LLM was unavailable, backfill missed commits:

```bash
# Process commits from the last 30 days
docgap run --since 2026-03-01T00:00:00Z
```

If docgap crashed mid-pipeline, use the self-healing commands:

```bash
# Detect and report pipeline issues
docgap heal

# Auto-fix: mark stale runs as failed, reprocess stuck commits
docgap heal --fix

# Or manually retry only failed commits
docgap reprocess --failed
```

### Reviewing the Pipeline Report

```bash
# Text summary
docgap report

# JSON for scripting
docgap report --format json | python3 -m json.tool
```

### Output Directory Structure

Generated documentation patches are stored per-commit:
```
/var/db/docgap/output/<commit-hash>/
├── report.txt          # Human-readable analysis
├── manpage.patch       # mdoc(7) patch (for manpage targets)
├── handbook.patch      # AsciiDoc patch (for handbook targets)
└── metadata.json       # Classification and generation metadata
```

### Debug Directory Structure (when `debug.llm_logging` is enabled)

```
/var/db/docgap/debug/<commit-hash>/
├── 01-stage1-detection-prompt.txt    # Full prompt sent to LLM
├── 02-stage1-detection-response.txt  # Raw LLM response
├── 03-stage2-generation-prompt.txt   # Generation prompt (if needs_doc)
├── 04-stage2-generation-response.txt # Raw generation response
└── metadata.json                     # Model info, timestamps, config
```

## Implicit Behaviors and Defaults

docgap is designed to work with sensible defaults and minimal configuration.
The following behaviors happen automatically and are important to understand.

### Prompt Templates

docgap uses a three-level fallback chain for LLM prompt templates:

1. **System override** (`/usr/local/etc/docgap/prompts/{name}.txt`) — if present, used first
2. **Project local** (`prompts/{name}.txt` relative to install) — if present, used second
3. **Hardcoded default** — built into the Python source code, always available

The `/usr/local/etc/docgap/prompts/` directory is created empty during installation.
This is intentional — the prompts work out of the box with the hardcoded defaults.
To customize a prompt, create a file in that directory:

| Template File | Stage | Default Source |
|--------------|-------|----------------|
| `detection.txt` | Stage 1 (classification) | `docgap.core.prompts.DETECTION_PROMPT` |
| `generation-mdoc.txt` | Stage 2 (mdoc patches) | `docgap.core.generator._DEFAULT_MDOC_PROMPT` |
| `generation-asciidoc.txt` | Stage 2 (AsciiDoc patches) | `docgap.core.generator._DEFAULT_ASCIIDOC_PROMPT` |

### Configuration File Search Order

When no `-c/--config` is specified, docgap searches for the config file in this order:

1. `/usr/local/etc/docgap/config.yaml` (FreeBSD production)
2. `/etc/docgap/config.yaml` (Linux production)
3. `{project_root}/config/config.yaml` (development)

The first file found is used. If none exist, it defaults to the FreeBSD path (which will raise an error).

### Pipeline Resume Behavior

- **First run with no history**: processes commits from the **last 7 days** automatically. No `--since` flag needed.
- **Subsequent runs**: automatically resumes from the `finished_at` timestamp of the last successful run. Commits from earlier runs are never re-processed.
- **Already-processed commits**: if a commit hash already exists in the database (e.g., from an interrupted run), it is silently skipped during the next `docgap run`.

### Error Handling Defaults

- **LLM classification errors**: if the LLM call fails or returns unparseable output, the commit is classified as `UNCERTAIN` with confidence 0.0 rather than failing the pipeline. This keeps the pipeline running but may hide connectivity issues.
- **Unknown LLM categories**: if the LLM returns an unrecognized category, it is silently normalized to `OTHER`.
- **No patch generated**: if Stage 2 produces no valid unified diff, a placeholder comment patch with `TODO: Add documentation here` is saved and the commit is marked `doc_generated`. Review these carefully.

### Input Truncation

Large inputs are automatically truncated to prevent resource exhaustion:

| Input | Limit | Behavior |
|-------|-------|----------|
| Commit diff | 100,000 chars | Truncated with warning in debug log |
| Commit subject | 1,000 chars | Truncated silently |
| File list | 500 files | Truncated with warning in debug log |
| Doc content (generation) | 50,000 chars | Truncated with warning |
| LLM response | 200,000 chars | Truncated with warning |

Classification and generation are performed on the truncated input. For very large commits, results may be less accurate.

### Documentation Format Detection

docgap determines whether to generate mdoc(7) or AsciiDoc based on the `doc_target` path:

- Files ending in `.adoc`, `.asciidoc`, `.asc` → **AsciiDoc**
- Paths containing `handbook`, `books/`, or `articles/` → **AsciiDoc**
- Everything else (including when `doc_target` is unknown) → **mdoc**

### Documentation Retrieval Fallback

When generating documentation for a flagged commit, docgap looks for existing docs in this order:

1. **Path-based mapping** — deterministic rules (e.g., `usr.bin/ls/ls.c` → `usr.bin/ls/ls.1`)
2. **Keyword search** — searches doc file names and content for the command/syscall name
3. **No context** — generates the patch without existing documentation context

### Database Caution

`docgap init` **deletes and recreates** the database if one already exists. Always back up your database before running init on a system with existing data:

```bash
cp /var/db/docgap/docgap.sqlite /var/db/docgap/docgap.sqlite.backup
```

### Git Operations

- Git commands automatically retry up to 3 times on network/timeout errors with exponential backoff.
- Clone operations have a 2-hour timeout; all other git operations timeout after 60 seconds.
- Safe directory checks are bypassed automatically (`-c safe.directory=*`) to handle repos owned by different users.

## Architecture

See `docs/architecture/system-design.md` for detailed architecture diagrams.

### Pipeline Flow

```
┌─────────────┐
│   Git Fetch │──► Commit Log
└─────────────┘
        ▼
┌─────────────┐
│  Log Parser │──► Filtered Commits
└─────────────┘
        ▼
┌─────────────┐
│ Stage 1     │──► Classification (LLM)
│ Detection   │
└─────────────┘
        ▼
┌─────────────┐
│  Database   │──► Store Results
└─────────────┘
        ▼
┌─────────────┐     ┌─────────────┐
│ Stage 2     │ ──► │ Generation  │
│ Generation  │     │ (if needed) │
└─────────────┘     └─────────────┘
        ▼
┌─────────────┐
│   Output    │──► Patches + Reports
└─────────────┘
        ▼
┌─────────────┐
│ Notification│──► Email (optional)
└─────────────┘
        ▼ (optional)
┌─────────────┐
│ Debug Logger│──► Prompts + Responses
└─────────────┘
```

### Key Components

- **Stage 1 Detection**: Classifies commits as `needs_doc`, `irrelevant`, or `uncertain` using LLM
- **Stage 2 Generation**: Produces draft documentation patches in mdoc(7) or AsciiDoc format
- **SQLite Database**: Tracks runs, commits, classifications, and output
- **Git Fetcher**: Manages FreeBSD source and documentation repositories
- **Output Manager**: Generates patch files and reports in organized directories
- **Reprocess Runner**: Retries failed or interrupted commits through Stage 1 and/or Stage 2
- **LLM Debug Logger**: Captures prompts and responses for cross-model evaluation

## Configuration Reference

| Section | Setting | Type | Default | Description |
|----|----|----|----|----|
| `general.data_dir` | String | /var/db/docgap | Data storage directory |
| `general.log_level` | String | info | Logging level (debug, info, warning, error) |
| `repositories.freebsd_src.path` | String | - | FreeBSD src repository path |
| `repositories.freebsd_src.remote` | String | - | FreeBSD src git remote URL |
| `llm.base_url` | String | http://localhost:11434 | Ollama server URL |
| `llm.model` | String | qwen3-coder-next-512k | LLM model name |
| `llm.timeout` | Integer | 120 | LLM request timeout in seconds |
| `detection.confidence_threshold_accept` | Float | 0.80 | Accept threshold for documentation needs |
| `detection.confidence_threshold_reject` | Float | 0.50 | Reject threshold for irrelevant commits |
| `generation.validate_mdoc` | Boolean | true | Validate mdoc output with mandoc |
| `generation.validate_asciidoc` | Boolean | true | Validate AsciiDoc output |
| `debug.llm_logging` | Boolean | false | Enable LLM prompt/response logging |
| `debug.log_dir` | String | {data_dir}/debug | Debug log directory |
| `debug.max_debug_entries` | Integer | 500 | Max debug entries before rotation |

## Environment Variables

Configuration can be overridden using environment variables:

| Variable | Purpose |
|------|----|
| `DOCGAP_GENERAL_DATA_DIR` | Override `general.data_dir` |
| `DOCGAP_LLM_BASE_URL` | Override `llm.base_url` |
| `DOCGAP_LLM_MODEL` | Override `llm.model` |

## Troubleshooting

### Ollama Connection Failed

```bash
# Check Ollama is running
ollama ps

# Restart Ollama
service ollama restart

# Verify model is loaded
ollama list
```

### Database Error

```bash
# Check database integrity
sqlite3 /var/db/docgap/docgap.sqlite "PRAGMA integrity_check;"

# Backup and recreate if corrupted
cp /var/db/docgap/docgap.sqlite /var/db/docgap/docgap.sqlite.backup
rm /var/db/docgap/docgap.sqlite
docgap init
```

### No Commits Processed

```bash
# Check git repositories
ls -la /var/db/docgap/repos/

# Test git fetch manually
cd /var/db/docgap/repos/freebsd-src
git fetch --all --prune

# Run with verbose logging
docgap run --verbose
```

### Permission Denied

```bash
# Fix permissions
chown -R root:wheel /var/db/docgap
chmod 600 /var/db/docgap/docgap.sqlite
```

## Alerting and Monitoring

### Email Notifications

docgap sends two types of email notifications when findings exist:

1. **Digest emails** to the Doceng team — summary of each pipeline run
2. **Per-commit emails** to individual committers whose changes need documentation

Configure notifications in `config.yaml`:

```yaml
notification:
  enabled: true
  doceng_recipients:
    - doceng@FreeBSD.org
    - your-team-alias@FreeBSD.org
  committer_notify: true
  digest_only_if_findings: true
  from_address: docgap@FreeBSD.org
  smtp_host: localhost
```

Notifications require a working `sendmail(8)` on the host. Test with:

```bash
echo "test" | sendmail -v your-email@example.com
```

### Monitoring the Automated Pipeline

When running docgap as a cron job or rc.d service, monitor these indicators:

#### Check Last Run Status

```bash
# Quick health check
docgap status

# Machine-readable report for monitoring scripts
docgap report --format json
```

#### Monitor Cron Logs

```bash
# View recent cron output
tail -100 /var/db/docgap/logs/cron.log

# Check for errors in the last 24 hours
grep -i error /var/db/docgap/logs/cron.log | tail -20
```

#### Database Health

```bash
# Check database integrity
sqlite3 /var/db/docgap/docgap.sqlite "PRAGMA integrity_check;"

# View run history
sqlite3 /var/db/docgap/docgap.sqlite \
  "SELECT id, status, started_at, commits_processed, commits_flagged 
   FROM runs ORDER BY id DESC LIMIT 10;"

# Check for stale runs (no completed run in last 24h)
sqlite3 /var/db/docgap/docgap.sqlite \
  "SELECT CASE WHEN COUNT(*) > 0 THEN 'OK' ELSE 'STALE' END 
   FROM runs WHERE status='completed' 
   AND finished_at > datetime('now', '-24 hours');"
```

#### Disk Space Monitoring

```bash
# Check output directory size
du -sh /var/db/docgap/output/

# Check database size
ls -lh /var/db/docgap/docgap.sqlite
```

#### LLM Server Health

```bash
# Check Ollama is running and responsive
curl -s http://localhost:11434/api/tags | head -1

# Check loaded models
ollama ps
```

### Setting Up External Alerting

For production deployments, integrate with your monitoring system:

#### Simple cron-based health check

Create `/usr/local/etc/docgap/health-check.sh`:

```bash
#!/bin/sh
# docgap health check - run every hour from cron
# Alert if no successful run in the last 24 hours

STALE=$(sqlite3 /var/db/docgap/docgap.sqlite \
  "SELECT CASE WHEN COUNT(*) > 0 THEN 'OK' ELSE 'STALE' END 
   FROM runs WHERE status='completed' 
   AND finished_at > datetime('now', '-24 hours');")

if [ "$STALE" = "STALE" ]; then
    echo "WARNING: docgap has not completed a successful run in 24 hours" | \
        sendmail -t <<EOF
To: doceng@FreeBSD.org
From: docgap@FreeBSD.org
Subject: [docgap] Pipeline stale - no successful run in 24h

docgap has not completed a successful pipeline run in the last 24 hours.

Last run status:
$(docgap status 2>&1)

Check logs: tail -50 /var/db/docgap/logs/cron.log
EOF
fi

# Also check Ollama health
if ! curl -sf http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "WARNING: Ollama server is not responding" | \
        sendmail -t <<EOF
To: doceng@FreeBSD.org
From: docgap@FreeBSD.org
Subject: [docgap] Ollama server unreachable

The Ollama LLM server is not responding at http://localhost:11434.

Attempt restart: service ollama restart
EOF
fi
```

Add to cron:
```
0 * * * * root /usr/local/etc/docgap/health-check.sh
```

## Maintenance

### Updating

Use the upgrade script to update docgap while preserving your configuration
and database:

```bash
cd /path/to/docgap
sudo ./scripts/upgrade.sh
```

The upgrade script will:
1. Back up the database and configuration
2. Upgrade the Python package
3. Reinstall the man page
4. Check for schema changes

#### Manual Update

```bash
service docgap stop
pip install --upgrade -e .
service docgap start
```

### Backup

```bash
# Backup database
cp /var/db/docgap/docgap.sqlite /var/db/docgap/docgap.sqlite.backup

# Backup output files
tar czf docgap-output-backup.tar.gz /var/db/docgap/output
```

### Reset

To clear all history and start fresh:

```bash
service docgap stop
rm /var/db/docgap/docgap.sqlite
docgap init
service docgap start
```

### Uninstallation

```bash
# Using the uninstall script
sudo ./scripts/uninstall.sh

# Preserve data and config during uninstall
sudo ./scripts/uninstall.sh --keep-data --keep-config
```

The uninstall script removes the Python package, man page, rc.d service,
cron entry, and optionally the data directory and configuration files.

#### Manual Uninstall

```bash
service docgap stop
pip uninstall -y docgap
rm -f /usr/local/share/man/man1/docgap.1
rm -f /usr/local/etc/rc.d/docgap
rm -f /usr/local/etc/cron.d/docgap
rm -rf /var/db/docgap            # Remove data (optional)
rm -rf /usr/local/etc/docgap     # Remove config (optional)
```

## Contributing

We welcome contributions! Here's how to help:

1. **Fork the repository**
2. **Create a feature branch**: `git checkout -b feature/amazing-feature`
3. **Commit your changes**: `git commit -m 'Add amazing feature'`
4. **Push to the branch**: `git push origin feature/amazing-feature`
5. **Open a Pull Request**

### Development Setup

```bash
# Clone and enter
git clone https://github.com/ebrandi/docgap.git
cd docgap

# Install in development mode with test dependencies
pip install -e ".[test]"

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=docgap --cov-report=html
```

### Code Style

- Follow PEP 8 for Python code
- Use type hints where possible
- Include docstrings for public functions
- Write tests for new functionality

## License

This project is licensed under the BSD 2-Clause License. See the LICENSE file for details.

## Community

- **FreeBSD Doceng Team**: doceng@FreeBSD.org
- **Project Repository**: https://github.com/ebrandi/docgap
- **Issue Tracker**: https://github.com/ebrandi/docgap/issues

## Acknowledgments

- Powered by Ollama with Qwen 3 Next Coder model
- Built for the FreeBSD Documentation Engineering team
- Inspired by the FreeBSD commit workflow and documentation needs

## See Also

- `mdoc(7)` - FreeBSD document formatting language
- `asciidoc(5)` - AsciiDoc documentation format
- `ollama` - Local LLM server

## Man Page

docgap includes a comprehensive man page. After installation:

    man docgap

The man page covers all commands, options, configuration, examples, and diagnostics.

*Last updated: April 6, 2026*
