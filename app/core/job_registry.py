"""Single source of truth for all scheduler job types."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobTypeDef:
    code: str
    label_pl: str
    synthetic: bool = False


JOB_REGISTRY: list[JobTypeDef] = [
    JobTypeDef("SEND_TO_KSEF", "Wysyłanie do KSeF"),
    JobTypeDef("POLL_KSEF_STATUS", "Sprawdzanie statusu KSeF"),
    JobTypeDef("SEND_BOOKED_NOTIFICATION", "Wysyłanie powiadomienia"),
    JobTypeDef("SEND_ACCOUNTING_BATCH", "Batch księgowy"),
    JobTypeDef("FETCH_KSEF_PURCHASES", "Pobieranie faktur zakupowych"),
    JobTypeDef("POLL_GITHUB_PROJECT", "Sprawdzanie tablicy GitHub", synthetic=True),
    JobTypeDef("SEND_DISCORD_NOTIFICATION", "Podsumowanie Discord", synthetic=True),
]

# Derived helpers — used by scheduler, toast, and API
JOB_TYPES: list[str] = [j.code for j in JOB_REGISTRY]
JOB_TYPE_LABELS: dict[str, str] = {j.code: j.label_pl for j in JOB_REGISTRY}
SYNTHETIC_JOB_TYPES: set[str] = {j.code for j in JOB_REGISTRY if j.synthetic}

STATUS_LABELS: dict[str, str] = {
    "done": "wykonano",
    "skipped": "pominięto",
    "failed": "błąd",
    "running": "w trakcie",
    "pending": "oczekuje",
}
