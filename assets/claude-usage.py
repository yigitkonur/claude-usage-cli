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
# @raycast.description Manages Claude session keys and shows the healthiest account inline

from __future__ import annotations

import argparse
import datetime as dt
import html as _html
import json
import os
import platform
import plistlib
import random
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from curl_cffi import requests

__version__ = "2.0.0"
GITHUB_REPO = "yigitkonur/claude-usage-cli"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"

API_BASE_URL = "https://claude.ai/api"
CONFIG_DIR = Path.home() / ".config" / "claude-usage"
STATE_PATH = CONFIG_DIR / "state.json"
LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"
LAUNCH_AGENT_LABEL = "com.yigitkonur.claude-usage"
LAUNCH_AGENT_PATH = LAUNCH_AGENTS_DIR / f"{LAUNCH_AGENT_LABEL}.plist"
REPORT_PATH = CONFIG_DIR / "report.html"
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
    if seconds <= 60:
        return "now"
    total_minutes = (seconds + 59) // 60
    if total_minutes < 60:
        return f"{total_minutes}m"
    hours = total_minutes // 60
    remaining_minutes = total_minutes % 60
    if hours < 24:
        if remaining_minutes > 0:
            return f"{hours}h{remaining_minutes:02d}m"
        return f"{hours}h"
    days = hours // 24
    remaining_hours = hours % 24
    if remaining_hours > 0:
        return f"{days}d{remaining_hours}h"
    return f"{days}d"


def format_absolute_reset_time(value: str | None) -> str | None:
    reset_at = parse_datetime(value)
    if not reset_at:
        return None
    local_time = reset_at.astimezone()
    hour = int(local_time.strftime("%I"))
    minute = local_time.strftime("%M")
    ampm = local_time.strftime("%p").lower()
    return f"{hour}:{minute}{ampm}"


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


def _do_refresh(state: dict[str, Any], *, live: bool) -> None:
    if live:
        refresh_accounts(state, labels=None, due_only=False)
        write_state(state)
    else:
        refresh_due_accounts_if_needed(state)


def ensure_accounts(state: dict[str, Any]) -> None:
    if not state["accounts"]:
        raise ScriptError("No accounts saved. Run: claude-usage.py setup")


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
    reset_time = format_absolute_reset_time(five_hour.get("resets_at"))
    reset_in = format_relative_reset(five_hour.get("resets_at"))
    if reset_time and reset_in:
        parts.append(f"↻{reset_time} (in {reset_in})")
    elif reset_in:
        parts.append(f"↻{reset_in}")
    if weekly_percent is not None and weekly_percent > WEEKLY_SHOW_MIN:
        weekly_piece = f"7d {round(float(weekly_percent))}%"
        if weekly_day:
            weekly_piece += f" {weekly_day}"
        w_countdown = format_relative_reset((cache.get("seven_day") or {}).get("resets_at"))
        if w_countdown:
            weekly_piece += f" (in {w_countdown})"
        parts.append(weekly_piece)
    line = " ".join(parts)
    return line if len(line) <= MAX_INLINE_LENGTH else line[: MAX_INLINE_LENGTH - 1] + "…"


def short_label(label: str) -> str:
    stripped = label.strip()
    return stripped[:1].upper() if stripped else "?"


def severity_class(percent: float | None) -> str:
    if percent is None:
        return "unknown"
    if percent >= 100:
        return "max"
    if percent >= 80:
        return "critical"
    if percent >= 50:
        return "warning"
    return "healthy"


def severity_dot(percent: float | None, error: str | None) -> str:
    if error:
        return "⚫"
    if percent is None:
        return "⚪"
    if percent >= 100:
        return "🔴"
    if percent >= 80:
        return "🟠"
    if percent >= 50:
        return "🟡"
    return "🟢"


def numbered_inline_line(state: dict[str, Any]) -> str:
    ensure_accounts(state)

    def sort_key(account: dict[str, Any]) -> tuple[float, str]:
        cache = account.get("cache") or {}
        weekly = weekly_value(cache)
        return (weekly if weekly is not None else 999.0, account["label"].lower())

    segments: list[str] = []
    for account in sorted(state["accounts"], key=sort_key):
        cache = account.get("cache") or {}
        label = short_label(account["label"])
        weekly = weekly_value(cache)
        error = account.get("last_error")
        dot = severity_dot(weekly, error)

        if weekly is None:
            if error:
                segments.append(f"{dot}{label} !")
                continue
            five_hour = cache.get("five_hour") or {}
            fh_percent = five_hour.get("percent")
            if fh_percent is not None:
                segments.append(f"{dot}{label} 5h {round(float(fh_percent))}%")
            else:
                segments.append(f"{dot}{label} —")
            continue

        piece = f"{dot}{label} {round(float(weekly))}%"
        reset_in = format_relative_reset((cache.get("seven_day") or {}).get("resets_at"))
        if reset_in:
            piece += f" {reset_in}"
        segments.append(piece)

    line = " · ".join(segments) if segments else "No usage data"
    return line if len(line) <= MAX_INLINE_LENGTH else line[: MAX_INLINE_LENGTH - 1] + "…"


# ── CLI rich display ───────────────────────────────────────────────────────────

_R = "\x1b[0m"
_B = "\x1b[1m"
_DIM = "\x1b[2m"
_CY = "\x1b[36m"
_GN = "\x1b[32m"
_YL = "\x1b[33m"
_OR = "\x1b[38;5;208m"
_RD = "\x1b[31m"

_BAR_LEN = 10


def _ansi_pct_color(percent: float | None) -> str:
    if percent is None or percent < 50:
        return _GN
    if percent < 80:
        return _YL
    if percent < 100:
        return _OR
    return _RD


def _dot_bar(percent: float | None) -> str:
    if percent is None:
        return _DIM + ("○" * _BAR_LEN) + _R
    c = _ansi_pct_color(percent)
    filled = max(0, min(_BAR_LEN, round(percent / 100 * _BAR_LEN)))
    empty = _BAR_LEN - filled
    return c + "●" * filled + _DIM + "○" * empty + _R


def render_cli_status(state: dict[str, Any]) -> str:
    ensure_accounts(state)

    def sort_key(a: dict[str, Any]) -> tuple[int, float, str]:
        cache = a.get("cache") or {}
        wk = weekly_value(cache)
        return (1 if a.get("last_error") else 0, wk if wk is not None else 999.0, a["label"].lower())

    ordered = sorted(state["accounts"], key=sort_key)
    best = next(
        (a for a in ordered if not a.get("last_error") and (weekly_value(a.get("cache") or {}) or 0) < 100),
        None,
    )
    best_label = best["label"] if best else None
    default_label = state.get("default_label")
    n = len(ordered)

    hr = _DIM + "─" * 52 + _R
    header_best = (
        f"best: {_B}{_CY}{best_label}{_R}" if best_label else f"{_RD}all maxed{_R}"
    )

    LABEL_W = 12

    lines: list[str] = [
        "",
        f"  {_B}claude usage{_R}  {_DIM}·{_R}  {n} account{'s' if n != 1 else ''}  {_DIM}·{_R}  {header_best}",
        f"  {hr}",
        "",
    ]

    for acc in ordered:
        label_upper = acc["label"].upper()
        cache = acc.get("cache") or {}
        last_err = acc.get("last_error")
        weekly = weekly_value(cache)
        seven = cache.get("seven_day") or {}
        five = cache.get("five_hour") or {}

        if last_err:
            marker = f" {_RD}✗{_R} "
        elif acc["label"] == best_label:
            marker = f" {_YL}★{_R} "
        elif acc["label"] == default_label:
            marker = f" {_DIM}◉{_R} "
        else:
            marker = "   "

        label_str = f"  {_B}{_CY}{label_upper:<{LABEL_W}}{_R}{marker}"
        indent = " " * (2 + LABEL_W + 3)

        if last_err:
            lines.append(f"{label_str}{_RD}{last_err[:50]}{_R}")
            lines.append("")
            continue

        wk_pct_str = f"{round(weekly):>3}%" if weekly is not None else "  —"
        wk_color = _ansi_pct_color(weekly)
        wk_reset = format_relative_reset(seven.get("resets_at"))
        wk_reset_str = f"  {_DIM}(in {wk_reset}){_R}" if wk_reset else ""
        lines.append(
            f"{label_str}7d  {_dot_bar(weekly)}  {_B}{wk_color}{wk_pct_str}{_R}{wk_reset_str}"
        )

        fh_pct = float(five["percent"]) if five.get("percent") is not None else None
        if fh_pct is not None:
            fh_pct_str = f"{round(fh_pct):>3}%"
            fh_color = _ansi_pct_color(fh_pct)
            fh_reset = format_relative_reset(five.get("resets_at"))
            fh_reset_str = f"  {_DIM}(in {fh_reset}){_R}" if fh_reset else ""
            lines.append(
                f"{indent}5h  {_dot_bar(fh_pct)}  {_B}{fh_color}{fh_pct_str}{_R}{fh_reset_str}"
            )
        else:
            lines.append(f"{indent}5h  {_DIM}no data{_R}")

        lines.append("")

    lines.append(f"  {hr}")
    lines.append(f"  {_DIM}Press ↵ Enter to open dashboard  ·  Ctrl+C to exit{_R}")
    lines.append("")
    return "\n".join(lines)


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


HTML_REPORT_CSS = """
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --parchment: #f5f4ed;
  --ivory: #faf9f5;
  --warm-sand: #e8e6dc;
  --border-cream: #f0eee6;
  --ring-warm: #d1cfc5;
  --near-black: #141413;
  --charcoal: #4d4c48;
  --olive: #5e5d59;
  --stone: #87867f;
  --warm-silver: #b0aea5;
  --terracotta: #c96442;
  --coral: #d97757;
  --crimson: #b53333;
  --tint-best: rgba(201, 100, 66, 0.05);
  --tint-best-hover: rgba(201, 100, 66, 0.08);
}

html, body { background: var(--parchment); color: var(--near-black); height: 100%; }

body {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.45;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.serif, .hero-title, .org-name, .pct, .hero-best-value, .wordmark {
  font-family: "Fraunces", Georgia, "Times New Roman", serif;
  font-weight: 500;
  font-variation-settings: "opsz" 48;
  letter-spacing: -0.01em;
}

.topnav {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 40px;
  border-bottom: 1px solid var(--border-cream);
  background: var(--parchment);
  flex-shrink: 0;
}

.wordmark {
  font-size: 17px;
  color: var(--near-black);
  display: flex;
  align-items: center;
  gap: 10px;
}

.wordmark::before {
  content: "✦";
  color: var(--terracotta);
  font-size: 15px;
}

.refreshed {
  font-size: 11px;
  color: var(--stone);
  letter-spacing: 0.1em;
  text-transform: uppercase;
  font-weight: 500;
}

.container {
  max-width: 1280px;
  width: 100%;
  margin: 0 auto;
  padding: 24px 40px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  flex: 1;
}

.hero {
  display: grid;
  grid-template-columns: 2.2fr 1fr 1fr;
  gap: 24px;
  align-items: stretch;
}

.hero-cell {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 18px 22px;
  background: var(--ivory);
  border: 1px solid var(--border-cream);
  border-radius: 12px;
}

.hero-cell.hero-best {
  background: var(--tint-best);
  border-color: rgba(201, 100, 66, 0.18);
  box-shadow: rgba(201, 100, 66, 0.06) 0px 0px 0px 1px;
}

.overline {
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--stone);
  font-weight: 500;
}

.hero-best .overline { color: var(--terracotta); }

.hero-title {
  font-size: 22px;
  line-height: 1.15;
  color: var(--near-black);
}

.hero-best-value {
  font-size: 28px;
  line-height: 1.05;
  color: var(--near-black);
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}

.hero-best-value .big-pct {
  color: var(--terracotta);
}

.hero-best-value .small {
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
  font-weight: 400;
  font-size: 13px;
  color: var(--olive);
  letter-spacing: 0;
}

.hero-note {
  font-size: 12px;
  color: var(--olive);
  line-height: 1.45;
}

.hero-note strong { color: var(--charcoal); font-weight: 500; }

.hero-stat {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hero-stat-main {
  font-family: "Fraunces", Georgia, serif;
  font-weight: 500;
  font-size: 22px;
  color: var(--near-black);
  letter-spacing: -0.01em;
  line-height: 1.1;
}

.hero-stat-sub {
  font-size: 12px;
  color: var(--olive);
}

.usage-grid {
  background: var(--ivory);
  border: 1px solid var(--border-cream);
  border-radius: 14px;
  overflow: hidden;
  flex: 1;
  display: flex;
  flex-direction: column;
}

.row-header, .row {
  display: grid;
  grid-template-columns: minmax(220px, 1.7fr) minmax(220px, 1.5fr) minmax(220px, 1.5fr) minmax(80px, 0.7fr) minmax(80px, 0.7fr);
  align-items: center;
  gap: 0;
  border-bottom: 1px solid var(--border-cream);
}

.row:last-child { border-bottom: 0; }

.row-header {
  background: var(--parchment);
  border-bottom: 1px solid var(--border-cream);
}

.row-header .cell {
  padding: 12px 22px;
  font-size: 10px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--stone);
  font-weight: 500;
}

.row {
  background: var(--ivory);
  transition: background 0.15s ease;
  flex: 1;
}

.row:hover { background: #f7f6ef; }

.row.row-best { background: var(--tint-best); }
.row.row-best:hover { background: var(--tint-best-hover); }

.row.row-error { background: rgba(181, 51, 51, 0.02); }

.cell { padding: 16px 22px; }

.account-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.label-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.label-name {
  font-size: 10px;
  letter-spacing: 0.18em;
  font-weight: 500;
  color: var(--charcoal);
  text-transform: uppercase;
}

.org-name {
  font-size: 17px;
  color: var(--near-black);
  line-height: 1.25;
  word-break: break-all;
}

.err-line {
  font-size: 11px;
  color: var(--crimson);
  font-style: italic;
  margin-top: 2px;
}

.badge {
  font-size: 9px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  padding: 2px 7px;
  border-radius: 99px;
  font-weight: 500;
  line-height: 1.4;
}

.badge-best { background: var(--terracotta); color: var(--ivory); }
.badge-default {
  background: transparent;
  color: var(--charcoal);
  border: 1px solid var(--ring-warm);
}
.badge-error { background: rgba(181, 51, 51, 0.1); color: var(--crimson); }

.metric-cell {
  display: grid;
  grid-template-columns: 52px 1fr;
  grid-template-rows: auto auto;
  row-gap: 4px;
  column-gap: 12px;
  align-items: center;
}

.metric-cell .pct {
  font-size: 20px;
  color: var(--near-black);
  line-height: 1;
  grid-column: 1;
  grid-row: 1;
  font-feature-settings: "tnum" on;
}

.metric-cell .pct.muted { color: var(--stone); font-style: italic; font-size: 17px; }

.metric-cell .bar {
  grid-column: 2;
  grid-row: 1;
  height: 6px;
  background: var(--warm-sand);
  border-radius: 99px;
  overflow: hidden;
}

.metric-cell.empty .bar { opacity: 0.5; }

.metric-cell .fill {
  height: 100%;
  background: var(--stone);
  border-radius: 99px;
  transition: width 0.4s ease;
}

.metric-cell .bar[data-sev="healthy"] .fill { background: var(--stone); }
.metric-cell .bar[data-sev="warning"] .fill { background: var(--coral); }
.metric-cell .bar[data-sev="critical"] .fill { background: var(--terracotta); }
.metric-cell .bar[data-sev="max"] .fill { background: var(--crimson); }

.metric-cell .countdown {
  grid-column: 1 / -1;
  grid-row: 2;
  font-size: 12px;
  color: var(--olive);
}

.metric-cell .countdown.muted { color: var(--stone); font-style: italic; }

.metric-cell .countdown strong {
  color: var(--charcoal);
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.model-cell { display: flex; align-items: center; }
.model-cell .pct { font-size: 18px; color: var(--charcoal); line-height: 1; }
.model-cell .pct.muted { color: var(--stone); font-style: italic; font-size: 15px; }

.foot {
  padding: 10px 40px;
  border-top: 1px solid var(--border-cream);
  font-size: 11px;
  color: var(--stone);
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  flex-shrink: 0;
  letter-spacing: 0.02em;
}

.foot code {
  font-family: ui-monospace, "SF Mono", "JetBrains Mono", monospace;
  font-size: 11px;
  background: var(--warm-sand);
  padding: 1px 6px;
  border-radius: 4px;
  color: var(--charcoal);
}

@media (max-width: 960px) {
  .hero { grid-template-columns: 1fr 1fr; }
  .hero-cell.hero-best { grid-column: 1 / -1; }
  .row-header .cell:nth-child(4), .row-header .cell:nth-child(5),
  .row .cell:nth-child(4), .row .cell:nth-child(5) { display: none; }
  .row-header, .row {
    grid-template-columns: minmax(180px, 1.4fr) 1fr 1fr;
  }
}

@media (max-width: 680px) {
  .container { padding: 16px 20px; }
  .topnav { padding: 12px 20px; }
  .hero { grid-template-columns: 1fr; }
  .hero-cell.hero-best { grid-column: auto; }
  .row-header, .row { grid-template-columns: 1fr 1fr; }
  .row-header .cell:first-child, .row .cell:first-child { grid-column: 1 / -1; }
}
"""


def _clean_org_name(name: str | None) -> str:
    if not name:
        return "Unknown organization"
    suffix = "'s Organization"
    if name.endswith(suffix):
        return name[: -len(suffix)]
    return name


def _countdown_html(value: str | None) -> str:
    rel = format_relative_reset(value)
    if not rel:
        return '<div class="countdown muted">no reset data</div>'
    return f'<div class="countdown">resets in <strong>{_html.escape(rel)}</strong></div>'


def _render_metric_cell(limit: dict[str, Any] | None) -> str:
    if not limit or limit.get("percent") is None:
        return (
            '<div class="cell metric-cell empty">'
            '<span class="pct muted">—</span>'
            '<div class="bar" data-sev="unknown"><div class="fill" style="width:0%"></div></div>'
            '<div class="countdown muted">no data</div>'
            '</div>'
        )
    pct = float(limit["percent"])
    fill = max(0.0, min(100.0, pct))
    sev = severity_class(pct)
    return (
        '<div class="cell metric-cell">'
        f'<span class="pct">{round(pct)}%</span>'
        f'<div class="bar" data-sev="{sev}"><div class="fill" style="width:{fill:.1f}%"></div></div>'
        f'{_countdown_html(limit.get("resets_at"))}'
        '</div>'
    )


def _render_model_cell(limit: dict[str, Any] | None) -> str:
    if not limit or limit.get("percent") is None:
        return '<div class="cell model-cell"><span class="pct muted">—</span></div>'
    pct = float(limit["percent"])
    return f'<div class="cell model-cell"><span class="pct">{round(pct)}%</span></div>'


def _render_account_row_html(
    account: dict[str, Any], *, is_default: bool, is_best: bool
) -> str:
    label = _html.escape(account["label"].upper())
    org = _html.escape(account["label"].title())
    cache = account.get("cache") or {}
    last_error = account.get("last_error")

    badges: list[str] = []
    if is_best and not last_error:
        badges.append('<span class="badge badge-best">Best</span>')
    if is_default:
        badges.append('<span class="badge badge-default">Default</span>')
    if last_error:
        badges.append('<span class="badge badge-error">Error</span>')
    badges_html = "".join(badges)

    err_html = f'<div class="err-line">{_html.escape(last_error)}</div>' if last_error else ""

    row_classes = ["row"]
    if is_best and not last_error:
        row_classes.append("row-best")
    if last_error:
        row_classes.append("row-error")
    row_class = " ".join(row_classes)

    account_cell = (
        '<div class="cell account-cell">'
        f'<div class="label-row">{badges_html}<span class="label-name">{label}</span></div>'
        f'<div class="org-name">{org}</div>'
        f'{err_html}'
        '</div>'
    )

    return (
        f'<div class="{row_class}">'
        f'{account_cell}'
        f'{_render_metric_cell(cache.get("five_hour"))}'
        f'{_render_metric_cell(cache.get("seven_day"))}'
        f'{_render_model_cell(cache.get("seven_day_opus"))}'
        f'{_render_model_cell(cache.get("seven_day_sonnet"))}'
        '</div>'
    )


def generate_html_report(state: dict[str, Any]) -> str:
    ensure_accounts(state)

    def sort_key(account: dict[str, Any]) -> tuple[int, float, str]:
        cache = account.get("cache") or {}
        weekly = weekly_value(cache)
        has_error = 1 if account.get("last_error") else 0
        weekly_sort = weekly if weekly is not None else 999.0
        return (has_error, weekly_sort, account["label"].lower())

    default_label = state.get("default_label")
    ordered = sorted(state["accounts"], key=sort_key)

    best_account = next(
        (
            a for a in ordered
            if not a.get("last_error")
            and (weekly_value(a.get("cache") or {}) or 0) < 100
        ),
        None,
    )
    best_label = best_account["label"] if best_account else None

    rows_html = "".join(
        _render_account_row_html(
            account,
            is_default=account["label"] == default_label,
            is_best=account["label"] == best_label,
        )
        for account in ordered
    )

    now_local = utc_now().astimezone()
    refreshed_str = (
        f"{now_local.strftime('%a %b')} {int(now_local.strftime('%d'))} · "
        f"{int(now_local.strftime('%I'))}:{now_local.strftime('%M')}"
        f"{now_local.strftime('%p').lower()}"
    )
    account_count = len(state["accounts"])
    healthy_count = sum(
        1 for a in state["accounts"]
        if (weekly_value(a.get("cache") or {}) or 0) < 50 and not a.get("last_error")
    )
    critical_count = sum(
        1 for a in state["accounts"]
        if (weekly_value(a.get("cache") or {}) or 0) >= 80
        and (weekly_value(a.get("cache") or {}) or 0) < 100
        and not a.get("last_error")
    )
    max_count = sum(
        1 for a in state["accounts"]
        if (weekly_value(a.get("cache") or {}) or 0) >= 100 and not a.get("last_error")
    )
    error_count = sum(1 for a in state["accounts"] if a.get("last_error"))

    if best_account:
        best_cache = best_account.get("cache") or {}
        best_weekly = weekly_value(best_cache) or 0
        best_seven_day = best_cache.get("seven_day") or {}
        best_reset = format_relative_reset(best_seven_day.get("resets_at"))
        best_label_upper = best_account["label"].upper()
        best_detail = (
            f'<span class="big-pct">{round(best_weekly)}%</span>'
            '<span class="small">weekly used</span>'
        )
        if best_reset:
            best_note = f'<strong>{_html.escape(best_label_upper)}</strong> · weekly resets in <strong>{_html.escape(best_reset)}</strong>'
        else:
            best_note = f'<strong>{_html.escape(best_label_upper)}</strong>'
        hero_best_html = (
            '<div class="hero-cell hero-best">'
            '<span class="overline">Best to use now</span>'
            f'<div class="hero-best-value">{best_detail}</div>'
            f'<div class="hero-note">{best_note}</div>'
            '</div>'
        )
    else:
        hero_best_html = (
            '<div class="hero-cell hero-best">'
            '<span class="overline">All accounts maxed</span>'
            '<div class="hero-best-value"><span class="big-pct">—</span></div>'
            '<div class="hero-note">Every account has hit its weekly ceiling.</div>'
            '</div>'
        )

    def _next_reset_summary() -> tuple[str, str]:
        soonest: tuple[float, str, str] | None = None
        for a in state["accounts"]:
            cache = a.get("cache") or {}
            seven = cache.get("seven_day") or {}
            rel = format_relative_reset(seven.get("resets_at"))
            reset_at = parse_datetime(seven.get("resets_at"))
            if rel and reset_at:
                secs = (reset_at - utc_now()).total_seconds()
                if soonest is None or secs < soonest[0]:
                    soonest = (secs, a["label"].upper(), rel)
        if soonest is None:
            return ("—", "no upcoming resets")
        return (soonest[2], f"next: {soonest[1]} · weekly")

    next_reset_value, next_reset_sub = _next_reset_summary()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Usage</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500&display=swap" rel="stylesheet">
<style>{HTML_REPORT_CSS}</style>
</head>
<body>
<nav class="topnav">
  <div class="wordmark">Claude Usage</div>
  <div class="refreshed">Refreshed {_html.escape(refreshed_str)}</div>
</nav>
<main class="container">
  <section class="hero">
    {hero_best_html}
    <div class="hero-cell">
      <span class="overline">Snapshot</span>
      <div class="hero-stat-main">{account_count} account{'s' if account_count != 1 else ''}</div>
      <div class="hero-stat-sub">{healthy_count} fresh · {critical_count} near ceiling · {max_count} maxed{f" · {error_count} error" if error_count else ""}</div>
    </div>
    <div class="hero-cell">
      <span class="overline">Next weekly reset</span>
      <div class="hero-stat-main">in {_html.escape(next_reset_value)}</div>
      <div class="hero-stat-sub">{_html.escape(next_reset_sub)}</div>
    </div>
  </section>
  <section class="usage-grid">
    <div class="row-header">
      <div class="cell">Account</div>
      <div class="cell">5-hour window</div>
      <div class="cell">7-day window</div>
      <div class="cell">Opus · 7d</div>
      <div class="cell">Sonnet · 7d</div>
    </div>
    {rows_html}
  </section>
</main>
<footer class="foot">
  <div>claude-usage.py · <code>~/.config/claude-usage/report.html</code></div>
  <div>Generated {_html.escape(now_local.strftime("%Y-%m-%d %H:%M"))}</div>
</footer>
</body>
</html>
"""


def handle_html(state: dict[str, Any], *, open_after: bool = True) -> str:
    ensure_accounts(state)
    refresh_accounts(state, labels=None, due_only=False)
    write_state(state)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    document = generate_html_report(state)
    REPORT_PATH.write_text(document, encoding="utf-8")
    REPORT_PATH.chmod(0o600)
    if open_after:
        try:
            subprocess.run(["open", str(REPORT_PATH)], check=False)
        except Exception as exc:
            return f"Report written to {REPORT_PATH} (open failed: {exc})"
    return f"Report written to {REPORT_PATH}"


def _self_update() -> str:
    if not getattr(sys, "frozen", False):
        return (
            f"Running as a script — update via:\n"
            f"  npx github:{GITHUB_REPO} update\n"
            f"or pull the latest claude-usage.py manually from {GITHUB_RELEASES_URL}"
        )
    arch = platform.machine()
    arch_map = {"arm64": "macos-arm64", "x86_64": "macos-x86_64"}
    suffix = arch_map.get(arch)
    if not suffix:
        raise ScriptError(f"Unsupported arch for self-update: {arch}")

    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
    with urllib.request.urlopen(api_url, timeout=10) as resp:  # noqa: S310
        release = json.load(resp)
    latest = release.get("tag_name", "").lstrip("v")
    if latest == __version__:
        return f"Already on latest version {__version__}"

    asset_name = f"claude-usage-{suffix}"
    download_url = next(
        (a["browser_download_url"] for a in release.get("assets", []) if a["name"] == asset_name),
        None,
    )
    if not download_url:
        raise ScriptError(f"No asset '{asset_name}' in latest release — check {GITHUB_RELEASES_URL}")

    dest = Path(sys.executable)
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as tmp:
        tmp_path = Path(tmp.name)
        with urllib.request.urlopen(download_url, timeout=60) as resp:  # noqa: S310
            tmp_path.write_bytes(resp.read())
    tmp_path.chmod(0o755)
    tmp_path.replace(dest)
    return f"Updated to {latest}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("command", nargs="?", default=None)
    parser.add_argument("rest", nargs="*")
    return parser


def parse_default_mode(argv: list[str]) -> tuple[str | None, bool, bool, bool]:
    preferred_label = None
    json_flag = False
    live_flag = False
    plain_flag = False
    for arg in argv:
        if arg == "--json":
            json_flag = True
        elif arg == "--live":
            live_flag = True
        elif arg == "--plain":
            plain_flag = True
        elif arg.startswith("-"):
            raise ScriptError(f"Unknown option: {arg}")
        elif preferred_label is None:
            preferred_label = arg
        else:
            raise ScriptError("Too many positional arguments")
    return preferred_label, json_flag, live_flag, plain_flag


def run_command(argv: list[str]) -> str:
    if argv and argv[0] in {"--version", "-V"}:
        return __version__

    state = read_state()
    parser = build_parser()
    known_commands = {
        "setup", "add", "list", "check", "default", "remove",
        "refresh-cache", "agent", "html", "status", "update",
        "help", "--help", "-h",
    }
    args = parser.parse_args(argv[:1] if argv and argv[0] in known_commands else [])

    if not argv or args.command is None:
        preferred_label, json_flag, live_flag, plain_flag = parse_default_mode(argv)
        _do_refresh(state, live=live_flag)
        selected, reason = select_account(state, preferred_label)
        selected = maybe_refresh_selected_account(state, selected, force_live=live_flag)
        source = "live" if live_flag else "cache_or_live"
        if json_flag:
            return render_json(state, selected, reason, source=source)
        if sys.stdout.isatty() and not plain_flag:
            print(render_cli_status(state))
            return ""
        return numbered_inline_line(state)

    command = args.command
    rest = argv[1:]

    if command in {"--version", "-V"}:
        return __version__

    if command in {"help", "--help", "-h"}:
        return (
            f"claude-usage {__version__}\n\n"
            "Usage:\n"
            "  claude-usage [label] [--plain] [--live] [--json]  Show status\n"
            "  claude-usage status   [--plain] [--live]          Same as above\n"
            "  claude-usage html     [--no-open]                 Open HTML dashboard\n"
            "  claude-usage add      <label> <session_key>       Add account\n"
            "  claude-usage remove   <label>                     Remove account\n"
            "  claude-usage list                                 List all accounts\n"
            "  claude-usage check    [label] [--json] [--live]   Check one account\n"
            "  claude-usage default  <label>                     Set default account\n"
            "  claude-usage refresh-cache [--all] [--due-only]  Refresh cache\n"
            "  claude-usage update                              Self-update binary\n"
            "  claude-usage agent    install|uninstall|run-once  Background agent\n"
            "  claude-usage --version                           Print version\n"
        )

    if command == "status":
        plain_flag = "--plain" in rest
        live_flag = "--live" in rest
        _do_refresh(state, live=live_flag)
        if plain_flag:
            return numbered_inline_line(state)
        print(render_cli_status(state))
        return ""

    if command == "update":
        return _self_update()

    if command == "setup":
        if rest:
            raise ScriptError("setup does not take arguments")
        return handle_setup(state)

    if command == "add":
        if len(rest) != 2:
            raise ScriptError("Usage: claude-usage add <label> <session_key>")
        account = add_account(state, rest[0], rest[1])
        return f"Added {account['label']} ({account['organization_name']})"

    if command == "list":
        if rest:
            raise ScriptError("list does not take arguments")
        return render_list(state)

    if command == "default":
        if len(rest) != 1:
            raise ScriptError("Usage: claude-usage default <label>")
        set_default_account(state, rest[0])
        return f"Default account set to {rest[0]}"

    if command == "remove":
        if len(rest) != 1:
            raise ScriptError("Usage: claude-usage remove <label>")
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
        _do_refresh(state, live=live_flag)
        selected, reason = select_account(state, preferred_label)
        selected = maybe_refresh_selected_account(state, selected, force_live=live_flag)
        source = "live" if live_flag else "cache_or_live"
        return render_json(state, selected, reason, source=source) if json_flag else numbered_inline_line(state)

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
        refreshed_labels = ", ".join(a["label"] for a in refreshed) if refreshed else "none"
        skipped_labels = ", ".join(a["label"] for a in skipped) if skipped else "none"
        return f"Refreshed: {refreshed_labels}{INLINE_SEPARATOR}Skipped: {skipped_labels}"

    if command == "html":
        open_after = True
        for arg in rest:
            if arg == "--no-open":
                open_after = False
            elif arg.startswith("-"):
                raise ScriptError(f"Unknown option: {arg}")
            else:
                raise ScriptError("html does not take positional arguments")
        return handle_html(state, open_after=open_after)

    if command == "agent":
        if len(rest) != 1 or rest[0] not in {"install", "uninstall", "run-once"}:
            raise ScriptError("Usage: claude-usage agent install|uninstall|run-once")
        action = rest[0]
        if action == "install":
            return install_launch_agent()
        if action == "uninstall":
            return uninstall_launch_agent()
        refreshed, skipped = refresh_accounts(state, labels=None, due_only=True)
        write_state(state)
        refreshed_labels = ", ".join(a["label"] for a in refreshed) if refreshed else "none"
        skipped_labels = ", ".join(a["label"] for a in skipped) if skipped else "none"
        return f"Agent run complete{INLINE_SEPARATOR}Refreshed: {refreshed_labels}{INLINE_SEPARATOR}Skipped: {skipped_labels}"

    raise ScriptError(f"Unknown command: {command}")


def main() -> None:
    try:
        output = run_command(sys.argv[1:])
        if output:
            print(output)
    except KeyboardInterrupt:
        print("Cancelled")
        raise SystemExit(1)
    except ScriptError as exc:
        print(str(exc))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
