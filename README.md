# claude-usage

Monitor your Claude.ai token limits across multiple accounts — one focused line in Raycast, one command for a full HTML dashboard.

```
🟢A 0% 6d23h · 🟠S 80% 2d14h · 🟠Y 92% 2d10h · 🔴C 100% 2d10h
```

In terminal (colored dot bars, exits immediately):

```
  claude usage  ·  4 accounts  ·  best: john
  ────────────────────────────────────────────────────────────────

  JOHN          ★  7d  ●○○○○○○○○○    0%  (in 6d22h)
                   5h  ●○○○○○○○○○    1%  (in 3h56m)

  COMPANY          7d  ████████○○   80%  (in 2d13h)
                   5h  ●●○○○○○○○○    3%  (in 3h56m)

  STUDENT          ◉  7d  █████████○   92%  (in 2d09h)
                   5h  ●○○○○○○○○○    1%  (in 3h56m)

  MY WIFE           7d  ██████████  100%  (in 2d09h)
                   5h  no data
  ────────────────────────────────────────────────────────────────
```

| Status | Meaning |
|--------|---------|
| 🟢 | < 50% used |
| 🟡 | 50–79% |
| 🟠 | 80–99% |
| 🔴 | 100% — limit reached |
| ⚫ | Auth error — session key expired |

---

## Install

### Quick install (macOS — recommended)

Downloads a prebuilt binary, no dependencies required:

```bash
curl -fsSL https://raw.githubusercontent.com/yigitkonur/claude-usage-cli/main/install.sh | bash
```

Then add your first account:

```bash
claude-usage setup
```

Optional alias:

```bash
alias cc='claude-usage'   # add to ~/.zshrc or ~/.bashrc
```

### Alternative: npx (interactive, also sets up Raycast)

Requires Node.js 18+. Walks through Raycast folder detection, account setup, and LaunchAgent install.

```bash
npx github:yigitkonur/claude-usage-cli
```

---

## Raycast

### Binary install

Copy `assets/raycast-cc.sh` from this repo to your Raycast scripts folder and make it executable:

```bash
cp raycast-cc.sh ~/scripts/cc.sh
chmod +x ~/scripts/cc.sh
```

Then in Raycast: **Settings → Extensions → Script Commands** → reload.

### uv --script install (legacy)

If you used the npx installer, `claude-usage.py` is already in your Raycast scripts folder. Search **"CC"** in Raycast.

---

## Getting your session key

Your session key authenticates the tool as you. It lives in your browser's cookie storage.

### Chrome / Arc / Brave

1. Open **[claude.ai](https://claude.ai)** and sign in to the account you want to add.
2. Open DevTools: **`⌘ + Option + I`**
3. **Application** tab → **Storage → Cookies → https://claude.ai**
4. Find `sessionKey` → double-click the Value cell → copy the full string.
   It starts with `sk-ant-sid02-` and is 100+ characters.

> **Tip:** Use `⌘A` then `⌘C` inside the value cell to select the full token.

### Safari

1. **Safari → Settings → Advanced → Show features for web developers**
2. Open claude.ai → **Develop → Show Web Inspector**
3. **Storage** tab → **Cookies** → `claude.ai` → find `sessionKey`

### Firefox

1. Open claude.ai → `F12` → **Storage** tab → **Cookies** → `https://claude.ai` → find `sessionKey`

---

## Commands

```bash
claude-usage                           # Show status (TTY: colored bars; Raycast: compact line)
claude-usage status                    # Same as above
claude-usage status --plain            # Force compact line even in TTY (for piping)
claude-usage html                      # Generate + open HTML dashboard
claude-usage html --no-open            # Generate without opening
claude-usage add <label> <key>         # Add account
claude-usage remove <label>            # Remove account
claude-usage list                      # List all accounts
claude-usage check [label] [--json]    # Check one account
claude-usage default <label>           # Set default account
claude-usage refresh-cache [--all]     # Refresh usage cache
claude-usage update                    # Self-update binary
claude-usage agent install             # Install background auto-refresh
claude-usage agent uninstall           # Remove background agent
claude-usage --version                 # Print version
```

### Flags available on `claude-usage` and `status`

| Flag | Effect |
|------|--------|
| `--live` | Force-refresh all accounts before displaying |
| `--plain` | Compact emoji line instead of colored dot bars |
| `--json` | JSON output (all accounts + selection reason) |

---

## Non-interactive / scripting

All commands that read data are non-interactive and safe to pipe:

```bash
# Plain status line
claude-usage --plain

# JSON — pipe anywhere
claude-usage --json | jq '.accounts[].label'

# HTML report without opening
claude-usage html --no-open

# Force refresh all, then print JSON
claude-usage --live --json

# Check if any account is at 100%
claude-usage --json | jq '.accounts[] | select(.weekly >= 100) | .label'
```

---

## Updating

```bash
claude-usage update          # self-update (binary install)
# or
npx github:yigitkonur/claude-usage-cli update   # update the uv --script version
```

---

## When a session key expires

If an account shows `⚫ ! Invalid authorization`:

```bash
claude-usage remove <label>
claude-usage add <label> <new-session-key>
```

Session keys stay valid until you manually sign out of claude.ai or Anthropic rotates them.

---

## HTML dashboard

Shows all accounts in a dense table: 5-hour window, 7-day window, Opus/Sonnet breakdowns, and reset countdowns.

```bash
claude-usage html           # generate and open
claude-usage html --no-open # generate only → ~/.config/claude-usage/report.html
```

---

## Background auto-refresh

Installs a macOS LaunchAgent that wakes every 60 s and refreshes accounts that are due (1–30 min jitter):

```bash
claude-usage agent install
claude-usage agent uninstall
```

Logs: `~/.config/claude-usage/launchd.out.log` and `launchd.err.log`

---

## Uninstall

```bash
# Remove binary
rm ~/.local/bin/claude-usage

# Remove background agent
claude-usage agent uninstall
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.yigitkonur.claude-usage.plist 2>/dev/null || true

# Remove all config and cached data
rm -rf ~/.config/claude-usage
```

If you used the uv --script install, also delete the script:

```bash
rm ~/scripts/claude-usage.py   # or wherever you installed it
```

---

## Troubleshooting

**"cannot be opened because the developer cannot be verified"**
The binary is not notarized yet. The installer handles this with `xattr -d com.apple.quarantine`. If you downloaded manually:
```bash
xattr -d com.apple.quarantine ~/.local/bin/claude-usage
```

**Raycast script shows nothing / old data**
- Confirm the script is executable: `chmod +x ~/scripts/cc.sh` (or `claude-usage.py`)
- Trigger a manual refresh: `claude-usage refresh-cache --all`
- Check logs: `cat ~/.config/claude-usage/launchd.err.log`

**`command not found: claude-usage`**
`~/.local/bin` is not in your PATH. Add to your shell rc:
```bash
export PATH="$HOME/.local/bin:$PATH"
```

**`uv: command not found`** (uv --script install only)
Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`

---

## Configuration

| Path | Contents |
|------|----------|
| `~/.config/claude-usage/state.json` | Accounts, session keys, usage cache |
| `~/.config/claude-usage/report.html` | Last-generated HTML dashboard |
| `~/.config/claude-usage/launchd.out.log` | Background agent stdout |
| `~/.config/claude-usage/launchd.err.log` | Background agent stderr |
| `~/Library/LaunchAgents/com.yigitkonur.claude-usage.plist` | Background agent definition |

`state.json` and `report.html` are both created with mode `0600` (owner-read-write only). They contain your session keys — keep them private.

---

## How it works

On every run, the script calls three Claude.ai web endpoints authenticated with your session key:

| Endpoint | What it returns |
|----------|----------------|
| `GET /api/organizations` | Org UUID |
| `GET /api/organizations/{uuid}/usage` | 5-hour and 7-day utilization + reset timestamps |
| `GET /api/organizations/{uuid}/overage_spend_limit` | Seat tier, billing info |

Results are cached in `state.json` with a jitter-based refresh schedule (1–30 min) to avoid hammering the API. The LaunchAgent wakes every 60 s but only refreshes accounts that are due.

The script uses `curl_cffi` with Chrome TLS fingerprint impersonation to avoid Cloudflare blocks on the API.

---

## Privacy

- No data leaves your machine except the Claude.ai API calls your browser already makes.
- Session keys are stored locally at `~/.config/claude-usage/state.json` with `0600` permissions.
- The HTML dashboard (`report.html`) is also `0600` — labels are shown instead of email addresses.
- No analytics, no telemetry, no external services.

---

## Requirements

| Item | Notes |
|------|-------|
| macOS 13+ | LaunchAgent and `open` commands |
| Binary install | No other dependencies |
| uv --script install | Requires [uv](https://docs.astral.sh/uv/) + Python 3.12 |
| npx installer | Requires Node.js 18+ |

---

## License

MIT
