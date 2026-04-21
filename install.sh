#!/usr/bin/env bash
# claude-usage installer — curl -fsSL https://raw.githubusercontent.com/yigitkonur/claude-usage-cli/main/install.sh | bash
set -euo pipefail

REPO="yigitkonur/claude-usage-cli"
DEST="${HOME}/.local/bin/claude-usage"

ARCH=$(uname -m)
case "$ARCH" in
  arm64)   ASSET="claude-usage-macos-arm64" ;;
  x86_64)  ASSET="claude-usage-macos-x86_64" ;;
  *)
    echo "Unsupported architecture: $ARCH"
    echo "Download manually: https://github.com/${REPO}/releases"
    exit 1
    ;;
esac

VERSION="${CLAUDE_USAGE_VERSION:-latest}"
if [ "$VERSION" = "latest" ]; then
  DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"
else
  DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}"
fi

mkdir -p "$(dirname "$DEST")"
echo "Downloading ${ASSET}..."
if ! curl -fsSL "$DOWNLOAD_URL" -o "$DEST" 2>&1; then
  echo "Download failed. Check: https://github.com/${REPO}/releases"
  exit 1
fi
chmod +x "$DEST"
xattr -d com.apple.quarantine "$DEST" 2>/dev/null || true

if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
  SHELL_NAME=$(basename "${SHELL:-/bin/zsh}")
  case "$SHELL_NAME" in
    zsh)  RC="$HOME/.zshrc" ;;
    bash) RC="$HOME/.bashrc" ;;
    *)    RC="$HOME/.profile" ;;
  esac
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
  echo "Added ~/.local/bin to PATH in $RC"
  echo "Restart your shell or run: source $RC"
fi

echo ""
echo "claude-usage installed at $DEST"
echo ""
echo "Next steps:"
echo "  claude-usage setup       # add your first account"
echo "  alias cc='claude-usage'  # optional shortcut"
