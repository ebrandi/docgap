#!/bin/sh
#
# docgap Uninstall Script
#
# This script removes docgap from the system.
#
# Usage: ./uninstall.sh [--keep-data] [--keep-config]
#
# Supported: FreeBSD 14.3+, Linux (Ubuntu 24.04+, Debian 12+, Fedora 40+)
#

set -e

# Load shared OS detection and helpers
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/common.sh"

# Parse command line options
KEEP_DATA=false
KEEP_CONFIG=false

while [ $# -gt 0 ]; do
    case "$1" in
        --keep-data)
            KEEP_DATA=true
            shift
            ;;
        --keep-config)
            KEEP_CONFIG=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--keep-data] [--keep-config]"
            echo ""
            echo "Options:"
            echo "  --keep-data   Keep data directory (database, output, logs)"
            echo "  --keep-config Keep configuration files"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "=== docgap Uninstall ==="
echo ""
echo "  OS: $OS_TYPE"
echo ""

# Check if running as root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Stop services
echo "Stopping services..."
stop_service

# Uninstall Python package
echo ""
echo "Uninstalling Python package..."
if python3 -m pip --version >/dev/null 2>&1; then
    run_pip uninstall -y docgap 2>/dev/null || true
    echo "  Package uninstalled"
else
    echo "  pip not available, skipping package removal"
fi

# Remove files
echo ""
echo "Removing files..."

# Remove man page
echo "Removing man page..."
rm -f "$DOCgap_MAN_DIR/docgap.1"
echo "  Removed man page"

# Remove service
uninstall_service

# Remove cron entry
uninstall_cron

# Remove Python package files
if [ -d "$DOCgap_PKG_DIR" ]; then
    rm -rf "$DOCgap_PKG_DIR"
    echo "  Removed: $DOCgap_PKG_DIR"
fi

# Remove data directory (unless --keep-data)
if [ ! "$KEEP_DATA" = true ] && [ -d "$DOCgap_DATA_DIR" ]; then
    # Safety: only remove if path is absolute and not a system directory
    case "$DOCgap_DATA_DIR" in
        /var/db/docgap|/var/lib/docgap|/var/db/docgap/*|/var/lib/docgap/*)
            rm -rf "$DOCgap_DATA_DIR"
            echo "  Removed: $DOCgap_DATA_DIR"
            ;;
        *)
            echo "  WARNING: Refusing to remove non-standard data dir: $DOCgap_DATA_DIR"
            echo "           Remove manually if intended"
            ;;
    esac
fi

# Remove config directory (unless --keep-config)
if [ ! "$KEEP_CONFIG" = true ] && [ -d "$DOCgap_CONFIG_DIR" ]; then
    case "$DOCgap_CONFIG_DIR" in
        /usr/local/etc/docgap|/etc/docgap)
            rm -rf "$DOCgap_CONFIG_DIR"
            echo "  Removed: $DOCgap_CONFIG_DIR"
            ;;
        *)
            echo "  WARNING: Refusing to remove non-standard config dir: $DOCgap_CONFIG_DIR"
            echo "           Remove manually if intended"
            ;;
    esac
fi

echo ""
echo "=== Uninstall Complete ==="
echo ""
echo "Data preserved: $KEEP_DATA"
echo "Config preserved: $KEEP_CONFIG"
echo ""
