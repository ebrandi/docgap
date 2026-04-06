#!/bin/sh
#
# docgap Installation Script
#
# This script installs docgap on FreeBSD or Linux with all dependencies.
#
# Usage: ./install.sh [--user USER] [--data-dir PATH] [--config-dir PATH]
#
# Supported: FreeBSD 14.3+, Linux (Ubuntu 24.04+, Debian 12+, Fedora 40+)
#

set -e

# Load shared OS detection and helpers
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/common.sh"

# Default configuration (DOCgap_DATA_DIR and DOCgap_CONFIG_DIR set by common.sh)
DOCgap_USER="${DOCgap_USER:-root}"

# Parse command line options
while [ $# -gt 0 ]; do
    case "$1" in
        --user)
            [ -z "${2:-}" ] && { echo "ERROR: --user requires a value" >&2; exit 1; }
            DOCgap_USER="$2"
            shift 2
            ;;
        --data-dir)
            [ -z "${2:-}" ] && { echo "ERROR: --data-dir requires a value" >&2; exit 1; }
            DOCgap_DATA_DIR="$2"
            shift 2
            ;;
        --config-dir)
            [ -z "${2:-}" ] && { echo "ERROR: --config-dir requires a value" >&2; exit 1; }
            DOCgap_CONFIG_DIR="$2"
            shift 2
            ;;
        --help)
            echo "Usage: $0 [--user USER] [--data-dir PATH] [--config-dir PATH]"
            echo ""
            echo "Options:"
            echo "  --user USER        Run as USER (default: root)"
            echo "  --data-dir PATH    Data directory (default: $DOCgap_DATA_DIR)"
            echo "  --config-dir PATH  Config directory (default: $DOCgap_CONFIG_DIR)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== docgap Installation ==="
echo ""
echo "  OS: $OS_TYPE"
echo ""

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Install/check required system dependencies
echo "Checking system dependencies..."

# Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "  python3 not found, installing..."
    pkg_install "python3" "python311" "python3"
    # Verify it installed successfully
    if ! command -v python3 >/dev/null 2>&1; then
        echo "ERROR: Failed to install python3" >&2
        exit 1
    fi
fi
PYTHON_VERSION=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2 | tr -d '.')
if [ "$PYTHON_VERSION" -lt 311 ]; then
    echo "ERROR: Python 3.11+ is required (found: $(python3 --version 2>&1 | cut -d' ' -f2))"
    exit 1
fi
echo "  Python $(python3 --version 2>&1 | cut -d' ' -f2) found"

# On FreeBSD, Python modules like sqlite3 are separate packages
if [ "$OS_TYPE" = "freebsd" ]; then
    PY_VER=$(python3 -c 'import sys; print(f"py{sys.version_info[0]}{sys.version_info[1]}")')
    # sqlite3 - required for docgap database
    if ! python3 -c "import sqlite3" 2>/dev/null; then
        echo "  sqlite3 module not found, installing..."
        pkg_install "sqlite3" "${PY_VER}-sqlite3" ""
        if ! python3 -c "import sqlite3" 2>/dev/null; then
            echo "ERROR: Failed to install Python sqlite3 module" >&2
            exit 1
        fi
    fi
    echo "  sqlite3 module available"
fi

# Validate user exists
if ! id "$DOCgap_USER" >/dev/null 2>&1; then
    echo "ERROR: User '$DOCgap_USER' does not exist" >&2
    exit 1
fi

# pip
echo "Checking pip..."
ensure_pip
echo "  pip available"

# git
if ! command -v git >/dev/null 2>&1; then
    echo "  git not found, installing..."
    pkg_install "git" "git" "git"
    if ! command -v git >/dev/null 2>&1; then
        echo "ERROR: Failed to install git" >&2
        exit 1
    fi
fi
echo "  git found"

# Ollama (optional)
echo "Checking optional dependencies..."
if ! command -v ollama >/dev/null 2>&1; then
    echo "WARNING: Ollama not found - LLM functionality will not work"
    pkg_hint "ollama" "pkg install ollama" "curl -fsSL https://ollama.com/install.sh | sh"
    echo ""
else
    echo "  Ollama found"
fi

# mandoc (optional)
if ! command -v mandoc >/dev/null 2>&1; then
    echo "WARNING: mandoc not found - mdoc validation will not work"
    pkg_hint "mandoc" "pkg install mandoc" "apt-get install mandoc"
    echo ""
else
    echo "  mandoc found"
fi

# Create directories
echo ""
echo "Creating directories..."
for dir in "$DOCgap_DATA_DIR" "$DOCgap_DATA_DIR/repos" "$DOCgap_DATA_DIR/output" "$DOCgap_DATA_DIR/reports" "$DOCgap_DATA_DIR/logs" "$DOCgap_CONFIG_DIR" "$DOCgap_CONFIG_DIR/prompts"; do
    if [ ! -d "$dir" ]; then
        mkdir -p "$dir"
        chown "$DOCgap_USER" "$dir"
        echo "  Created: $dir"
    else
        echo "  Already exists: $dir"
    fi
done

# Install Python package
echo ""
echo "Installing Python package..."
cd "$SCRIPT_DIR/.."
run_pip install -e .
echo "  Package installed"

# Install man page
echo ""
echo "Installing man page..."
if [ ! -d "$DOCgap_MAN_DIR" ]; then
    mkdir -p "$DOCgap_MAN_DIR"
fi
cp man/docgap.1 "$DOCgap_MAN_DIR/docgap.1"
chmod 444 "$DOCgap_MAN_DIR/docgap.1"
echo "  Installed: $DOCgap_MAN_DIR/docgap.1"

# Copy configuration
echo ""
echo "Configuring docgap..."
PROD_CONFIG="config/production.yaml"
DEFAULT_CONFIG="$DOCgap_CONFIG_DIR/config.yaml"

if [ -f "$PROD_CONFIG" ]; then
    if [ ! -f "$DEFAULT_CONFIG" ]; then
        cp "$PROD_CONFIG" "$DEFAULT_CONFIG"
        chmod 640 "$DEFAULT_CONFIG"
        echo "  Created: $DEFAULT_CONFIG"
        echo "  Please edit $DEFAULT_CONFIG to customize settings"
    else
        echo "  Configuration already exists: $DEFAULT_CONFIG"
        echo "  Skip: Use existing config or backup and copy manually"
    fi
else
    # Copy sample config only if no existing config
    if [ ! -f "$DEFAULT_CONFIG" ]; then
        cp config/config.yaml.sample "$DEFAULT_CONFIG"
        sed_inplace "s|/var/db/docgap|$DOCgap_DATA_DIR|g" "$DEFAULT_CONFIG"
        chmod 640 "$DEFAULT_CONFIG"
        echo "  Created: $DEFAULT_CONFIG"
    else
        echo "  Configuration already exists: $DEFAULT_CONFIG"
        echo "  Skip: Use existing config or backup and copy manually"
    fi
fi

# Initialize database
echo ""
echo "Initializing database..."
"$DOCgap_BIN_DIR/docgap" --config "$DEFAULT_CONFIG" init
echo "  Database initialized"

# Set permissions
echo ""
echo "Setting permissions..."
chown -R "$DOCgap_USER" "$DOCgap_DATA_DIR"
chmod 600 "$DOCgap_DATA_DIR/docgap.sqlite"
echo "  Permissions set"

# Install service
echo ""
echo "Installing service..."
install_service "$SCRIPT_DIR"

# Install cron entry
echo ""
echo "Installing cron entry..."
install_cron "$SCRIPT_DIR"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit $DEFAULT_CONFIG to customize settings"
echo "  2. Run 'ollama pull qwen3-coder-next-512k' for LLM support"
case "$OS_TYPE" in
    freebsd)
        echo "  3. Run 'service cron start' to enable cron scheduling"
        echo "  4. Run 'service docgap start' or add to /etc/rc.conf"
        ;;
    linux)
        echo "  3. Run 'systemctl enable --now docgap' to enable the service"
        echo "  4. Cron scheduling is active via $DOCgap_CRON_DIR/docgap"
        ;;
esac
echo ""
echo "For more information, see the README"
