import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*]')
LIST_URL = "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectDocByItemIdAndChild"
DETAIL_URL = "https://www.nfra.gov.cn/cbircweb/DocInfo/SelectByDocId"


def make_pdf_filename(publish_date, title, doc_id, existing_names):
    short_title = WINDOWS_INVALID.sub("", title)[:10].rstrip(" .") or str(doc_id)
    date_part = publish_date.replace("-", "")
    filename = f"{date_part}-{short_title}.pdf"
    if filename.casefold() in {name.casefold() for name in existing_names}:
        filename = f"{date_part}-{short_title}-{doc_id}.pdf"
    return filename


def select_documents(rows, target_date):
    return [row for row in rows if str(row.get("publishDate", "")).split(" ", 1)[0] == target_date]


def _clean_text(value):
    value = value.translate(str.maketrans({
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
    }))
    value = " ".join(value.split())
    value = re.sub(r"(?<=\w)\s*'\s*(?=\w)", "'", value)
    value = re.sub(r'"\s+([^\"]*?)\s+"', r'"\1"', value)
    value = re.sub(r"\s*-\s*", "-", value)
    return re.sub(r"\s+([,.;:!?])", r"\1", value)


def extract_document(payload, doc_id):
    soup = BeautifulSoup(payload.get("docClob") or "", "html.parser")
    paragraphs = []
    for node in soup.find_all(["p", "li"]):
        text = _clean_text(node.get_text(" ", strip=True))
        if text and text not in paragraphs:
            paragraphs.append(text)
    if not paragraphs:
        fallback = " ".join(soup.get_text(" ", strip=True).split())
        if fallback:
            paragraphs.append(fallback)
    if not paragraphs:
        raise ValueError(f"NFRA document {doc_id} has an empty body")
    links = []
    for link in soup.find_all("a", href=True):
        label = " ".join(link.get_text(" ", strip=True).split()) or link["href"]
        links.append((label, urljoin("https://www.nfra.gov.cn/", link["href"])))
    return {
        "doc_id": int(doc_id),
        "title": _clean_text(payload.get("docTitle") or payload.get("docSubtitle") or f"NFRA document {doc_id}"),
        "publish_date": str(payload.get("publishDate", "")).split(" ", 1)[0],
        "paragraphs": paragraphs,
        "links": links,
        "source_url": f"https://www.nfra.gov.cn/en/view/pages/ItemDetail.html?docId={doc_id}&itemId=981",
    }


def resolve_notebook_id(payload, title):
    if isinstance(payload, dict):
        notebooks = payload.get("notebooks") or payload.get("items") or []
    else:
        notebooks = payload if isinstance(payload, list) else []
    for notebook in notebooks:
        if notebook.get("title") == title or notebook.get("name") == title:
            return notebook.get("id") or notebook.get("notebook_id") or notebook.get("notebookId")
    raise RuntimeError(f"Notebook '{title}' not found")


def build_upload_commands(pdf_path, notebook_id, title, source_id):
    add = [
        "notebooklm", "source", "add", "--json", "--notebook", notebook_id,
        "--type", "file", "--title", title, str(Path(pdf_path)),
    ]
    wait = [
        "notebooklm", "source", "wait", source_id, "--notebook", notebook_id,
        "--timeout", "180", "--interval", "2", "--json",
    ]
    return add, wait


def is_synced(state, doc_id):
    return state.get("documents", {}).get(str(doc_id), {}).get("status") == "uploaded"


def parse_source_id(payload):
    if not isinstance(payload, dict):
        raise RuntimeError("NotebookLM source add returned invalid JSON")
    source = payload.get("source") if isinstance(payload.get("source"), dict) else payload
    source_id = source.get("id") or source.get("source_id") or source.get("sourceId")
    if not source_id:
        raise RuntimeError("NotebookLM source add response did not include a source ID")
    return source_id


def _pdf_font_name():
    font_name = "Arial"
    if font_name not in pdfmetrics.getRegisteredFontNames():
        font_path = Path("C:/Windows/Fonts/arial.ttf")
        if font_path.exists():
            pdfmetrics.registerFont(TTFont(font_name, str(font_path)))
        else:
            font_name = "Helvetica"
    return font_name


def write_pdf(document, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_name = _pdf_font_name()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "NFRA Title", parent=styles["Title"], fontName=font_name,
        fontSize=18, leading=23, textColor=colors.HexColor("#17365D"),
        spaceAfter=8 * mm,
    )
    meta_style = ParagraphStyle(
        "NFRA Meta", parent=styles["BodyText"], fontName=font_name,
        fontSize=9, leading=13, textColor=colors.HexColor("#555555"),
        spaceAfter=2 * mm,
    )
    body_style = ParagraphStyle(
        "NFRA Body", parent=styles["BodyText"], fontName=font_name,
        fontSize=10.5, leading=16, textColor=colors.HexColor("#222222"),
        spaceAfter=4 * mm,
    )
    footer_style = ParagraphStyle(
        "NFRA Footer", parent=styles["BodyText"], fontName=font_name,
        fontSize=8, leading=10, alignment=TA_CENTER, textColor=colors.HexColor("#777777"),
    )
    story = [
        Paragraph(escape(document["title"]), title_style),
        Paragraph(f"Publication date: {escape(document['publish_date'])}", meta_style),
        Paragraph(f"NFRA document ID: {escape(str(document['doc_id']))}", meta_style),
        Paragraph(f"Source: <link href=\"{escape(document['source_url'])}\" color=\"#1A5FB4\">{escape(document['source_url'])}</link>", meta_style),
        Spacer(1, 4 * mm),
    ]
    for raw_paragraph in document["paragraphs"]:
        normalized = raw_paragraph.replace("\u00a0", " ").replace("\u2011", "-")
        story.append(Paragraph(escape(normalized), body_style))
    if document.get("links"):
        story.extend([Spacer(1, 2 * mm), Paragraph("Referenced links", body_style)])
        for label, url in document["links"]:
            story.append(Paragraph(f"<link href=\"{escape(url)}\" color=\"#1A5FB4\">{escape(label)}</link>", meta_style))

    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        rightMargin=22 * mm, leftMargin=22 * mm,
        topMargin=20 * mm, bottomMargin=18 * mm,
        title=document["title"], author="National Financial Regulatory Administration",
    )

    def add_footer(canvas, pdf_doc):
        canvas.saveState()
        footer = Paragraph(f"NFRA Rules and Regulations - Page {pdf_doc.page}", footer_style)
        width, height = footer.wrap(A4[0] - 44 * mm, 10 * mm)
        footer.drawOn(canvas, 22 * mm, 8 * mm)
        canvas.restoreState()

    doc.build(story, onFirstPage=add_footer, onLaterPages=add_footer)
    return output_path


def request_json(url, params):
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": "Mozilla/5.0 NFRA-NotebookLM-Sync/1.0"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def run_json_command(args):
    completed = subprocess.run(
        args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(args)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"command returned invalid JSON: {' '.join(args)}\n{completed.stdout}") from exc


def load_state(path):
    path = Path(path)
    if not path.exists():
        return {"version": 1, "documents": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    state.setdefault("version", 1)
    state.setdefault("documents", {})
    return state


def save_state(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp_path.replace(path)


def _nfra_data(payload, label):
    if not isinstance(payload, dict) or payload.get("rptCode") != 200 or payload.get("data") is None:
        raise RuntimeError(f"NFRA {label} returned an invalid response")
    return payload["data"]


def run_sync(
    target_date,
    output_dir,
    state_path,
    notebook_title="NFRA",
    upload=True,
    force=False,
    http_get_json=request_json,
    command_runner=run_json_command,
):
    output_dir = Path(output_dir).resolve()
    state_path = Path(state_path).resolve()
    listing = _nfra_data(
        http_get_json(LIST_URL, {"itemId": 981, "pageSize": 18, "pageIndex": 1}),
        "listing",
    )
    rows = listing.get("rows") if isinstance(listing, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("NFRA listing response did not contain rows")
    selected = select_documents(rows, target_date)
    counts = {"matched": len(selected), "generated": 0, "uploaded": 0, "skipped": 0, "failed": 0}
    result = {
        "status": "completed",
        "target_date": target_date,
        "mode": "upload" if upload else "generate-only",
        "notebook": {"title": notebook_title, "id": None},
        "output_dir": str(output_dir),
        "state_file": str(state_path),
        "counts": counts,
        "entries": [],
    }
    if not selected:
        return result

    state = load_state(state_path)
    notebook_id = None
    if upload:
        notebook_id = resolve_notebook_id(command_runner(["notebooklm", "list", "--json", "--no-truncate"]), notebook_title)
        result["notebook"]["id"] = notebook_id

    output_dir.mkdir(parents=True, exist_ok=True)
    existing_names = {path.name for path in output_dir.glob("*.pdf")}
    for row in selected:
        doc_id = row.get("docId")
        title = row.get("docTitle") or row.get("docSubtitle") or f"NFRA document {doc_id}"
        if not doc_id:
            counts["failed"] += 1
            result["entries"].append({"status": "failed", "title": title, "error": "NFRA row is missing docId"})
            continue
        if is_synced(state, doc_id) and not force:
            counts["skipped"] += 1
            result["entries"].append({"status": "skipped", "doc_id": doc_id, "title": title, "reason": "already uploaded"})
            continue
        entry = {"doc_id": doc_id, "title": title}
        try:
            detail_payload = _nfra_data(http_get_json(DETAIL_URL, {"docId": doc_id}), f"detail {doc_id}")
            document = extract_document(detail_payload, doc_id)
            previous_path = state.get("documents", {}).get(str(doc_id), {}).get("pdf_path")
            names_for_collision = set(existing_names)
            if previous_path:
                names_for_collision.discard(Path(previous_path).name)
            filename = make_pdf_filename(document["publish_date"], document["title"], doc_id, names_for_collision)
            pdf_path = write_pdf(document, output_dir / filename)
            existing_names.add(pdf_path.name)
            counts["generated"] += 1
            state["documents"][str(doc_id)] = {
                "status": "generated",
                "title": document["title"],
                "publish_date": document["publish_date"],
                "source_url": document["source_url"],
                "pdf_path": str(pdf_path),
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            }
            save_state(state_path, state)
            entry.update({"status": "generated", "pdf_path": str(pdf_path)})
            if upload:
                add_command, _ = build_upload_commands(pdf_path, notebook_id, document["title"], "")
                source_id = parse_source_id(command_runner(add_command))
                _, wait_command = build_upload_commands(pdf_path, notebook_id, document["title"], source_id)
                command_runner(wait_command)
                state["documents"][str(doc_id)].update({
                    "status": "uploaded",
                    "notebook_title": notebook_title,
                    "notebook_id": notebook_id,
                    "source_id": source_id,
                    "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                })
                save_state(state_path, state)
                counts["uploaded"] += 1
                entry.update({"status": "uploaded", "source_id": source_id})
        except Exception as exc:
            counts["failed"] += 1
            entry.update({"status": "failed", "error": str(exc)})
        result["entries"].append(entry)
    if counts["failed"]:
        result["status"] = "partial_failure"
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sync NFRA English Rules and Regulations to NotebookLM as PDFs.")
    parser.add_argument("--target-date", help="Publication date to process (YYYY-MM-DD). Defaults to today in Asia/Shanghai.")
    parser.add_argument("--output-dir", default=str(Path.cwd() / "output" / "pdf"))
    parser.add_argument("--state-file", default=str(Path.cwd() / ".runtime" / "nfra-sync-state.json"))
    parser.add_argument("--notebook-title", default="NFRA")
    parser.add_argument("--no-upload", action="store_true", help="Generate PDFs without uploading to NotebookLM.")
    parser.add_argument("--force", action="store_true", help="Regenerate and re-upload documents already marked uploaded.")
    args = parser.parse_args(argv)
    target_date = args.target_date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    result = run_sync(
        target_date=target_date,
        output_dir=args.output_dir,
        state_path=args.state_file,
        notebook_title=args.notebook_title,
        upload=not args.no_upload,
        force=args.force,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["counts"]["failed"] else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
