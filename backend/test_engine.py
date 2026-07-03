import pandas as pd
from engine import run_forecast_logic
from fabric_connector import fetch_inventory_data

import os
from dotenv import load_dotenv
load_dotenv()
conn_str = os.getenv("FABRIC_CONNECTION_STRING", "")

print("Fetching inventory...")
express, other = fetch_inventory_data(conn_str)

print("Loading lead times...")
lt_file = "../Vendor Lead Times 231215 BN - updated W9-29-2025.xlsx"
lt_df = pd.read_excel(lt_file)
# Mimic main.py
lt_df.rename(columns={'Lead Time': 'Lead Time Days'}, inplace=True)

print("Running engine...")
final_json, stats = run_forecast_logic([express], lt_df)

print("Checking final json...")
import json
data = json.loads(final_json)
match = [x for x in data if str(x.get('Vendor Code')) == '6688']
if match:
    print("Found 6688!")
    print("Vendor:", match[0].get('Vendor'))
else:
    print("6688 not found in final output")
