# Claude Usage CLI

Track multiple Claude session keys from the terminal or Raycast with one small script.

It validates each session key against Claude's web API, stores labeled accounts locally, refreshes usage on a randomized schedule, and renders a compact one-line summary such as:

```text
1️⃣ M 0% 5h Sun(99%) | 2️⃣ Y 2% 4h Wed(41%) | 3️⃣ C 69% 3h Thu(39%)
```

In that line:

- `M`, `Y`, and `C` come from the first letter of the label you saved for each account.
- The first percent is the 5-hour usage percent.
- The next token is the 5-hour reset countdown.
- The day is the 7-day reset day.
- The percent in parentheses is the 7-day usage percent.

## Install

Quick install:

```bash
curl -fsSL https://raw.githubusercontent.com/yigitkonur/claude-usage-cli/main/install.sh | bash
```

The installer:

- installs `uv` if it is missing
- downloads the script into `~/.local/bin/claude-usage`
- marks it executable

If `~/.local/bin` is not on your `PATH`, add this to your shell config:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## Setup

### 1. Add your first account

```bash
claude-usage setup
```

You will be prompted for:

- a label such as `cihan`, `yigit`, or `mooney`
- a Claude `sessionKey`

The script validates the session key before saving it.

### 2. Add more accounts

You can add more during `setup`, or later with:

```bash
claude-usage add cihan sk-ant-...
claude-usage add yigit sk-ant-...
claude-usage add mooney sk-ant-...
```

### 3. Pick the default account

```bash
claude-usage default yigit
```

### 4. See all saved accounts

```bash
claude-usage list
```

### 5. Check the inline summary

```bash
claude-usage
```

### 6. Get structured JSON

```bash
claude-usage --json
```

### 7. Force a live refresh

```bash
claude-usage --live
claude-usage check --live --json
```

## Background Refresh

The script stores account state in:

```text
~/.config/claude-usage/state.json
```

It can also install a macOS `launchd` agent that wakes every minute, but only refreshes accounts that are due. Each account gets a randomized next refresh time between 1 and 30 minutes.

Install the agent:

```bash
claude-usage agent install
```

Run one agent cycle manually:

```bash
claude-usage agent run-once
```

Remove the agent:

```bash
claude-usage agent uninstall
```

## Commands

```text
claude-usage [preferred-label] [--json] [--live]
claude-usage setup
claude-usage add <label> <session_key>
claude-usage list
claude-usage check [label] [--json] [--live]
claude-usage default <label>
claude-usage remove <label>
claude-usage refresh-cache [label ...] [--all] [--due-only]
claude-usage agent install|uninstall|run-once
```

## Notes

- Session keys are stored locally in `~/.config/claude-usage/state.json`.
- The script uses Claude's web endpoints for organizations, usage, and overage/account metadata.
- If one account is stale and due for refresh, the default inline run refreshes due accounts before rendering so the line stays accurate.
- Raycast users can drop the script into Script Commands as-is; the metadata header is already included.
