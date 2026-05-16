"""Single source of truth for all domain status values, labels, and display styles."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StatusDef:
    code: str
    label_pl: str
    pill_class: str  # CSS class: "pill-success", "pill-warning", "pill-danger", "pill-info"
    emoji: str  # For Discord messages: 🟢 🟡 🔴 🔵 ⚪ 🟠


# ─── KSeF Status ────────────────────────────────────────────────────────────

KSEF_STATUSES: list[StatusDef] = [
    StatusDef("DRAFT", "Szkic", "badge-ksef-draft", "⚪"),
    StatusDef("GENERATED", "Wygenerowano XML", "badge-ksef-draft", "⚪"),
    StatusDef("QUEUED", "W kolejce", "badge-ksef-queued", "🟡"),
    StatusDef("SENT", "Wysłano", "badge-ksef-sent", "🔵"),
    StatusDef("PROCESSING", "Przetwarzanie", "badge-ksef-sent", "🔵"),
    StatusDef("ACCEPTED", "Zaakceptowano", "badge-ksef-accepted", "🟢"),
    StatusDef("REJECTED", "Odrzucono", "badge-ksef-rejected", "🔴"),
    StatusDef("DOWNLOADED", "Pobrano", "badge-ksef-accepted", "🟢"),
    StatusDef("ERROR", "Błąd", "badge-ksef-error", "🔴"),
]

# ─── ERP Status ─────────────────────────────────────────────────────────────

ERP_STATUSES: list[StatusDef] = [
    StatusDef("DRAFT_CREATED", "Szkic utworzony", "pill-warning", "⚪"),
    StatusDef("SENT_TO_KSEF", "Wysłano do KSeF", "pill-info", "🔵"),
    StatusDef("KSEF_ACCEPTED", "Zaakceptowano w KSeF", "pill-success", "🟢"),
    StatusDef("KSEF_REJECTED", "Odrzucono w KSeF", "pill-danger", "🔴"),
    StatusDef("READY_FOR_ACCOUNTING", "Gotowa do księgowości", "pill-info", "🔵"),
    StatusDef("BLOCKED", "Zablokowana", "pill-danger", "🔴"),
    StatusDef("ACCOUNTING_BATCHED", "W pakiecie księgowym", "pill-info", "📵"),
    StatusDef("SENT_TO_OFFICE", "Wysłano do biura", "pill-success", "🟢"),
    StatusDef("APPROVED", "Zatwierdzona", "pill-success", "🟢"),
]

# ─── Accounting Status ──────────────────────────────────────────────────────

ACCOUNTING_STATUSES: list[StatusDef] = [
    StatusDef("new", "Nowa", "pill-warning", "🟡"),
    StatusDef("qualified", "Zakwalifikowana", "pill-info", "🔵"),
    StatusDef("batched", "W pakiecie", "pill-info", "📵"),
    StatusDef("sent_to_office", "Wysłano do biura", "pill-success", "🟢"),
    StatusDef("rejected", "Odrzucona", "pill-danger", "🔴"),
]

# ─── Review Status ──────────────────────────────────────────────────────────

REVIEW_STATUSES: list[StatusDef] = [
    StatusDef("PENDING", "Oczekuje", "pill-warning", "🟡"),
    StatusDef("APPROVED", "Zatwierdzona", "pill-success", "🟢"),
    StatusDef("REJECTED", "Odrzucona", "pill-danger", "🔴"),
]

# ─── Notification Status ────────────────────────────────────────────────────

NOTIFICATION_STATUSES: list[StatusDef] = [
    StatusDef("PENDING", "Oczekuje", "pill-warning", "🟡"),
    StatusDef("NEW", "Nowa", "pill-warning", "🟡"),
    StatusDef("SENT", "Wysłano", "pill-success", "🟢"),
    StatusDef("FAILED", "Błąd", "pill-danger", "🔴"),
]

# ─── Status pakietu księgowego ───────────────────────────────────────────────

BATCH_STATUSES: list[StatusDef] = [
    StatusDef("GENERATED", "Wygenerowany", "pill-warning", "🟡"),
    StatusDef("SENT", "Wysłano", "pill-success", "🟢"),
]

# ─── Direction Code ─────────────────────────────────────────────────────────

DIRECTION_STATUSES: list[StatusDef] = [
    StatusDef("SALE", "Sprzedaż", "pill-danger", "🟠"),
    StatusDef("PURCHASE", "Zakup", "pill-info", "🔵"),
]


# ─── Derived lookup helpers ─────────────────────────────────────────────────

def _build_lookup(statuses: list[StatusDef]) -> dict[str, StatusDef]:
    return {s.code: s for s in statuses}


KSEF_STATUS_MAP: dict[str, StatusDef] = _build_lookup(KSEF_STATUSES)
ERP_STATUS_MAP: dict[str, StatusDef] = _build_lookup(ERP_STATUSES)
ACCOUNTING_STATUS_MAP: dict[str, StatusDef] = _build_lookup(ACCOUNTING_STATUSES)
REVIEW_STATUS_MAP: dict[str, StatusDef] = _build_lookup(REVIEW_STATUSES)
NOTIFICATION_STATUS_MAP: dict[str, StatusDef] = _build_lookup(NOTIFICATION_STATUSES)
BATCH_STATUS_MAP: dict[str, StatusDef] = _build_lookup(BATCH_STATUSES)
DIRECTION_STATUS_MAP: dict[str, StatusDef] = _build_lookup(DIRECTION_STATUSES)

# Allowed-value sets (for validation in services)
ALLOWED_KSEF_STATUSES: set[str] = {s.code for s in KSEF_STATUSES}
ALLOWED_ERP_STATUSES: set[str] = {s.code for s in ERP_STATUSES}
ALLOWED_ACCOUNTING_STATUSES: set[str] = {s.code for s in ACCOUNTING_STATUSES}
ALLOWED_REVIEW_STATUSES: set[str] = {s.code for s in REVIEW_STATUSES}

# All registries indexed by field name (for generic Jinja helper)
STATUS_REGISTRIES: dict[str, dict[str, StatusDef]] = {
    "ksef": KSEF_STATUS_MAP,
    "erp": ERP_STATUS_MAP,
    "accounting": ACCOUNTING_STATUS_MAP,
    "review": REVIEW_STATUS_MAP,
    "notification": NOTIFICATION_STATUS_MAP,
    "batch": BATCH_STATUS_MAP,
    "direction": DIRECTION_STATUS_MAP,
}


def get_status_label(registry_name: str, code: str | None) -> str:
    """Get Polish label for a status code. Returns code itself as fallback."""
    if not code:
        return "BRAK"
    registry = STATUS_REGISTRIES.get(registry_name, {})
    entry = registry.get(code)
    return entry.label_pl if entry else code


def get_status_pill_class(registry_name: str, code: str | None) -> str:
    """Get CSS pill class for a status code."""
    if not code:
        return "pill-warning"
    registry = STATUS_REGISTRIES.get(registry_name, {})
    entry = registry.get(code)
    return entry.pill_class if entry else "pill-warning"


def get_status_emoji(registry_name: str, code: str | None) -> str:
    """Get emoji for a status code (for Discord messages)."""
    if not code:
        return "⚪"
    registry = STATUS_REGISTRIES.get(registry_name, {})
    entry = registry.get(code)
    return entry.emoji if entry else "⚪"


def format_status_discord(registry_name: str, code: str | None) -> str:
    """Format a status for Discord: emoji + Polish label."""
    emoji = get_status_emoji(registry_name, code)
    label = get_status_label(registry_name, code)
    return f"{emoji} {label}"
