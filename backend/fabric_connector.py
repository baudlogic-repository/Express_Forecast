import pandas as pd
import pyodbc
import os

def fetch_inventory_data(connection_string: str = None):
    """
    Connects to Microsoft Fabric SQL Analytics Endpoint and fetches inventory data.
    Returns a single DataFrame containing Branch 01 inventory.
    """
    if not connection_string:
        raise ValueError("No connection string provided.")
    query_parts = "SELECT * FROM JS_jdis_Part_Information WHERE PI_Branch = '01'"
    query_vendors = "SELECT ACC_NO, Vendor_Slicer FROM JS_Vendor_List"
    try:
        print("Connecting to Fabric SQL Analytics Endpoint...")
        conn = pyodbc.connect(connection_string)
        print("Executing queries...")
        parts_df = pd.read_sql(query_parts, conn)
        vendors_df = pd.read_sql(query_vendors, conn)
        conn.close()
        
        # Lowercase columns
        parts_df.columns = [str(c).lower() for c in parts_df.columns]
        vendors_df.columns = [str(c).lower() for c in vendors_df.columns]
        
        # Ensure consistent types for joining
        if 'pi_vendor_code' in parts_df.columns and 'acc_no' in vendors_df.columns:
            parts_df['pi_vendor_code_clean'] = pd.to_numeric(parts_df['pi_vendor_code'], errors='coerce').fillna(0).astype(int)
            vendors_df['acc_no_clean'] = pd.to_numeric(vendors_df['acc_no'], errors='coerce').fillna(0).astype(int)
            
            df = parts_df.merge(vendors_df[['acc_no_clean', 'vendor_slicer']], left_on='pi_vendor_code_clean', right_on='acc_no_clean', how='left')
            df.drop(columns=['pi_vendor_code_clean', 'acc_no_clean'], inplace=True, errors='ignore')
        else:
            df = parts_df
        
        if 'pi_branch' not in df.columns:
            raise KeyError(f"'pi_branch' column not found in Fabric. Available columns are: {list(df.columns)}")
            
        df['pi_branch'] = df['pi_branch'].astype(str).str.strip()
        
        return df
    except Exception as e:
        print(f"Error querying Fabric: {e}")
        raise e

