# Check the CSV output for the five required columns and short descriptions.

import csv
from pathlib import Path

csv_file = Path(__file__).with_name("product_announcements.csv")
required_columns = [
    "company_name", "stock_name", "filing_time",
    "new_product", "product_description"
]

with open(csv_file, "r", encoding="utf-8-sig", newline="") as file:
    reader = csv.DictReader(file)
    columns = reader.fieldnames
    rows = list(reader)

print("Correct columns:", columns == required_columns)
print("Product records:", len(rows))

for number, row in enumerate(rows, start=1):
    complete = all(row.get(column) for column in required_columns)
    short_enough = len(row.get("product_description", "")) < 180
    print("Row", number, "-", row.get("new_product", ""))
    print("  All fields populated:", complete)
    print("  Description under 180 characters:", short_enough)
