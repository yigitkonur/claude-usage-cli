#!/usr/bin/env bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title CC
# @raycast.mode inline
# @raycast.refreshTime 5m

# Optional parameters:
# @raycast.icon ✦
# @raycast.packageName Claude
# @raycast.description Claude usage across accounts

# Supports both binary install (~/.local/bin) and uv --script install (~/scripts)
if [ -x "$HOME/.local/bin/claude-usage" ]; then
  exec "$HOME/.local/bin/claude-usage" 2>&1
elif [ -x "$HOME/scripts/claude-usage.py" ]; then
  exec uv run --python 3.12 --script "$HOME/scripts/claude-usage.py" 2>&1
else
  echo "⚫ claude-usage not found — run installer"
fi
