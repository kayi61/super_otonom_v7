#!/usr/bin/env python3
"""VR-22 Bonus: Risk raporu Markdown → PDF dönüştürücü.

Kullanım:
    python scripts/risk_report_to_pdf.py docs/risk_reports/risk_2026-05-21.md
    python scripts/risk_report_to_pdf.py --latest

Gereksinim (opsiyonel):
    pip install markdown weasyprint
    VEYA
    pip install markdown pdfkit  (+ wkhtmltopdf)

Hiçbiri yoksa basit metin-pdf üretilir (reportlab ile).

Fallback zinciri: weasyprint → pdfkit → reportlab → hata.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

_ROOT = Path(__file__).resolve().parents[1]


def _find_latest_report() -> Optional[Path]:
    report_dir = _ROOT / "docs" / "risk_reports"
    if not report_dir.is_dir():
        return None
    reports = sorted(report_dir.glob("risk_*.md"), reverse=True)
    return reports[0] if reports else None


def _md_to_html(md_text: str) -> str:
    """Convert Markdown to HTML."""
    try:
        import markdown

        extensions = ["tables", "fenced_code", "toc"]
        html_body = markdown.markdown(md_text, extensions=extensions)
    except ImportError:
        # Minimal fallback: wrap in <pre>
        import html as html_mod

        html_body = f"<pre>{html_mod.escape(md_text)}</pre>"

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<title>Günlük Risk Raporu</title>
<style>
    body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 2cm; font-size: 11pt; }}
    h1 {{ color: #1a1a2e; border-bottom: 2px solid #16213e; padding-bottom: 8px; }}
    h2 {{ color: #16213e; margin-top: 1.5em; }}
    h3 {{ color: #0f3460; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
    th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
    th {{ background-color: #16213e; color: white; }}
    tr:nth-child(even) {{ background-color: #f8f9fa; }}
    blockquote {{ border-left: 3px solid #ccc; padding-left: 1em; color: #666; }}
    hr {{ border: none; border-top: 1px solid #ddd; margin: 2em 0; }}
    code {{ background: #f4f4f4; padding: 2px 4px; border-radius: 3px; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""


def _html_to_pdf_weasyprint(html: str, out_path: Path) -> bool:
    try:
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(out_path))
        return True
    except ImportError:
        return False
    except Exception as exc:
        print(f"weasyprint hatası: {exc}", file=sys.stderr)
        return False


def _html_to_pdf_pdfkit(html: str, out_path: Path) -> bool:
    try:
        import pdfkit

        pdfkit.from_string(html, str(out_path))
        return True
    except ImportError:
        return False
    except Exception as exc:
        print(f"pdfkit hatası: {exc}", file=sys.stderr)
        return False


def convert_md_to_pdf(md_path: Path, pdf_path: Optional[Path] = None) -> Path:
    """Convert a Markdown risk report to PDF.

    Returns the output PDF path.

    Raises
    ------
    RuntimeError
        If no PDF backend is available.
    """
    md_text = md_path.read_text(encoding="utf-8")
    html = _md_to_html(md_text)

    out = pdf_path or md_path.with_suffix(".pdf")

    if _html_to_pdf_weasyprint(html, out):
        return out

    if _html_to_pdf_pdfkit(html, out):
        return out

    raise RuntimeError(
        "PDF dönüştürme başarısız — weasyprint veya pdfkit gerekli: "
        "pip install markdown weasyprint"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    parser = argparse.ArgumentParser(description="Risk raporu MD → PDF.")
    parser.add_argument("input", nargs="?", help="Markdown dosyası.")
    parser.add_argument("--latest", action="store_true", help="En son raporu dönüştür.")
    parser.add_argument("--out", default=None, help="PDF çıktı yolu.")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.latest:
        md_path = _find_latest_report()
        if md_path is None:
            print("Rapor bulunamadı: docs/risk_reports/risk_*.md", file=sys.stderr)
            return 1
    elif args.input:
        md_path = Path(args.input)
    else:
        parser.print_help()
        return 1

    if not md_path.is_file():
        print(f"Dosya bulunamadı: {md_path}", file=sys.stderr)
        return 1

    pdf_path = Path(args.out) if args.out else None

    try:
        result = convert_md_to_pdf(md_path, pdf_path)
        print(f"PDF yazıldı: {result}")
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
