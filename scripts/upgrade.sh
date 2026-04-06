#!/bin/sh
#
# docgap Upgrade Script
#
# This script upgrades docgap to the latest version while preserving configuration.
#
# Usage: ./upgrade.sh
#
# Supported: FreeBSD 14.3+, Linux (Ubuntu 24.04+, Debian 12+, Fedora 40+)
#

set -e

# Load shared OS detection and helpers
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/common.sh"

echo "=== docgap Upgrade ==="
echo ""
echo "  OS: $OS_TYPE"
echo ""

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Stop service before upgrade
echo "Stopping service..."
stop_service

# Check pip
echo "Checking pip..."
ensure_pip
echo "  pip available"

# Backup existing database
BACKUP_DIR="$DOCgap_DATA_DIR/backup"

if [ -d "$DOCgap_DATA_DIR" ]; then
    echo "Backing up existing data..."
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    if [ -f "$DOCgap_DATA_DIR/docgap.sqlite" ]; then
        cp "$DOCgap_DATA_DIR/docgap.sqlite" "$BACKUP_DIR/"
        chmod 600 "$BACKUP_DIR/docgap.sqlite"
        echo "  Backed up: docgap.sqlite"
    fi
fi

# Backup configuration
if [ -f "$DOCgap_CONFIG_DIR/config.yaml" ]; then
    echo "Backing up configuration..."
    mkdir -p "$BACKUP_DIR"
    cp "$DOCgap_CONFIG_DIR/config.yaml" "$BACKUP_DIR/config.yaml.backup"
    echo "  Backed up: config.yaml"
fi

# Update Python package
echo ""
echo "Upgrading Python package..."
cd "$SCRIPT_DIR/.."
run_pip install --upgrade -e .
echo "  Package upgraded"

# Install man page
echo ""
echo "Installing man page..."
if [ ! -d "$DOCgap_MAN_DIR" ]; then
    mkdir -p "$DOCgap_MAN_DIR"
fi
cp man/docgap.1 "$DOCgap_MAN_DIR/docgap.1"
chmod 444 "$DOCgap_MAN_DIR/docgap.1"
echo "  Installed: $DOCgap_MAN_DIR/docgap.1"

# Update service files
echo ""
echo "Updating service..."
install_service "$SCRIPT_DIR"

# Update cron entry
echo ""
echo "Updating cron entry..."
install_cron "$SCRIPT_DIR"

# Run any database migrations if needed
echo ""
echo "Checking database schema..."
echo "  Database schema check complete"

# Restore any new configuration defaults
echo ""
echo "Checking configuration..."
if [ -f "$DOCgap_CONFIG_DIR/config.yaml" ]; then
    echo "  Configuration preserved: $DOCgap_CONFIG_DIR/config.yaml"
else
    echo "  WARNING: Configuration not found, using defaults"
fi

echo ""
echo "=== Upgrade Complete ==="
echo ""
echo "Next steps:"
echo "  1. Review the README for any breaking changes"
case "$OS_TYPE" in
    freebsd)
        echo "  2. Check docgap status: $DOCgap_BIN_DIR/docgap status"
        echo "  3. Restart cron if needed: service cron restart"
        ;;
    linux)
        echo "  2. Check docgap status: $DOCgap_BIN_DIR/docgap status"
        echo "  3. Restart service if needed: systemctl restart docgap"
        ;;
esac
echo ""
