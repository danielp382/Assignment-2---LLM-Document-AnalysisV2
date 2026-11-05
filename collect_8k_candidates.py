# CAP5619 - Assignment 2: LLM Document Analysis
# Find SEC 8-K documents that mention new product launches.
# Download their text and add them to filings_to_analyze.csv.
# These are CANDIDATES, not confirmed product announcements.

import csv
import json
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Replace the sample email with your own, as in your existing script.
SEC_USER_AGENT = "CAP5619 Student Research da334356@ucf.edu"

# Adjust this number to discover more documents. Not every filing has a product.
MAX_DOCUMENTS = 250
START_DATE = "2021-01-01"
END_DATE = "2026-11-04"

# We use several searches because companies describe product launches differently.
SEARCH_TERMS = [
    '"commercial launch"',
    '"new product launch"',
    '"announced the launch"',
    '"announces the launch"',
    '"launch of its"',
    '"launches its"',
    '"introduces new"',
    '"new product"',
    '"product introduction"',
    '"product launch"',
]

folder = Path(__file__).parent
text_folder = folder / "sec_documents"
manifest_file = folder / "filings_to_analyze.csv"
source_file = folder / "candidate_sources.csv"


class HTMLText(HTMLParser):
    """Remove HTML tags while keeping readable text."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag in ("p", "div", "br", "tr", "td", "li"):
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1
        elif tag in ("p", "div", "tr", "li"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def sec_request(url, json_response=False):
    # Slow the requests to stay well below SEC's published 10/second limit.
    headers = {
        "User-Agent": SEC_USER_AGENT,
        "Accept": "application/json" if json_response else "text/html,*/*",
        "Accept-Encoding": "identity",
    }
    for attempt in range(3):
        try:
            time.sleep(0.4)
            with urlopen(Request(url, headers=headers), timeout=35) as response:
                data = response.read()
            if json_response:
                return json.loads(data.decode("utf-8-sig"))
            return data.decode("utf-8", errors="replace")
        except (HTTPError, URLError, TimeoutError) as error:
            print("SEC request issue:", error)
            if attempt == 2:
                raise
            time.sleep(3 * (attempt + 1))


def clean_text(raw):
    if "<html" in raw.lower() or "<div" in raw.lower():
        parser = HTMLText()
        parser.feed(raw)
        raw = " ".join(parser.parts)
    raw = re.sub(r"[\t\r ]+", " ", raw)
    raw = re.sub(r"\n\s*\n+", "\n", raw)
    return raw.strip()


def relevant_text(text):
    # Small press releases usually fit. For longer documents, collect
    # context around product-launch language instead of sending 100K+ chars.
    if len(text) <= 17000:
        return text
    pattern = re.compile(
        r"commercial launch|new product|product launch|"
        r"announc\w*.{0,30}launch|launch\w*.{0,30}product|"
        r"introduc\w*.{0,30}product",
        re.IGNORECASE,
    )
    pieces = [text[:2200]]
    for match in list(pattern.finditer(text))[:15]:
        a = max(0, match.start() - 500)
        b = min(len(text), match.end() + 1300)
        pieces.append(text[a:b])
    return "\n...\n".join(pieces)[:17000]


def search_documents(term, offset):
    params = urlencode({
        "q": term,
        "forms": "8-K",
        "dateRange": "custom",
        "startdt": START_DATE,
        "enddt": END_DATE,
        "from": offset,
    })
    url = "https://efts.sec.gov/LATEST/search-index?" + params
    return sec_request(url, json_response=True).get("hits", {}).get("hits", [])


def main():
    if "your-email@example.com" in SEC_USER_AGENT:
        raise SystemExit("Replace your-email@example.com with your email first.")

    text_folder.mkdir(exist_ok=True)
    manifest_rows = []
    source_rows = []
    seen = set()

    # Keep any documents already added, including our Microsoft/TELA tests.
    if manifest_file.exists():
        with open(manifest_file, encoding="utf-8-sig", newline="") as file:
            manifest_rows = list(csv.DictReader(file))
        for row in manifest_rows:
            seen.add(row.get("accession_number", ""))

    if source_file.exists():
        with open(source_file, encoding="utf-8-sig", newline="") as file:
            source_rows = list(csv.DictReader(file))

    added = 0
    for term in SEARCH_TERMS:
        if added >= MAX_DOCUMENTS:
            break
        print("\nSearching:", term)
        # Search several pages for each phrase (the SEC typically returns
        # at most 100 matches per page).
        for offset in (0, 100, 200, 300):
            if added >= MAX_DOCUMENTS:
                break
            try:
                hits = search_documents(term, offset)
            except (HTTPError, URLError, TimeoutError, ValueError) as error:
                print("Could not search SEC:", error)
                break
            if not hits:
                break

            # Prefer press-release exhibits rather than earnings-only 8-K text.
            hits.sort(key=lambda h: not str(
                h.get("_source", {}).get("file_type", "")
            ).upper().startswith("EX-99"))

            for hit in hits:
                if added >= MAX_DOCUMENTS:
                    break
                source = hit.get("_source", {})
                accession = source.get("adsh", "")
                ciks = source.get("ciks", [])
                identifier = hit.get("_id", "")
                if (source.get("form") != "8-K" or not accession
                        or not ciks or ":" not in identifier
                        or accession in seen):
                    continue

                _, original_filename = identifier.split(":", 1)
                if not original_filename.lower().endswith((".htm", ".html", ".txt")):
                    continue

                cik = str(ciks[0]).zfill(10)
                archive_path = accession.replace("-", "")
                sec_url = (
                    f"https://www.sec.gov/Archives/edgar/data/"
                    f"{int(cik)}/{archive_path}/{original_filename}"
                )
                try:
                    html = sec_request(sec_url)
                    text = clean_text(html)
                    if len(text) < 300:
                        continue
                    # Eliminate common non-product hits before querying LLaMA.
                    if not re.search(
                        r"launch|introduc|new product", text, re.IGNORECASE
                    ):
                        continue
                    text = relevant_text(text)
                except (HTTPError, URLError, TimeoutError, ValueError) as error:
                    print("Skipped SEC document:", error)
                    continue

                saved_name = f"sec_documents/{archive_path}.txt"
                (folder / saved_name).write_text(text, encoding="utf-8")
                manifest_rows.append({
                    "filename": saved_name,
                    "cik": cik,
                    "accession_number": accession,
                })
                source_rows.append({
                    "filename": saved_name,
                    "accession_number": accession,
                    "sec_document_url": sec_url,
                    "search_term": term,
                })
                seen.add(accession)
                added += 1
                print(f"Added {added}: {accession} ({len(text)} characters)")

                # Save progress even if a later SEC request fails.
                with open(manifest_file, "w", encoding="utf-8-sig", newline="") as file:
                    writer = csv.DictWriter(
                        file, fieldnames=["filename", "cik", "accession_number"]
                    )
                    writer.writeheader()
                    writer.writerows(manifest_rows)
                with open(source_file, "w", encoding="utf-8-sig", newline="") as file:
                    writer = csv.DictWriter(file, fieldnames=[
                        "filename", "accession_number", "sec_document_url", "search_term"
                    ])
                    writer.writeheader()
                    writer.writerows(source_rows)

    print("\nCandidate documents newly collected:", added)
    print("Total documents in manifest:", len(manifest_rows))
    print("Next run: python assignment2_final.py")
    print("Candidates must still be checked by the LLaMA model.")


if __name__ == "__main__":
    main()
