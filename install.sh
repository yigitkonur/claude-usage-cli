#!/usr/bin/env bash
set -euo pipefail

REPO_OWNER="${REPO_OWNER:-yigitkonur}"
REPO_NAME="${REPO_NAME:-claude-usage-cli}"
REPO_BRANCH="${REPO_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-$HOME/.local/bin}"
SCRIPT_NAME="${SCRIPT_NAME:-claude-usage}"
RAW_BASE="${RAW_BASE:-https://raw.githubusercontent.com/$REPO_OWNER/$REPO_NAME/$REPO_BRANCH}"
SCRIPT_SOURCE="${SCRIPT_SOURCE:-$RAW_BASE/claude-usage.py}"

need_cmd() {
  command -v "$1" >/dev/null 2>&1
}

install_uv() {
  if need_cmd uv; then
    return
  fi

  echo "uv not found. Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"

  if ! need_cmd uv; then
    echo "uv installation finished but uv is still not on PATH." >&2
    echo "Add ~/.local/bin to PATH and rerun the installer." >&2
    exit 1
  fi
}

main() {
  if ! need_cmd curl; then
    echo "curl is required." >&2
    exit 1
  fi

  install_uv

  mkdir -p "$INSTALL_DIR"
  curl -fsSL "$SCRIPT_SOURCE" -o "$INSTALL_DIR/$SCRIPT_NAME"
  chmod +x "$INSTALL_DIR/$SCRIPT_NAME"

  echo
  echo "Installed $SCRIPT_NAME to $INSTALL_DIR/$SCRIPT_NAME"
  echo
  echo "Next steps:"
  echo "  1. Make sure $INSTALL_DIR is on your PATH"
  echo "  2. Run: $SCRIPT_NAME setup"
  echo "  3. Optional background refresh: $SCRIPT_NAME agent install"
}

main "$@"
