"""Общие константы и хелперы для отчётов /generate и /apply.

Раньше REPORTS_DIR, регулярка report_id и формат UTC-timestamp
дублировались в main.py и apply.py. Любая попытка сменить формат
требовала держать два места в синхроне - типичный путь к расхождению.
Здесь единственный источник правды.
"""
import re
from datetime import datetime, timezone
from pathlib import Path

REPORTS_DIR = Path(__file__).parent / "reports"

REPORT_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}_(safe|risky|destructive)$")


def utc_now_report_id(mode: str) -> str:
    """Сформировать report_id вида 20240115T120000_<mode> в текущий UTC."""
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{mode}"


def utc_now_iso_z() -> str:
    """Текущее время UTC в ISO8601 с суффиксом Z (без +00:00)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
