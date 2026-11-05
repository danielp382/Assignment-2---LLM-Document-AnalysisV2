# CAP5619 - Assignment 2: LLM Document Analysis
# Analyze many downloaded SEC 8-K documents with the local Ollama model.
# Continue from previous results and save the CSV after each document.

import csv
import json
import re
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen

# Use the same identifying email you used in your earlier SEC tests.
SEC_USER_AGENT = "CAP5619 Student Research da334356@ucf.edu"
MODEL_NAME = "llama3.2:3b"
TARGET_ROWS = 100

folder = Path(__file__).parent
manifest_file = folder / "filings_to_analyze.csv"
output_file = folder / "product_announcements.csv"
review_file = folder / "review_log.csv"

column_names = [
    "company_name", "stock_name", "filing_time",
    "new_product", "product_description"
]
log_names = ["filename", "cik", "accession_number", "status", "reason"]
company_cache = {}


def load_csv(path):
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, column_names, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=column_names)
        writer.writeheader()
        writer.writerows(rows)


def read_sec_json(url):
    request = Request(url, headers={
        "User-Agent": SEC_USER_AGENT,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    })
    time.sleep(0.4)
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def get_metadata(cik, accession):
    # SEC submission files provide the actual filing acceptance timestamp.
    cik = cik.zfill(10)
    if cik not in company_cache:
        company_cache[cik] = read_sec_json(
            f"https://data.sec.gov/submissions/CIK{cik}.json"
        )
    info = company_cache[cik]
    tickers = info.get("tickers", [])
    if not tickers:
        raise ValueError("No stock ticker listed for this SEC company")

    filings = info["filings"]
    blocks = [filings["recent"]]

    for block in blocks:
        if accession in block.get("accessionNumber", []):
            index = block["accessionNumber"].index(accession)
            return {
                "company_name": info["name"],
                "stock_name": tickers[0],
                "filing_time": block["acceptanceDateTime"][index],
            }

    # Older filings may have moved out of the 'recent' block.
    for older in filings.get("files", []):
        older_block = read_sec_json(
            "https://data.sec.gov/submissions/" + older["name"]
        )
        if accession in older_block.get("accessionNumber", []):
            index = older_block["accessionNumber"].index(accession)
            return {
                "company_name": info["name"],
                "stock_name": tickers[0],
                "filing_time": older_block["acceptanceDateTime"][index],
            }

    raise ValueError("Accession number not found in SEC submissions")


def analyze_document(document_text):
    # Keep the prompt similar to our original working test.
    prompt = f"""
You are analyzing an SEC Form 8-K filing or an exhibit.
Determine whether it EXPLICITLY announces the launch or introduction
of a new product. Do not count earnings, financial changes,
partnerships, general company announcements, or existing products.
Do not invent product names or features. If there is a real launch,
use the exact product name and a factual description under 180 characters.
If there is not, put N/A for the product name and description.

Return exactly these four lines:
New Product Announced: Yes or No
Product Name: Name or N/A
Product Description: Description or N/A
Reason: One brief explanation

SEC DOCUMENT:
{document_text}
"""
    result = subprocess.run(
        ["ollama", "run", MODEL_NAME],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Ollama error")

    fields = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def main():
    if "your-email@example.com" in SEC_USER_AGENT:
        raise SystemExit("Replace the sample email in assignment2_bulk.py first.")
    inputs = load_csv(manifest_file)
    if not inputs:
        raise SystemExit("No input documents in filings_to_analyze.csv")

    results = load_csv(output_file)
    reviews = load_csv(review_file)
    done = {
        r.get("filename", "")
        for r in reviews
        if r.get("status") in ("SAVED", "NO PRODUCT", "INVALID RESULT", "DUPLICATE")
    }
    saved_products = {
        (r.get("stock_name", "").upper(),
         re.sub(r"\W+", "", r.get("new_product", "").lower()))
        for r in results
    }

    print("Input documents:", len(inputs))
    print("Product rows already saved:", len(results))

    try:
        for number, item in enumerate(inputs, start=1):
            if len(results) >= TARGET_ROWS:
                break
            name = item["filename"].strip()
            cik = item["cik"].strip()
            accession = item["accession_number"].strip()
            if name in done:
                continue

            print(f"\nDocument {number}/{len(inputs)}: {name}", flush=True)
            status = "ERROR"
            reason = ""
            try:
                path = folder / name
                if not path.is_file():
                    raise FileNotFoundError(name)
                document = path.read_text(encoding="utf-8")
                fields = analyze_document(document)
                answer = fields.get("New Product Announced", "").lower().strip()
                name_of_product = fields.get("Product Name", "").strip()
                description = fields.get("Product Description", "").strip()
                reason = fields.get("Reason", "")

                if answer == "no":
                    status = "NO PRODUCT"
                elif (answer != "yes" or not name_of_product
                      or name_of_product.upper() == "N/A"
                      or not description or description.upper() == "N/A"
                      or len(description) >= 180):
                    status = "INVALID RESULT"
                else:
                    sec = get_metadata(cik, accession)
                    key = (
                        sec["stock_name"].upper(),
                        re.sub(r"\W+", "", name_of_product.lower())
                    )
                    if key in saved_products:
                        status = "DUPLICATE"
                    else:
                        results.append({
                            "company_name": sec["company_name"],
                            "stock_name": sec["stock_name"],
                            "filing_time": sec["filing_time"],
                            "new_product": name_of_product,
                            "product_description": description,
                        })
                        saved_products.add(key)
                        status = "SAVED"
                        print("Product:", name_of_product)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
                reason = str(error)
                status = "ERROR"

            reviews = [r for r in reviews if r.get("filename") != name]
            reviews.append({
                "filename": name,
                "cik": cik,
                "accession_number": accession,
                "status": status,
                "reason": reason,
            })
            write_csv(output_file, column_names, results)
            write_csv(review_file, log_names, reviews)
            print("Status:", status, "| Valid CSV rows:", len(results), flush=True)

    except KeyboardInterrupt:
        print("\nStopped manually. The CSV and review log are saved.")

    print("\nTotal valid product records:", len(results))
    print("Output:", output_file.name)
    print("Review log:", review_file.name)
    print("Check LLaMA's Yes results against the original SEC filing before submitting.")


if __name__ == "__main__":
    main()
