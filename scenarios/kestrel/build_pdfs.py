"""Render the Kestrel corpus to realistic-looking policy PDFs.

    python scenarios/kestrel/build_pdfs.py

Writes docs/ (preloaded at start-up) and docs/to-upload/ (uploaded by the
evaluator during the walkthrough).
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from corpus import COMPANY, DOCS  # noqa: E402

styles = getSampleStyleSheet()
H_COMPANY = ParagraphStyle("co", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))
H_TITLE = ParagraphStyle("t", parent=styles["Title"], fontSize=17, spaceAfter=4, alignment=0)
H_SEC = ParagraphStyle("s", parent=styles["Heading3"], fontSize=11.5, spaceBefore=8, spaceAfter=3)
BODY = ParagraphStyle("b", parent=styles["BodyText"], fontSize=10, leading=14, spaceAfter=4)
FOOT = ParagraphStyle("f", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#777777"))


def build(doc: dict, out_dir: Path) -> Path:
    path = out_dir / doc["file"]
    story = [
        Paragraph(f"{COMPANY} &nbsp;|&nbsp; {doc['dept']}", H_COMPANY),
        Paragraph(doc["title"], H_TITLE),
    ]
    meta = [
        ["Document no.", doc["doc_no"], "Version", doc["version"]],
        ["Effective date", doc["date"], "Owner", doc["dept"]],
    ]
    if doc.get("supersedes"):
        meta.append(["Supersedes", doc["supersedes"], "Status", "In force"])
    table = Table(meta, colWidths=[28 * mm, 55 * mm, 22 * mm, 60 * mm])
    table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#555555")),
        ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#555555")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#bbbbbb")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f4f6f8")),
    ]))
    story += [table, Spacer(1, 8)]
    for heading, paras in doc["sections"]:
        story.append(Paragraph(heading, H_SEC))
        story += [Paragraph(p, BODY) for p in paras]
    story += [Spacer(1, 14), Paragraph(
        f"Internal document. Approved by the Head of {doc['dept']}. "
        "Queries: helpdesk@kestrel.example", FOOT)]
    SimpleDocTemplate(str(path), pagesize=A4, title=doc["title"], author=COMPANY,
                      leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=18 * mm, bottomMargin=18 * mm).build(story)
    return path


def main() -> None:
    docs_dir = HERE / "docs"
    upload_dir = docs_dir / "to-upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for doc in DOCS:
        path = build(doc, docs_dir if doc["preload"] else upload_dir)
        print(f"{'preload' if doc['preload'] else 'UPLOAD '}  {path.relative_to(HERE)}")


if __name__ == "__main__":
    main()
