#!/bin/sh
#
# docgap Common Functions
#
# Shared OS detection, path configuration, and helper functions
# for install, uninstall, and upgrade scripts.
#
# Usage: . "$(dirname "$0")/common.sh"
#

# --- OS Detection ------------------------------------------------------------

detect_os() {
    case "$(uname -s)" in
        FreeBSD)
            OS_TYPE="freebsd"
            ;;
        Linux)
            OS_TYPE="linux"
            ;;
        *)
            echo "ERROR: Unsupported operating system: $(uname -s)" >&2
            echo "       Supported: FreeBSD, Linux" >&2
            exit 1
            ;;
    esac
}

# --- Path Configuration ------------------------------------------------------

set_os_paths() {
    case "$OS_TYPE" in
        freebsd)
            : "${DOCgap_DATA_DIR:=/var/db/docgap}"
            : "${DOCgap_CONFIG_DIR:=/usr/local/etc/docgap}"
            : "${DOCgap_PKG_DIR:=/usr/local/lib/docgap}"
            DOCgap_MAN_DIR="/usr/local/share/man/man1"
            DOCgap_BIN_DIR="/usr/local/bin"
            DOCgap_SERVICE_DIR="/usr/local/etc/rc.d"
            DOCgap_CRON_DIR="/usr/local/etc/cron.d"
            ;;
        linux)
            : "${DOCgap_DATA_DIR:=/var/lib/docgap}"
            : "${DOCgap_CONFIG_DIR:=/etc/docgap}"
            : "${DOCgap_PKG_DIR:=/usr/lib/docgap}"
            DOCgap_MAN_DIR="/usr/share/man/man1"
            DOCgap_BIN_DIR="/usr/local/bin"
            DOCgap_SERVICE_DIR="/etc/systemd/system"
            DOCgap_CRON_DIR="/etc/cron.d"
            ;;
        *)
            echo "ERROR: Unknown OS_TYPE: '$OS_TYPE'" >&2
            exit 1
            ;;
    esac
}

# --- pip Handling -------------------------------------------------------------

# Find a working pip invocation. On FreeBSD base, pip may not exist;
# bootstrap it with ensurepip before proceeding.
ensure_pip() {
    if python3 -m pip --version >/dev/null 2>&1; then
        return 0
    fi

    echo "  pip not found, attempting bootstrap via ensurepip..."
    if python3 -m ensurepip --default-pip >/dev/null 2>&1; then
        echo "  pip bootstrapped successfully"
        return 0
    fi

    echo "ERROR: pip is not available and ensurepip failed." >&2
    case "$OS_TYPE" in
        freebsd)
            # Determine installed Python minor version for the package name
            PY_VER=$(python3 -c 'import sys; print(f"py{sys.version_info[0]}{sys.version_info[1]}")' 2>/dev/null || echo "py311")
            echo "       Install pip with: pkg install ${PY_VER}-pip" >&2
            ;;
        linux)
            echo "       Install pip with: apt-get install python3-pip  (Debian/Ubuntu)" >&2
            echo "                     or: dnf install python3-pip      (Fedora/RHEL)" >&2
            ;;
    esac
    exit 1
}

# Run pip with the correct flags for the current environment.
# Usage: run_pip install -e .
#        run_pip uninstall -y docgap
run_pip() {
    if [ -n "$VIRTUAL_ENV" ]; then
        python3 -m pip "$@"
    else
        python3 -m pip --break-system-packages "$@" 2>/dev/null \
            || python3 -m pip "$@"
    fi
}

# --- sed Portability ----------------------------------------------------------

# Portable in-place sed. BSD sed requires '' after -i; GNU sed does not.
# Usage: sed_inplace 's/old/new/g' file.txt
sed_inplace() {
    _expr="$1"
    _file="$2"
    case "$OS_TYPE" in
        freebsd)
            sed -i '' "$_expr" "$_file"
            ;;
        linux)
            sed -i "$_expr" "$_file"
            ;;
    esac
}

# --- Package Hints ------------------------------------------------------------

# Print OS-appropriate install instructions for a package.
# Usage: pkg_hint "ollama" "pkg install ollama" "See https://ollama.com/download/linux"
pkg_hint() {
    _name="$1"
    _freebsd_cmd="$2"
    _linux_cmd="$3"
    case "$OS_TYPE" in
        freebsd)
            echo "         Install with: $_freebsd_cmd"
            ;;
        linux)
            echo "         Install with: $_linux_cmd"
            ;;
    esac
}

# --- Package Installation -----------------------------------------------------

# Install a system package. Requires root.
# Usage: pkg_install python3 [freebsd_pkg_name] [linux_pkg_name]
#   If freebsd/linux names differ from the generic name, pass them explicitly.
pkg_install() {
    _generic="$1"
    _freebsd="${2:-$1}"
    _linux="${3:-$1}"
    case "$OS_TYPE" in
        freebsd)
            [ -z "$_freebsd" ] && return 0
            echo "  Installing $_freebsd via pkg..."
            pkg install -y "$_freebsd"
            ;;
        linux)
            [ -z "$_linux" ] && return 0
            echo "  Installing $_linux via apt-get..."
            apt-get install -y "$_linux" 2>/dev/null \
                || { echo "  apt-get failed, trying dnf..." ; dnf install -y "$_linux" ; }
            ;;
    esac
}

# --- Service Management ------------------------------------------------------

install_service() {
    _script_dir="$1"
    case "$OS_TYPE" in
        freebsd)
            if [ -f "$_script_dir/rc.d/docgap" ]; then
                cp "$_script_dir/rc.d/docgap" "$DOCgap_SERVICE_DIR/docgap"
                chmod +x "$DOCgap_SERVICE_DIR/docgap"
                echo "  Installed: $DOCgap_SERVICE_DIR/docgap"
                echo "  Enable with: echo 'docgap_enable=\"YES\"' >> /etc/rc.conf"
            else
                echo "  WARNING: rc.d script not found at $_script_dir/rc.d/docgap"
            fi
            ;;
        linux)
            if [ -f "$_script_dir/systemd/docgap.service" ]; then
                cp "$_script_dir/systemd/docgap.service" "$DOCgap_SERVICE_DIR/docgap.service"
                # Substitute actual paths into the installed service file
                sed_inplace "s|/usr/local/bin/docgap|$DOCgap_BIN_DIR/docgap|g" "$DOCgap_SERVICE_DIR/docgap.service"
                sed_inplace "s|/var/lib/docgap|$DOCgap_DATA_DIR|g" "$DOCgap_SERVICE_DIR/docgap.service"
                sed_inplace "s|/etc/docgap|$DOCgap_CONFIG_DIR|g" "$DOCgap_SERVICE_DIR/docgap.service"
                chmod 644 "$DOCgap_SERVICE_DIR/docgap.service"
                systemctl daemon-reload
                echo "  Installed: $DOCgap_SERVICE_DIR/docgap.service"
                echo "  Enable with: systemctl enable docgap"
            else
                echo "  WARNING: systemd unit not found at $_script_dir/systemd/docgap.service"
            fi
            ;;
    esac
}

uninstall_service() {
    case "$OS_TYPE" in
        freebsd)
            if [ -f "$DOCgap_SERVICE_DIR/docgap" ]; then
                rm "$DOCgap_SERVICE_DIR/docgap"
                echo "  Removed: $DOCgap_SERVICE_DIR/docgap"
            fi
            ;;
        linux)
            if [ -f "$DOCgap_SERVICE_DIR/docgap.service" ]; then
                systemctl disable docgap 2>/dev/null || true
                rm "$DOCgap_SERVICE_DIR/docgap.service"
                systemctl daemon-reload
                echo "  Removed: $DOCgap_SERVICE_DIR/docgap.service"
            fi
            ;;
    esac
}

stop_service() {
    case "$OS_TYPE" in
        freebsd)
            if [ -f "$DOCgap_SERVICE_DIR/docgap" ] && service docgap status >/dev/null 2>&1; then
                service docgap stop
                echo "  Stopped: docgap"
            else
                echo "  docgap service not running"
            fi
            ;;
        linux)
            if systemctl is-active docgap >/dev/null 2>&1; then
                systemctl stop docgap
                echo "  Stopped: docgap"
            else
                echo "  docgap service not running"
            fi
            ;;
    esac
}

# --- Cron Management ----------------------------------------------------------

install_cron() {
    _script_dir="$1"
    if [ -f "$_script_dir/cron.d/docgap" ]; then
        mkdir -p "$DOCgap_CRON_DIR"
        cp "$_script_dir/cron.d/docgap" "$DOCgap_CRON_DIR/docgap"
        # Substitute actual paths into the installed cron file
        sed_inplace "s|/usr/local/bin/docgap|$DOCgap_BIN_DIR/docgap|g" "$DOCgap_CRON_DIR/docgap"
        sed_inplace "s|/var/db/docgap|$DOCgap_DATA_DIR|g" "$DOCgap_CRON_DIR/docgap"
        chmod 644 "$DOCgap_CRON_DIR/docgap"
        echo "  Installed: $DOCgap_CRON_DIR/docgap"
    else
        echo "  WARNING: cron entry not found at $_script_dir/cron.d/docgap"
    fi
}

uninstall_cron() {
    if [ -f "$DOCgap_CRON_DIR/docgap" ]; then
        rm "$DOCgap_CRON_DIR/docgap"
        echo "  Removed: $DOCgap_CRON_DIR/docgap"
    fi
}

# --- Initialization -----------------------------------------------------------

# Auto-detect OS and set paths when sourced
detect_os
set_os_paths
