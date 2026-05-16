"""
PROMPT 2 — Uretim sir denetimi: Vault-only, .env duz metin, deploy_env_check.

Cikti: docs/SECRETS_AUDIT_LAST.md (tarih, makine, tablo; sır degerleri YOK).
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_DOC = _REPO_ROOT / "docs" / "SECRETS_AUDIT_LAST.md"


@dataclass
class CheckRow:
    madde: str
    sonuc: str  # PASS | FAIL | WARN | N/A
    not_: str


def _repo_root() -> Path:
    return _REPO_ROOT


def _scan_dotenv_key_names(env_path: Path, watch_names: Sequence[str]) -> List[str]:
    """`.env` dosyasinda dolu borsa anahtar degisken adlari (deger yazilmaz)."""
    if not env_path.is_file():
        return []
    watch = set(watch_names)
    found: List[str] = []
    for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = re.sub(r'^["\']|["\']$', "", val.strip())
        if key in watch and val:
            found.append(key)
    return sorted(set(found))


def _env_keys_set(names: Sequence[str]) -> List[str]:
    return sorted(n for n in names if (os.getenv(n) or "").strip())


def _exchange_key_names() -> List[str]:
    """Borsa API anahtarlari (Telegram haric — canli emir yolu)."""
    from super_otonom.vault_bridge import env_api_key_names

    return [n for n in env_api_key_names() if not n.startswith("TELEGRAM_")]


def _telegram_key_names() -> List[str]:
    return ["TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]


def _live_profile_env_overlay() -> Dict[str, str]:
    return {
        "DRY_RUN": "false",
        "PAPER_MODE": "false",
        "LIVE_CONFIRM": "YES",
        "SECRETS_VAULT_ONLY": "true",
    }


def _run_deploy_env_check(extra_env: Optional[Dict[str, str]] = None) -> Tuple[int, str]:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, "-m", "super_otonom.deploy_env_check"],
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    # Sır sızıntısı riski: satırlarda anahtar değeri göstermeyelim
    safe_lines: List[str] = []
    for line in out.splitlines():
        if re.search(r"(api_key|api_secret|BINANCE_|SECRET)=", line, re.I):
            safe_lines.append("[redacted line]")
        else:
            safe_lines.append(line)
    return proc.returncode, "\n".join(safe_lines[-40:])


def run_audit(*, write_doc: bool = True, doc_path: Optional[Path] = None) -> int:
    from super_otonom.config import GENERAL
    from super_otonom.vault_bridge import VaultBridge, secrets_vault_only_mode

    doc_path = doc_path or _DEFAULT_DOC
    verified_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    machine = platform.node() or os.getenv("COMPUTERNAME", "unknown")
    env_file = _repo_root() / ".env"
    exchange_keys = _exchange_key_names()
    telegram_keys = _telegram_key_names()
    ex_id = str(GENERAL.get("default_exchange") or "binance").lower()

    rows: List[CheckRow] = []

    dry = bool(GENERAL.get("dry_run"))
    paper = bool(GENERAL.get("paper_mode"))
    live_confirm = str(GENERAL.get("live_confirm") or "")

    rows.append(
        CheckRow(
            "Mevcut profil: DRY_RUN",
            "PASS" if dry else "WARN",
            str(dry),
        )
    )
    rows.append(
        CheckRow(
            "Mevcut profil: PAPER_MODE",
            "PASS" if paper else "WARN",
            str(paper),
        )
    )
    rows.append(
        CheckRow(
            "Mevcut profil: LIVE_CONFIRM",
            "PASS" if live_confirm == "YES" else "WARN",
            repr(live_confirm),
        )
    )

    dotenv_exchange = _scan_dotenv_key_names(env_file, exchange_keys)
    rows.append(
        CheckRow(
            ".env icinde duz metin BINANCE/borsa anahtari (dosya)",
            "FAIL" if dotenv_exchange else "PASS",
            ", ".join(dotenv_exchange) if dotenv_exchange else "(yok)",
        )
    )

    dotenv_telegram = _scan_dotenv_key_names(env_file, telegram_keys)
    rows.append(
        CheckRow(
            ".env icinde TELEGRAM_* (uyari; canlida Vault onerilir)",
            "WARN" if dotenv_telegram else "PASS",
            ", ".join(dotenv_telegram) if dotenv_telegram else "(yok)",
        )
    )

    env_exchange = _env_keys_set(exchange_keys)
    rows.append(
        CheckRow(
            "Ortamda duz metin BINANCE/borsa anahtari (process env)",
            "FAIL" if env_exchange else "PASS",
            ", ".join(env_exchange) if env_exchange else "(yok)",
        )
    )

    vault_only_now = secrets_vault_only_mode()
    rows.append(
        CheckRow(
            "SECRETS_VAULT_ONLY (simdiki cozumleme)",
            "PASS" if vault_only_now else "WARN",
            str(vault_only_now),
        )
    )

    vb = VaultBridge()
    vst = vb.status()
    rows.append(
        CheckRow(
            "Vault erisilebilir",
            "PASS" if vst.get("available") else "FAIL",
            f"addr={vst.get('addr')} auth={vst.get('auth')}",
        )
    )

    kv_path = vb.kv_path_display(ex_id)
    probe = vb.probe_kv_fields(ex_id, ("api_key", "api_secret"))
    kv_ok = all(probe.values())
    rows.append(
        CheckRow(
            f"Vault KV dolu ({kv_path})",
            "PASS" if kv_ok else ("WARN" if not vst.get("available") else "FAIL"),
            "api_key=" + ("evet" if probe.get("api_key") else "hayir")
            + " api_secret=" + ("evet" if probe.get("api_secret") else "hayir"),
        )
    )

    dep_code, dep_snip = _run_deploy_env_check()
    rows.append(
        CheckRow(
            "deploy_env_check (mevcut .env)",
            "PASS" if dep_code == 0 else "FAIL",
            f"exit={dep_code}",
        )
    )

    live_env = _live_profile_env_overlay()
    dep_live_code, dep_live_snip = _run_deploy_env_check(live_env)
    rows.append(
        CheckRow(
            "deploy_env_check (canli profil sim: DRY_RUN=false PAPER=false LIVE_CONFIRM=YES SECRETS_VAULT_ONLY=true)",
            "PASS" if dep_live_code == 0 else "FAIL",
            f"exit={dep_live_code}",
        )
    )

    live_blockers = [
        r
        for r in rows
        if r.sonuc == "FAIL"
        and (
            "borsa" in r.madde.lower()
            or r.madde.startswith("Vault erisilebilir")
            or r.madde.startswith("Vault KV dolu")
            or "deploy_env_check (canli" in r.madde
        )
    ]
    overall = "PASS" if not live_blockers else "FAIL"
    if overall == "PASS" and any(r.sonuc == "WARN" for r in rows):
        overall = "WARN"

    order_block = (
        "Canli profilde deploy_env_check veya Vault-only iken anahtar sizintisi varsa "
        "`main_loop` / config yolu gercek emir gondermemeli (LIVE_CONFIRM + SECRETS_VAULT_ONLY kapilari)."
    )

    lines = [
        f"# Sir denetimi (PROMPT 2) — {verified_at}",
        "",
        "| Alan | Deger |",
        "|------|--------|",
        f"| Makine | `{machine}` |",
        f"| Repo | `{_repo_root()}` |",
        f"| Genel sonuc | **{overall}** |",
        f"| .env dosyasi | `{env_file}` ({'var' if env_file.is_file() else 'yok'}) |",
        "",
        "## Checklist",
        "",
        "| Madde | Sonuc | Not |",
        "|-------|--------|-----|",
    ]
    for r in rows:
        note = (r.not_ or "").replace("|", "\\|")
        lines.append(f"| {r.madde} | **{r.sonuc}** | {note} |")

    lines.extend(
        [
            "",
            "## deploy_env_check ozeti (son satirlar, sir yok)",
            "",
            "### Mevcut profil",
            "```text",
            dep_snip.strip() or "(bos)",
            "```",
            "",
            "### Canli profil simulasyonu",
            "```text",
            dep_live_snip.strip() or "(bos)",
            "```",
            "",
            "## Emir gonderimi",
            "",
            order_block,
            "",
            "## Yenileme",
            "",
            "```powershell",
            "Set-Location -LiteralPath '<repo_koku>'",
            ".\\scripts\\fastrun_secrets_audit.cmd",
            "```",
            "",
        ]
    )

    if write_doc:
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"secrets_audit: genel={overall} makine={machine}")
    for r in rows:
        print(f"  [{r.sonuc}] {r.madde}: {r.not_}")
    if write_doc:
        print(f"Yazildi: {doc_path}")

    return 0 if overall == "PASS" else (2 if overall == "WARN" else 1)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Uretim sir denetimi (Vault / .env / deploy_env_check)")
    p.add_argument("--no-write-doc", action="store_true", help="SECRETS_AUDIT_LAST.md yazma")
    p.add_argument("--doc", type=Path, default=_DEFAULT_DOC)
    args = p.parse_args(argv)
    return run_audit(write_doc=not args.no_write_doc, doc_path=args.doc)


if __name__ == "__main__":
    raise SystemExit(main())
