#!/usr/bin/env python3
"""Download the IMF PDFs listed in the corpus JSON.

Most entries point to an IMF landing page, not to the PDF itself. For each
document the script uses `direct_pdf_url` when present, otherwise it fetches
the landing page and picks the first PDF link it finds (imf.org
"/-/media/files/..." links, or eLibrary "/downloadpdf/..." links).

Usage:
    python3 scripts/download_imf_pdfs.py [corpus.json] [output_dir]

Files are saved as DOCxxx_<slug>.pdf. Already-downloaded files are skipped,
and a report (download_report.json) lists what failed and why.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PDF_LINK = re.compile(
    r'href="([^"]+?(?:\.pdf|\.ashx|/downloadpdf/[^"]+))"', re.IGNORECASE)


def fetch(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.geturl(), resp.headers.get("Content-Type", ""), resp.read()


def is_pdf(data):
    return data[:5] == b"%PDF-"


def candidate_pdf_urls(doc):
    if doc.get("direct_pdf_url"):
        yield doc["direct_pdf_url"]
    url = doc["official_url"]
    if url.lower().endswith(".pdf"):
        yield url
        return
    # eLibrary: the PDF usually sits at the same path under /downloadpdf/
    if "elibrary.imf.org/view/" in url:
        yield url.replace("/view/", "/downloadpdf/view/").replace(".xml", ".pdf")
    final_url, _, html = fetch(url)
    seen = set()
    for href in PDF_LINK.findall(html.decode("utf-8", "replace")):
        full = urllib.parse.urljoin(final_url, href.replace("&amp;", "&"))
        # skip cover images, translated summaries, etc. but keep order
        if full not in seen:
            seen.add(full)
            yield full


def slug(text, n=70):
    s = re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")
    return s[:n].rstrip("-")


def main():
    corpus = Path(sys.argv[1] if len(sys.argv) > 1
                  else "data/corpus_fmi_fiscalite_afrique_extraction.json")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else "pdfs")
    out.mkdir(parents=True, exist_ok=True)
    docs = json.loads(corpus.read_text(encoding="utf-8"))["documents"]

    report = []
    for doc in docs:
        target = out / f"{doc['document_id']}_{slug(doc['title'])}.pdf"
        entry = {"document_id": doc["document_id"], "title": doc["title"],
                 "official_url": doc["official_url"], "file": str(target)}
        if target.exists() and target.stat().st_size > 0:
            entry["status"] = "already_present"
            report.append(entry)
            continue
        errors = []
        try:
            for pdf_url in candidate_pdf_urls(doc):
                try:
                    _, _, data = fetch(pdf_url, timeout=180)
                except (urllib.error.URLError, TimeoutError) as e:
                    errors.append(f"{pdf_url}: {e}")
                    continue
                if is_pdf(data):
                    target.write_bytes(data)
                    entry.update(status="downloaded", pdf_url=pdf_url,
                                 bytes=len(data))
                    break
                errors.append(f"{pdf_url}: not a PDF")
            else:
                entry["status"] = "no_pdf_found"
        except (urllib.error.URLError, TimeoutError) as e:
            errors.append(f"landing page: {e}")
            entry["status"] = "landing_page_error"
        if errors and entry.get("status") != "downloaded":
            entry["errors"] = errors
        print(f"{doc['document_id']}  {entry['status']:<20} {doc['title'][:60]}")
        report.append(entry)
        time.sleep(1)  # be polite to imf.org

    (out / "download_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(r["status"] in ("downloaded", "already_present") for r in report)
    print(f"\n{ok}/{len(report)} PDFs available in {out}/ "
          f"(details in {out}/download_report.json)")


if __name__ == "__main__":
    main()
