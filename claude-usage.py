#!/usr/bin/env -S uv run --python 3.12 --script
# -*- coding: utf-8 -*-
# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "curl-cffi>=0.14.0",
# ]
# ///

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title CC
# @raycast.mode inline
# @raycast.refreshTime 5m

# Optional parameters:
# @raycast.icon ✦
# @raycast.packageName Claude
# @raycast.argument1 { "type": "text", "placeholder": "Preferred label", "optional": true }

# Documentation:
# @raycast.author Yigit Konur
# @raycast.description Manages multiple Claude session keys and shows them inline

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import plistlib
import random
import shutil
import stat
import sys
from pathlib import Path
from typing import Any

from curl_cffi import requests

API_BASE_URL = "https://claude.ai/api"
CONFIG_DIR = Path.home() / ".config" / "claude-usage"
STATE_PATH = CONFIG_DIR / "state.json"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCH_AGENT_LABEL = "io.github.claude-usage.cli"
LAUNCH_AGENT_PATH = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

WEEKLY_SHOW_MIN = 50.0
MAX_INLINE_LENGTH = 140
INLINE_SEPARATOR = "  "
RANDOM_REFRESH_MINUTES = (1, 30)
DEFAULT_TIMEOUT_SECONDS = 20


class ScriptError(RuntimeError):
    """Formatted error for CLI and Raycast output."""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def program_name() -> str:
    return Path(sys.argv[0]).name or "claude-usage"


def parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def format_relative_reset(value: str | None) -> str | None:
    reset_at = parse_datetime(value)
    if not reset_at:
        return None
    seconds = max(int((reset_at - utc_now()).total_seconds()), 0)
    minutes = (seconds + 59) // 60
    if minutes <= 1:
        return "1m"
    if minutes < 60:
        return f"{minutes}m"
    rounded_hours = max(1, round(minutes / 60))
    return f"{rounded_hours}h"


def build_headers(session_key: str) -> dict[str, str]:
    return {
        "accept": "*/*",
        "accept-language": "en-US,en;q=0.9",
        "anthropic-client-platform": "web_claude_ai",
        "anthropic-client-version": "1.0.0",
        "content-type": "application/json",
        "cookie": f"sessionKey={session_key}",
        "origin": "https://claude.ai",
        "referer": "https://claude.ai/settings/usage",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": USER_AGENT,
    }


def build_session(session_key: str) -> requests.Session:
    session = requests.Session(impersonate="chrome131")
    session.headers.update(build_headers(session_key))
    return session


def parse_json_response(response: requests.Response, url: str) -> Any:
    text = response.text
    if "<!DOCTYPE html>" in text or "<html" in text:
        raise ScriptError(f"Cloudflare or HTML response received from {url}")
    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover - library-specific JSON errors
        raise ScriptError(f"Invalid JSON from {url}: {exc}") from exc
    if response.status_code >= 400:
        message = (
            payload.get("error", {}).get("message")
            if isinstance(payload, dict)
            else None
        ) or (payload.get("message") if isinstance(payload, dict) else None)
        raise ScriptError(message or f"HTTP {response.status_code} from {url}")
    return payload


def get_json(session: requests.Session, url: str) -> Any:
    try:
        response = session.get(url, timeout=DEFAULT_TIMEOUT_SECONDS)
    except Exception as exc:
        raise ScriptError(f"Network error calling {url}: {exc}") from exc
    return parse_json_response(response, url)


def read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"default_label": None, "accounts": []}
    with STATE_PATH.open("r", encoding="utf-8") as handle:
        state = json.load(handle)
    if "accounts" not in state or not isinstance(state["accounts"], list):
        raise ScriptError(f"Invalid state file: {STATE_PATH}")
    state.setdefault("default_label", None)
    return state


def write_state(state: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = STATE_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
    temp_path.replace(STATE_PATH)
    try:
        os.chmod(STATE_PATH, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def make_next_refresh_at() -> str:
    delay_minutes = random.randint(*RANDOM_REFRESH_MINUTES)
    return (utc_now() + dt.timedelta(minutes=delay_minutes)).isoformat()


def normalize_limit(limit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not limit or limit.get("utilization") is None:
        return None
    resets_at = limit.get("resets_at")
    if float(limit["utilization"]) == 0 and not resets_at:
        return None
    return {
        "percent": float(limit["utilization"]),
        "resets_at": resets_at,
        "reset_in": format_relative_reset(resets_at),
    }


def weekly_candidates(cache: dict[str, Any]) -> list[float]:
    candidates = []
    for key in ("seven_day", "seven_day_opus", "seven_day_sonnet"):
        limit = cache.get(key)
        if limit and limit.get("percent") is not None:
            candidates.append(float(limit["percent"]))
    return candidates


def weekly_value(cache: dict[str, Any]) -> float | None:
    seven_day = cache.get("seven_day")
    if seven_day and seven_day.get("percent") is not None:
        return float(seven_day["percent"])
    candidates = weekly_candidates(cache)
    return max(candidates) if candidates else None


def weekly_reset_day(cache: dict[str, Any]) -> str | None:
    seven_day = cache.get("seven_day")
    if not seven_day:
        return None
    resets_at = parse_datetime(seven_day.get("resets_at"))
    if not resets_at:
        return None
    return resets_at.astimezone().strftime("%a")


def score_account(account: dict[str, Any]) -> tuple[float, float, float]:
    cache = account.get("cache") or {}
    five_hour = cache.get("five_hour") or {}
    five_hour_percent = float(five_hour.get("percent", 999.0))
    weekly_percent = weekly_value(cache)
    weekly_sort = weekly_percent if weekly_percent is not None else 999.0
    reset_at = parse_datetime(five_hour.get("resets_at"))
    reset_sort = reset_at.timestamp() if reset_at else float("inf")
    return (weekly_sort, five_hour_percent, reset_sort)


def sort_accounts_for_list(accounts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def sort_key(account: dict[str, Any]) -> tuple[float, float, str]:
        cache = account.get("cache") or {}
        five_hour = cache.get("five_hour") or {}
        five_hour_percent = float(five_hour.get("percent", 999.0))
        weekly_percent = weekly_value(cache)
        weekly_sort = weekly_percent if weekly_percent is not None else 999.0
        return (five_hour_percent, weekly_sort, account["label"].lower())

    return sorted(accounts, key=sort_key)


def account_exists(state: dict[str, Any], label: str) -> dict[str, Any] | None:
    for account in state["accounts"]:
        if account["label"] == label:
            return account
    return None


def fetch_account_snapshot(session_key: str, existing_org_uuid: str | None = None) -> dict[str, Any]:
    session = build_session(session_key)
    organizations = get_json(session, f"{API_BASE_URL}/organizations")
    if not isinstance(organizations, list) or not organizations:
        raise ScriptError("No organizations returned for this session key")

    organization = None
    if existing_org_uuid:
        for candidate in organizations:
            if candidate.get("uuid") == existing_org_uuid:
                organization = candidate
                break
    if organization is None:
        organization = organizations[0]

    org_uuid = organization.get("uuid") or organization.get("id")
    if not org_uuid:
        raise ScriptError("Organization UUID not found")

    usage = get_json(session, f"{API_BASE_URL}/organizations/{org_uuid}/usage")
    overage: dict[str, Any] | None = None
    overage_error = None
    try:
        overage = get_json(session, f"{API_BASE_URL}/organizations/{org_uuid}/overage_spend_limit")
    except ScriptError as exc:
        overage_error = str(exc)

    cache = {
        "five_hour": normalize_limit(usage.get("five_hour")),
        "seven_day": normalize_limit(usage.get("seven_day")),
        "seven_day_opus": normalize_limit(usage.get("seven_day_opus")),
        "seven_day_sonnet": normalize_limit(usage.get("seven_day_sonnet")),
        "fetched_at": iso_now(),
    }

    return {
        "organization_uuid": org_uuid,
        "organization_name": organization.get("name") or "Unknown Organization",
        "organization_capabilities": organization.get("capabilities") or [],
        "cache": cache,
        "account_details": {
            "uuid": overage.get("account_uuid") if overage else None,
            "email": overage.get("account_email") if overage else None,
            "name": overage.get("account_name") if overage else None,
            "seat_tier": overage.get("seat_tier") if overage else None,
            "service_name": overage.get("org_service_name") if overage else None,
        },
        "billing": {
            "enabled": overage.get("is_enabled") if overage else None,
            "currency": overage.get("currency") if overage else None,
            "limit_type": overage.get("limit_type") if overage else None,
            "monthly_credit_limit": overage.get("monthly_credit_limit") if overage else None,
            "used_credits": overage.get("used_credits") if overage else None,
        },
        "overage_error": overage_error,
    }


def refresh_account(account: dict[str, Any]) -> dict[str, Any]:
    snapshot = fetch_account_snapshot(account["session_key"], account.get("organization_uuid"))
    account["organization_uuid"] = snapshot["organization_uuid"]
    account["organization_name"] = snapshot["organization_name"]
    account["organization_capabilities"] = snapshot["organization_capabilities"]
    account["account_details"] = snapshot["account_details"]
    account["billing"] = snapshot["billing"]
    account["cache"] = snapshot["cache"]
    account["last_validated_at"] = iso_now()
    account["last_error"] = None
    account["next_refresh_at"] = make_next_refresh_at()
    if snapshot["overage_error"]:
        account["last_error"] = snapshot["overage_error"]
    return account


def refresh_account_safe(account: dict[str, Any]) -> dict[str, Any]:
    try:
        return refresh_account(account)
    except ScriptError as exc:
        account["last_error"] = str(exc)
        account["next_refresh_at"] = make_next_refresh_at()
        return account


def refresh_accounts(
    state: dict[str, Any],
    labels: list[str] | None = None,
    due_only: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refreshed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    due_reference = utc_now()
    allowed = set(labels or [])

    for account in state["accounts"]:
        if allowed and account["label"] not in allowed:
            skipped.append(account)
            continue
        due_at = parse_datetime(account.get("next_refresh_at"))
        if due_only and due_at and due_at > due_reference:
            skipped.append(account)
            continue
        refreshed.append(refresh_account_safe(account))
    return refreshed, skipped


def refresh_due_accounts_if_needed(state: dict[str, Any]) -> list[dict[str, Any]]:
    refreshed, _ = refresh_accounts(state, labels=None, due_only=True)
    if refreshed:
        write_state(state)
    return refreshed


def ensure_accounts(state: dict[str, Any]) -> None:
    if not state["accounts"]:
        raise ScriptError(f"No accounts saved. Run: {program_name()} setup")


def select_account(
    state: dict[str, Any],
    preferred_label: str | None = None,
) -> tuple[dict[str, Any], str]:
    ensure_accounts(state)
    accounts = state["accounts"]
    if preferred_label:
        preferred = account_exists(state, preferred_label)
        if preferred:
            return preferred, "preferred_label"
    default_label = state.get("default_label")
    if default_label:
        default_account = account_exists(state, default_label)
        if default_account:
            return default_account, "default_label"
    fallback_accounts = [
        account for account in accounts if (account.get("cache") or {}).get("five_hour")
    ]
    if fallback_accounts:
        return min(fallback_accounts, key=score_account), "fallback_best_available"
    return accounts[0], "fallback_first_saved"


def maybe_refresh_selected_account(
    state: dict[str, Any],
    selected: dict[str, Any],
    *,
    force_live: bool = False,
) -> dict[str, Any]:
    due_at = parse_datetime(selected.get("next_refresh_at"))
    should_refresh = force_live or due_at is None or due_at <= utc_now()
    if should_refresh:
        refresh_account_safe(selected)
        write_state(state)
    return selected


def account_summary(account: dict[str, Any]) -> dict[str, Any]:
    cache = account.get("cache") or {}
    return {
        "label": account["label"],
        "organization_name": account.get("organization_name"),
        "healthy": (account.get("cache") or {}).get("five_hour") is not None,
        "five_hour": cache.get("five_hour"),
        "weekly": weekly_value(cache),
        "last_validated_at": account.get("last_validated_at"),
        "next_refresh_at": account.get("next_refresh_at"),
        "last_error": account.get("last_error"),
    }


def compact_account_line(account: dict[str, Any]) -> str:
    cache = account.get("cache") or {}
    five_hour = cache.get("five_hour") or {}
    five_hour_percent = five_hour.get("percent")
    weekly_percent = weekly_value(cache)
    weekly_day = weekly_reset_day(cache)
    if five_hour_percent is None:
        if weekly_percent is not None:
            line = f"{account['label']} 7d {round(float(weekly_percent))}%"
            if weekly_day:
                line += f" {weekly_day}"
            return line if len(line) <= MAX_INLINE_LENGTH else line[: MAX_INLINE_LENGTH - 1] + "…"
        return f"{account['label']} no usage data"
    parts = [
        account["label"],
        f"5h {round(float(five_hour_percent))}%",
    ]
    reset_in = format_relative_reset(five_hour.get("resets_at"))
    if reset_in:
        parts.append(f"↻{reset_in}")
    if weekly_percent is not None and weekly_percent > WEEKLY_SHOW_MIN:
        weekly_piece = f"7d {round(float(weekly_percent))}%"
        if weekly_day:
            weekly_piece += f" {weekly_day}"
        parts.append(weekly_piece)
    line = " ".join(parts)
    return line if len(line) <= MAX_INLINE_LENGTH else line[: MAX_INLINE_LENGTH - 1] + "…"


def short_label(label: str) -> str:
    stripped = label.strip()
    return stripped[:1].upper() if stripped else "?"


def numbered_inline_line(state: dict[str, Any]) -> str:
    ensure_accounts(state)
    emoji_numbers = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    segments: list[str] = []

    for index, account in enumerate(sort_accounts_for_list(state["accounts"])):
        cache = account.get("cache") or {}
        five_hour = cache.get("five_hour") or {}
        five_hour_percent = five_hour.get("percent")
        weekly_percent = weekly_value(cache)
        weekly_day = weekly_reset_day(cache)
        number = emoji_numbers[index] if index < len(emoji_numbers) else f"{index + 1}."
        shown_five_hour_percent = 0 if five_hour_percent is None else round(float(five_hour_percent))
        reset_in = format_relative_reset(five_hour.get("resets_at")) if five_hour_percent is not None else "-"

        segment = f"{number} {short_label(account['label'])} {shown_five_hour_percent}%"
        segment += f" {reset_in or '-'}"
        if weekly_day and weekly_percent is not None:
            segment += f" {weekly_day}({round(float(weekly_percent))}%)"
        elif weekly_day:
            segment += f" {weekly_day}"
        elif weekly_percent is not None:
            segment += f" ({round(float(weekly_percent))}%)"
        segments.append(segment)

    line = " | ".join(segments) if segments else "No usage data"
    return line if len(line) <= MAX_INLINE_LENGTH else line[: MAX_INLINE_LENGTH - 1] + "…"


def render_json(
    state: dict[str, Any],
    selected: dict[str, Any],
    reason: str,
    *,
    source: str,
) -> str:
    payload = {
        "selected": account_summary(selected),
        "selection_reason": reason,
        "source": source,
        "default_label": state.get("default_label"),
        "accounts": [account_summary(account) for account in sort_accounts_for_list(state["accounts"])],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_list(state: dict[str, Any]) -> str:
    ensure_accounts(state)
    lines = []
    for account in sort_accounts_for_list(state["accounts"]):
        prefix = "* " if state.get("default_label") == account["label"] else "  "
        line = compact_account_line(account)
        error = account.get("last_error")
        if error:
            line = f"{line} ! {error}"
        lines.append(prefix + line)
    return "\n".join(lines)


def prompt_nonempty(prompt: str) -> str:
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("Value is required.")


def add_account(state: dict[str, Any], label: str, session_key: str) -> dict[str, Any]:
    if account_exists(state, label):
        raise ScriptError(f"Label already exists: {label}")
    account = {
        "label": label,
        "session_key": session_key,
        "organization_uuid": None,
        "organization_name": None,
        "organization_capabilities": [],
        "account_details": {},
        "billing": {},
        "cache": {},
        "last_validated_at": None,
        "last_error": None,
        "next_refresh_at": None,
    }
    refresh_account(account)
    state["accounts"].append(account)
    if not state.get("default_label"):
        state["default_label"] = label
    write_state(state)
    return account


def remove_account(state: dict[str, Any], label: str) -> None:
    existing = account_exists(state, label)
    if not existing:
        raise ScriptError(f"Label not found: {label}")
    state["accounts"] = [account for account in state["accounts"] if account["label"] != label]
    if state.get("default_label") == label:
        state["default_label"] = state["accounts"][0]["label"] if state["accounts"] else None
    write_state(state)


def set_default_account(state: dict[str, Any], label: str) -> None:
    if not account_exists(state, label):
        raise ScriptError(f"Label not found: {label}")
    state["default_label"] = label
    write_state(state)


def build_launch_agent_plist(script_path: Path, uv_path: str) -> dict[str, Any]:
    log_dir = CONFIG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": [
            uv_path,
            "run",
            "--python",
            "3.12",
            "--script",
            str(script_path),
            "refresh-cache",
            "--all",
            "--due-only",
        ],
        "RunAtLoad": True,
        "StartInterval": 60,
        "StandardOutPath": str(log_dir / "launchd.out.log"),
        "StandardErrorPath": str(log_dir / "launchd.err.log"),
        "WorkingDirectory": str(script_path.parent),
    }


def install_launch_agent() -> str:
    uv_path = shutil.which("uv")
    if not uv_path:
        raise ScriptError("uv is required to install the launch agent")
    script_path = Path(__file__).resolve()
    LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    plist_data = build_launch_agent_plist(script_path, uv_path)
    with LAUNCH_AGENT_PATH.open("wb") as handle:
        plistlib.dump(plist_data, handle)
    return (
        f"LaunchAgent written to {LAUNCH_AGENT_PATH}\n"
        f"Run: launchctl unload {LAUNCH_AGENT_PATH} 2>/dev/null || true\n"
        f"Run: launchctl load {LAUNCH_AGENT_PATH}"
    )


def uninstall_launch_agent() -> str:
    if LAUNCH_AGENT_PATH.exists():
        LAUNCH_AGENT_PATH.unlink()
        return (
            f"Removed {LAUNCH_AGENT_PATH}\n"
            f"Run: launchctl bootout gui/$(id -u) {LAUNCH_AGENT_PATH} 2>/dev/null || true"
        )
    return "LaunchAgent not installed"


def handle_setup(state: dict[str, Any]) -> str:
    print("Interactive Claude account setup. Press Ctrl+C to stop.")
    added: list[str] = []
    while True:
        label = prompt_nonempty("Label: ")
        session_key = prompt_nonempty("Session key: ")
        account = add_account(state, label, session_key)
        added.append(account["label"])
        more = input("Add another account? [y/N] ").strip().lower()
        if more not in {"y", "yes"}:
            break
    return f"Saved accounts: {', '.join(added)}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("rest", nargs="*")
    return parser


def parse_default_mode(argv: list[str]) -> tuple[str | None, bool, bool]:
    preferred_label = None
    json_flag = False
    live_flag = False
    for arg in argv:
        if arg == "--json":
            json_flag = True
        elif arg == "--live":
            live_flag = True
        elif arg.startswith("-"):
            raise ScriptError(f"Unknown option: {arg}")
        elif preferred_label is None:
            preferred_label = arg
        else:
            raise ScriptError("Too many positional arguments")
    return preferred_label, json_flag, live_flag


def run_command(argv: list[str]) -> str:
    state = read_state()
    parser = build_parser()
    args = parser.parse_args(argv[:1] if argv and argv[0] in {
        "setup",
        "add",
        "list",
        "check",
        "default",
        "remove",
        "refresh-cache",
        "agent",
        "help",
        "--help",
        "-h",
    } else [])

    if not argv or args.command is None:
        preferred_label, json_flag, live_flag = parse_default_mode(argv)
        if live_flag:
            refresh_accounts(state, labels=None, due_only=False)
            write_state(state)
        else:
            refresh_due_accounts_if_needed(state)
        selected, reason = select_account(state, preferred_label)
        selected = maybe_refresh_selected_account(state, selected, force_live=live_flag)
        source = "live" if live_flag else "cache_or_live"
        return render_json(state, selected, reason, source=source) if json_flag else numbered_inline_line(state)

    command = args.command
    rest = argv[1:]

    if command in {"help", "--help", "-h"}:
        prog = program_name()
        return (
            "Usage:\n"
            f"  {prog} [preferred-label] [--json] [--live]\n"
            f"  {prog} setup\n"
            f"  {prog} add <label> <session_key>\n"
            f"  {prog} list\n"
            f"  {prog} check [label] [--json] [--live]\n"
            f"  {prog} default <label>\n"
            f"  {prog} remove <label>\n"
            f"  {prog} refresh-cache [label ...] [--all] [--due-only]\n"
            f"  {prog} agent install|uninstall|run-once\n"
        )

    if command == "setup":
        if rest:
            raise ScriptError("setup does not take arguments")
        return handle_setup(state)

    if command == "add":
        if len(rest) != 2:
            raise ScriptError(f"Usage: {program_name()} add <label> <session_key>")
        account = add_account(state, rest[0], rest[1])
        return f"Added {account['label']} ({account['organization_name']})"

    if command == "list":
        if rest:
            raise ScriptError("list does not take arguments")
        return render_list(state)

    if command == "default":
        if len(rest) != 1:
            raise ScriptError(f"Usage: {program_name()} default <label>")
        set_default_account(state, rest[0])
        return f"Default account set to {rest[0]}"

    if command == "remove":
        if len(rest) != 1:
            raise ScriptError(f"Usage: {program_name()} remove <label>")
        remove_account(state, rest[0])
        return f"Removed {rest[0]}"

    if command == "check":
        preferred_label = None
        json_flag = False
        live_flag = False
        for arg in rest:
            if arg == "--json":
                json_flag = True
            elif arg == "--live":
                live_flag = True
            elif arg.startswith("-"):
                raise ScriptError(f"Unknown option: {arg}")
            elif preferred_label is None:
                preferred_label = arg
            else:
                raise ScriptError("Too many positional arguments for check")
        if live_flag:
            refresh_accounts(state, labels=None, due_only=False)
            write_state(state)
        else:
            refresh_due_accounts_if_needed(state)
        selected, reason = select_account(state, preferred_label)
        selected = maybe_refresh_selected_account(state, selected, force_live=live_flag)
        return render_json(state, selected, reason, source="live" if live_flag else "cache_or_live") if json_flag else numbered_inline_line(state)

    if command == "refresh-cache":
        labels: list[str] = []
        all_flag = False
        due_only = False
        for arg in rest:
            if arg == "--all":
                all_flag = True
            elif arg == "--due-only":
                due_only = True
            elif arg.startswith("-"):
                raise ScriptError(f"Unknown option: {arg}")
            else:
                labels.append(arg)
        ensure_accounts(state)
        if not all_flag and not labels:
            selected, _ = select_account(state)
            labels = [selected["label"]]
        refreshed, skipped = refresh_accounts(state, labels=None if all_flag else labels, due_only=due_only)
        write_state(state)
        refreshed_labels = ", ".join(account["label"] for account in refreshed) if refreshed else "none"
        skipped_labels = ", ".join(account["label"] for account in skipped) if skipped else "none"
        return f"Refreshed: {refreshed_labels}{INLINE_SEPARATOR}Skipped: {skipped_labels}"

    if command == "agent":
        if len(rest) != 1 or rest[0] not in {"install", "uninstall", "run-once"}:
            raise ScriptError(f"Usage: {program_name()} agent install|uninstall|run-once")
        action = rest[0]
        if action == "install":
            return install_launch_agent()
        if action == "uninstall":
            return uninstall_launch_agent()
        refreshed, skipped = refresh_accounts(state, labels=None, due_only=True)
        write_state(state)
        refreshed_labels = ", ".join(account["label"] for account in refreshed) if refreshed else "none"
        skipped_labels = ", ".join(account["label"] for account in skipped) if skipped else "none"
        return f"Agent run complete{INLINE_SEPARATOR}Refreshed: {refreshed_labels}{INLINE_SEPARATOR}Skipped: {skipped_labels}"

    raise ScriptError(f"Unknown command: {command}")


def main() -> None:
    try:
        output = run_command(sys.argv[1:])
        print(output)
    except KeyboardInterrupt:
        print("Cancelled")
        raise SystemExit(1)
    except ScriptError as exc:
        print(str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
