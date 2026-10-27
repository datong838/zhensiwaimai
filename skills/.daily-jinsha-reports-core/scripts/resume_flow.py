"""Small deterministic router. No device access, no hidden send retry."""

TRANSIENT = (
    "page-not-ready:", "list-view-not-ready", "report-list-not-stable",
    "exact-filename-not-unique", "selected-file-animation-not-stable",
    "sent-bubble-not-stable", "group-title-not-verified", "file-panel-still-moving",
    "file-music-evidence-incomplete", "system-file-picker-not-ready",
    "wechat-not-foreground-after-send", "transient-page-obscured",
    "main-wechat-not-foreground", "wechat-home-not-recognized", "visible-group-title-not-verified",
)


def retryable(error):
    return str(error).startswith(TRANSIENT)


def next_action(ledger_state, page, bound):
    if ledger_state == "confirmed":
        return "done"
    if ledger_state == "in-flight":
        return "verify"  # Never decides to click send solely from a ledger flag.
    if page in ("picker", "file_selector", "selected") and not bound:
        raise RuntimeError("unbound-file-page")
    return {"picker": "choose", "file_selector": "select", "selected": "send",
            "group": "panel", "home": "locate", "obscured": "wait"}[page]


def validate_binding(saved, group, hashes):
    if saved and (saved.get("group") != group or saved.get("hashes") != hashes):
        raise RuntimeError("checkpoint-binding-mismatch")


def retry_delay(failure_count):
    return min(4.0, .5 * 2 ** (failure_count - 1))
