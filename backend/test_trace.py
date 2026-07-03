import os
import sys
import pandas as pd

from fabric_connector import fetch_inventory_data

from dotenv import load_dotenv
load_dotenv()
conn_str = os.getenv("FABRIC_CONNECTION_STRING", "")

print("Fetching data...")
express = fetch_inventory_data(conn_str)

print("Vendor slicer in express:", 'vendor_slicer' in express.columns)
# Check 6688
match = express[express['pi_vendor_code'].astype(str).str.contains('6688', na=False)]
if not match.empty:
    print("Match found! Count:", len(match))
    print("vendor_slicer =", match['vendor_slicer'].iloc[0])
else:
    print("6688 not found in express_inv")
