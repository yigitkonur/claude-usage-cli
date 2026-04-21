#!/usr/bin/env bash
# claude-usage installer — downloads the prebuilt binary for your Mac
# Usage: curl -fsSL https://raw.githubusercontent.com/yigitkonur/claude-usage-cli/main/install.sh | bash
set -euo pipefail

REPO="yigitkonur/claude-usage-cli"
DEST="${HOME}/.local/bin/claude-usage"

# ── Architecture detection ─────────────────────────────────────────────────────
ARCH=$(uname -m)
case "$ARCH" in
  arm64)   ASSET="claude-usage-macos-arm64"  ;;
  x86_64)  ASSET="claude-usage-macos-x86_64" ;;
  *)
    echo "Unsupported architecture: $ARCH"
    echo "Download manually from https://github.com/${REPO}/releases"
    exit 1
    ;;
esac

# ── Version selection ──────────────────────────────────────────────────────────
VERSION="${CLAUDE_USAGE_VERSION:-latest}"
if [ "$VERSION" = "latest" ]; then
  DOWNLOAD_URL="https://github.com/${REPO}/releases/latest/download/${ASSET}"
else
  DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${ASSET}"
fi

# ── Download ───────────────────────────────────────────────────────────────────
mkdir -p "$(dirname "$DEST")"
echo "Downloading claude-usage ($ARCH)…"
if ! curl -fsSL "$DOWNLOAD_URL" -o "$DEST"; then
  echo "Download failed. Check your internet connection or visit:"
  echo "  https://github.com/${REPO}/releases"
  exit 1
fi
chmod +x "$DEST"

# ── Gatekeeper: remove quarantine attribute set by browser/curl downloads ─────
xattr -d com.apple.quarantine "$DEST" 2>/dev/null || true

# ── PATH setup ────────────────────────────────────────────────────────────────
if [[ ":${PATH}:" != *":${HOME}/.local/bin:"* ]]; then
  SHELL_NAME=$(basename "${SHELL:-/bin/zsh}")
  case "$SHELL_NAME" in
    zsh)  RC="$HOME/.zshrc"  ;;
    bash) RC="$HOME/.bashrc" ;;
    *)    RC="$HOME/.profile" ;;
  esac
  printf '\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$RC"
  echo "  Added ~/.local/bin to PATH in $RC"
  echo "  Restart your shell or run:  source $RC"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo "  ✓ claude-usage installed to $DEST"
echo ""
echo "  Next steps:"
echo "    claude-usage setup          # add your first account"
echo "    alias cc='claude-usage'     # optional shortcut"
echo ""
echo "  For Raycast, copy assets/raycast-cc.sh to your Raycast scripts folder."
echo "  Or use the interactive installer: npx github:yigitkonur/claude-usage-cli"
