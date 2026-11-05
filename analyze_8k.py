
# CAP5619 - Assignment 2: LLM Document Analysis
# Analyze SEC 8-K documents using a local LLaMA model
# Retrieve filing metadata from SEC EDGAR
# Save valid new-product announcements to CSV

import csv
import json
import subprocess
import sys

from pathlib import Path
from urllib.request import Request, urlopen


# --------------------------------------------------
# Step 1 - Identify the document to analyze
# --------------------------------------------------

if len(sys.argv) != 2:
    raise SystemExit(
        "Usage: python analyze_8k.py filename.txt"
    )

filename = sys.argv[1]

# Look for the document in the same folder as this script
file_path = Path(__file__).with_name(filename)

if not file_path.is_file():
    raise SystemExit(
        f"File not found: {filename}"
    )


# --------------------------------------------------
# Step 2 - Read the SEC document
# --------------------------------------------------

document_text = file_path.read_text(
    encoding="utf-8"
)

print("Source file:", filename)
print("Document characters:", len(document_text))


# --------------------------------------------------
# Step 3 - Create the instructions for LLaMA
# --------------------------------------------------

prompt = f"""
You are analyzing an SEC Form 8-K filing or an exhibit
attached to an SEC Form 8-K.

Your task is to identify whether the document explicitly
announces the launch or introduction of a new product.

Follow these rules:

1. Only answer Yes if there is clear evidence that a
   company announced a new product.

2. Do not count financial reporting changes, earnings,
   business agreements, or ordinary company updates
   as new-product announcements.

3. Do not count an existing product as new unless
   the document explicitly announces a new version
   or a new launch.

4. Do not invent product names or product features.

5. Use the product name stated in the document.

6. If a new product is announced, write a short,
   factual product description under 180 characters.

7. If no new product is announced, use N/A for
   the product name and description.

8. Base your answer only on the document provided.

Return the answer using exactly these four fields:

New Product Announced: Yes or No
Product Name: Product name or N/A
Product Description: Description or N/A
Reason: Brief explanation

Do not add extra headings or commentary.

SEC DOCUMENT:

{document_text}
"""


# --------------------------------------------------
# Step 4 - Send the document to the local LLaMA model
# --------------------------------------------------

try:
    result = subprocess.run(
        ["ollama", "run", "llama3.2:3b"],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180
    )

except subprocess.TimeoutExpired:
    raise SystemExit(
        "Ollama timed out while analyzing the document."
    )

print("\nOllama return code:", result.returncode)

if result.returncode != 0:
    print("Ollama error:", result.stderr)
    raise SystemExit("LLM analysis failed.")


# --------------------------------------------------
# Step 5 - Display the LLaMA response
# --------------------------------------------------

print("\nLLM Analysis Result:\n")
print(result.stdout)


# --------------------------------------------------
# Step 6 - Extract structured information
# --------------------------------------------------

extracted_data = {}

required_fields = [
    "New Product Announced",
    "Product Name",
    "Product Description"
]

for line in result.stdout.splitlines():

    key, separator, value = line.partition(":")

    if separator and key.strip() in required_fields:
        extracted_data[key.strip()] = value.strip()


print("\nStructured Extraction Results:\n")

for field in required_fields:
    print(
        field + ":",
        extracted_data.get(field, "MISSING")
    )

fields_complete = all(
    extracted_data.get(field)
    for field in required_fields
)

print("\nRequired fields present:", fields_complete)


# --------------------------------------------------
# Step 7 - Validate the product description
# --------------------------------------------------

description = extracted_data.get(
    "Product Description", ""
).strip()

if not description:
    print("\nDescription validation: Missing field")

elif description.upper() == "N/A":
    print("\nDescription validation: Not applicable")

else:
    print("\nDescription characters:", len(description))
    print("Under 180 characters:", len(description) < 180)


# --------------------------------------------------
# Step 8 - Identify a valid new-product announcement
# --------------------------------------------------

announced = extracted_data.get(
    "New Product Announced", ""
).strip().lower()

product = extracted_data.get(
    "Product Name", ""
).strip()

valid_product = (
    fields_complete
    and announced == "yes"
    and product.upper() != "N/A"
    and description.upper() != "N/A"
    and len(description) < 180
)

if not valid_product:
    print(
        "\nCSV skipped: No valid new-product "
        "announcement was extracted."
    )
    sys.exit(0)


# --------------------------------------------------
# Step 9 - Identify the SEC filing for our test
# --------------------------------------------------

# We are currently testing only the verified TELA Bio filing.
# Later, these identifiers will be determined automatically.

if filename == "TELA_Bio_2023-08-16_Ex99_1.txt":

    cik = "0001561921"
    accession_number = "0001104659-23-092205"

else:
    print(
        "\nCSV skipped: SEC metadata has not yet "
        "been configured for this document."
    )
    sys.exit(0)


# --------------------------------------------------
# Step 10 - Retrieve filing metadata from SEC EDGAR
# --------------------------------------------------

sec_url = (
    f"https://data.sec.gov/submissions/CIK{cik}.json"
)

# IMPORTANT: Replace the email address with your own.
headers = {
    "User-Agent": "CAP5619 Student Research your-email@example.com",
    "Accept": "application/json"
}

request = Request(
    sec_url,
    headers=headers
)

with urlopen(request, timeout=30) as response:
    sec_data = json.load(response)


# --------------------------------------------------
# Step 11 - Find the exact SEC filing
# --------------------------------------------------

recent = sec_data["filings"]["recent"]

try:
    index = recent["accessionNumber"].index(
        accession_number
    )

except ValueError:
    raise SystemExit(
        "Filing not found in recent SEC submissions."
    )


# --------------------------------------------------
# Step 12 - Extract company information
# --------------------------------------------------

company = sec_data["name"]

ticker = sec_data["tickers"][0]

filing_time = recent["acceptanceDateTime"][index]

print("\nSEC Metadata Retrieved:")
print("Company:", company)
print("Ticker:", ticker)
print("Filing timestamp (UTC):", filing_time)
print("Accession Number:", accession_number)


# --------------------------------------------------
# Step 13 - Save the information to a CSV file
# --------------------------------------------------

csv_file = file_path.parent / "tela_llm_test.csv"

with open(
    csv_file,
    "w",
    newline="",
    encoding="utf-8-sig"
) as file:

    writer = csv.writer(file)

    # Required columns from the assignment
    writer.writerow([
        "company_name",
        "stock_name",
        "filing_time",
        "new_product",
        "product_description"
    ])

    # Combine SEC metadata with LLaMA extraction
    writer.writerow([
        company,
        ticker,
        filing_time,
        product,
        description
    ])


# --------------------------------------------------
# Step 14 - Confirm the CSV was created
# --------------------------------------------------

print("\nCSV saved successfully!")
print("Filename:", csv_file.name)
print("Data rows written: 1")
