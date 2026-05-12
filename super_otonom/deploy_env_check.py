"""
Canlı / staging kutusunda `.env` yüklendikten sonra çalıştırın:

    python -m super_otonom.deploy_env_check

A9 + paper/canlı kombinasyonlarını kontrol eder; canlı profilde LIVE_CONFIRM=YES
(`main_loop` ile aynı); sorunda çıkış kodu ≠ 0. Başarılı çıktıda testnet=true ise stdout UYARISI.
Başarılı ve ``DEPLOY_ENV_SKIP_RISK_SUMMARY=1`` yoksa stdout'a ``print_resolved_risk --summary``
eklenir (P0 — INSTITUTIONAL §1 hizalama; üretim kutuda ayrı komut gerekmez).
Başarıda ``data/reports/deploy_env_check_last_ok.json`` zaman damgası yazılır; canlı tick kilidi
için ``DEPLOY_ENV_LOCK_AT_START`` (RUNBOOK).
`super_otonom.config` import edilir (dotenv + mevcut uyarı logları tetiklenir).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    from super_otonom.config import EXCHANGES, GENERAL, RISK
    from super_otonom.meta_regime_orchestrator import advisory_ack_path_for_gate

    mode = (os.getenv("META_REGIME_MODE") or "shadow").strip().lower()
    loose = (os.getenv("META_ADVISORY_LOOSE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    paper = bool(GENERAL.get("paper_mode"))
    live_like = not paper

    issues: list[str] = []

    if mode == "advisory" and live_like and loose:
        issues.append(
            "[HATA] Paper/dry-run kapalı ortamda META_ADVISORY_LOOSE açık — "
            "canlı .env'den kaldırın (geliştirme .env'ini kopyalamayın)."
        )

    # main_loop ile aynı kapı: paper kapalıyken LIVE_CONFIRM zorunlu
    if live_like and GENERAL.get("live_confirm") != "YES":
        issues.append(
            "[HATA] PAPER_MODE kapalı (canlı profil) ancak LIVE_CONFIRM=YES değil — "
            "main_loop başlamadan çıkar; .env bilinçli güncelleyin (RUNBOOK #tatbikat-env)."
        )

    if mode == "advisory" and live_like and not loose:
        path = advisory_ack_path_for_gate("advisory")
        if path is not None:
            try:
                ok = os.path.isfile(path) and os.path.getsize(path) > 0
            except OSError:
                ok = False
            if not ok:
                issues.append(
                    f"[HATA] META_REGIME_MODE=advisory ancak ölçüm ACK yok veya boş: {path}\n"
                    '        Çalıştırın: python -m super_otonom.meta_regime_orchestrator --message "A5 reviewed"\n'
                    "        veya: powershell -ExecutionPolicy Bypass -File scripts/write_meta_advisory_ack.ps1"
                )

    if not issues:
        print(
            "deploy_env_check: A9 / canlı .env — engelleyici sorun yok "
            f"(META_REGIME_MODE={mode!r}, paper_mode={paper}, "
            f"LIVE_CONFIRM={GENERAL.get('live_confirm')!r})."
        )
        # CI / minimal env: .env yokken de config.RISK (env varsayılanları) stdout'da görünsün.
        print(
            "deploy_env_check: P0 - INSTITUTIONAL sect.1 alignment (resolved RISK; no .env required): "
            f"max_daily_loss_pct={RISK.get('max_daily_loss_pct')!r}"
        )
        ex_id = str(GENERAL.get("default_exchange") or "")
        ex_cfg = EXCHANGES.get(ex_id, {})
        if live_like and ex_cfg.get("testnet") is True:
            print(
                "deploy_env_check: UYARI — "
                f"default_exchange={ex_id!r} için testnet=true; "
                "gerçek canlı hesap kullanıyorsanız venue testnet bayrağını false yapın (RCO manuel)."
            )
        if (os.getenv("DEPLOY_ENV_SKIP_RISK_SUMMARY") or "").strip().lower() not in (
            "1",
            "true",
            "yes",
            "on",
        ):
            root = Path(__file__).resolve().parents[1]
            script = root / "scripts" / "print_resolved_risk.py"
            if script.is_file():
                print(
                    "deploy_env_check: P0 — çözümlenmiş RISK özeti (INSTITUTIONAL sect.1 ile karşılaştırın):"
                )
                proc = subprocess.run(
                    [sys.executable, str(script), "--summary"],
                    cwd=str(root),
                    env=os.environ.copy(),
                    timeout=120,
                    text=True,
                )
                if proc.returncode != 0:
                    print(
                        "deploy_env_check: UYARI — print_resolved_risk.py çıkış "
                        f"{proc.returncode}; §1 özetini manuel çalıştırın.",
                        file=sys.stderr,
                    )
            else:
                print(
                    f"deploy_env_check: UYARI — özet script bulunamadı: {script}",
                    file=sys.stderr,
                )
        try:
            from super_otonom.deploy_env_stamp import write_last_ok

            stamp_path = write_last_ok()
            print(
                "deploy_env_check: başarı zaman damgası — "
                f"{stamp_path.name} (canlı tick kilidi için RUNBOOK #tatbikat-env)."
            )
        except OSError as exc:
            print(
                f"deploy_env_check: UYARI — başarı kaydı yazılamadı: {exc}",
                file=sys.stderr,
            )
        return 0

    print("\n".join(issues), file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
