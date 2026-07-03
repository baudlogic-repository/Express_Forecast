import pandas as pd
from fabric_connector import fetch_inventory_data

import os
from dotenv import load_dotenv
load_dotenv()
conn_str = os.getenv("FABRIC_CONNECTION_STRING", "")

print("Fetching inventory...")
express = fetch_inventory_data(conn_str)

df = express.copy()
print("pi_current_mo_sales sum:", df['pi_current_mo_sales'].astype(float).sum())
print("pi_sales_history_02 sum:", df['pi_sales_history_02'].astype(float).sum())
print("pi_sales_history_03 sum:", df['pi_sales_history_03'].astype(float).sum())

match = df[df['pi_part_no'] == '009160']
if not match.empty:
    print("\nPart 009160:")
    print("Current mo:", match['pi_current_mo_sales'].values[0])
    print("History 02:", match['pi_sales_history_02'].values[0])
    print("History 03:", match['pi_sales_history_03'].values[0])
