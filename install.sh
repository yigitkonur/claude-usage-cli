#!/usr/bin/env bash
set -euo pipefail
ARCH=$(uname -m)
case "$ARCH" in
  arm64|x86_64) ;;
  *) echo "Unsupported: $ARCH"; exit 1 ;;
esac
DEST="${HOME}/.local/bin/claude-usage"
mkdir -p "$(dirname "$DEST")"
echo "Downloading claude-usage ($ARCH)..."
curl -fsSL "https://github.com/yigitkonur/claude-usage-cli/releases/latest/download/claude-usage-macos-${ARCH}" -o "$DEST"
chmod +x "$DEST"
xattr -d com.apple.quarantine "$DEST" 2>/dev/null || true
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
  RC="${HOME}/.zshrc"; [ -n "${BASH_VERSION-}" ] && RC="${HOME}/.bashrc"
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
  echo "Added ~/.local/bin to PATH in $RC — restart shell or: source $RC"
fi
echo "Installed. Run: claude-usage setup"
