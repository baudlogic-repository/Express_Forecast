import pandas as pd
import numpy as np
import os
from datetime import datetime
from sklearn.linear_model import LinearRegression
import sys

# Context manager to silence stdout/stderr
class SilenceOutput:
    def __enter__(self):
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout.close()
        sys.stderr.close()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr

import io

def run_forecast_logic(inventory_dfs, lead_time_df, status_callback=None):
    """
    Consolidated logic for cleaning and forecasting.
    inventory_dfs: List of pandas DataFrames (e.g., [express_inv, other_inv]).
    lead_time_df: pandas DataFrame containing lead time data.
    status_callback: Function to report progress updates.
    Returns: A dictionary with report DataFrames and raw excel file bytes.
    """
    def log(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    log("Starting processing engine...")
    
    # 1. LOAD INVENTORY DATA
    log("Processing inventory data...")
    all_dfs = []
    for i, df in enumerate(inventory_dfs):
        if df.empty:
            continue
        log(f"Cleaning dataset {i+1}...")
        try:
            # Standardize column types
            if 'pi_branch' in df.columns:
                df['pi_branch'] = df['pi_branch'].astype(str).str.strip()
            else:
                # If no branch column, assume it's all branch 01 for fallback
                df['pi_branch'] = '01'
                
            # Force numeric sales
            log(f"   - Standardizing sales data...")
            sales_variants = ['pi_current_mo_sales', 'pi_Current_Mo_Sales']
            for var in sales_variants:
                if var in df.columns:
                    df[var] = pd.to_numeric(df[var], errors='coerce').fillna(0)
            
            if 'pi_Current_Mo_Sales' in df.columns:
                if 'pi_current_mo_sales' not in df.columns:
                    df['pi_current_mo_sales'] = 0
                df['pi_current_mo_sales'] = df['pi_current_mo_sales'] + df['pi_Current_Mo_Sales']
                
            history_cols = [c for c in df.columns if c.startswith('pi_sales_history_')]
            for col in history_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
            all_dfs.append(df)
        except Exception as e:
            log(f"Error cleaning dataset {i+1}: {e}")

    if not all_dfs:
        raise ValueError("No valid inventory data loaded.")

    full_inv = pd.concat(all_dfs, ignore_index=True)
    log(f"Total rows loaded: {len(full_inv)}")

    # 2. LOAD LEAD TIMES
    log("Processing lead times...")
    try:
        lt_df = lead_time_df.copy()
        lt_df.columns = ['Vendor Code', 'Vendor Name', 'Lead Time Days']
    except Exception as e:
        log(f"Warning: Could not process lead time data. Using defaults. Details: {e}")
        lt_df = pd.DataFrame(columns=['Vendor Code', 'Vendor Name', 'Lead Time Days'])

    # 3. AGGREGATION & BRANCH SPLIT
    log("Aggregating sales across branches while isolating Branch 01 inventory...")
    if 'pi_part_no' not in full_inv.columns:
        raise ValueError("Critical Error: 'pi_part_no' column missing from all input files.")
        
    history_cols = sorted([c for c in full_inv.columns if c.startswith('pi_sales_history_')])
    sales_cols_for_agg = ['pi_current_mo_sales'] + history_cols
    
    # 3A. Aggregate sales across ALL branches
    sales_agg_rules = {col: 'sum' for col in sales_cols_for_agg if col in full_inv.columns}
    sales_df = full_inv.groupby('pi_part_no').agg(sales_agg_rules).reset_index()
    
    # 3B. Isolate inventory metrics for Branch 01
    branch_01_df = full_inv[full_inv['pi_branch'] == '01'].copy()
    
    # Drop the original sales columns from Branch 01 so we can merge the aggregated ones cleanly
    branch_01_df.drop(columns=[c for c in sales_cols_for_agg if c in branch_01_df.columns], inplace=True)
    
    # Merge them together (inner join ensures we only keep parts that actually exist in Branch 01)
    full_inv = branch_01_df.merge(sales_df, on='pi_part_no', how='inner')
    
    # Apply Bin Filter specifically to Branch 01
    if 'pi_bin' in full_inv.columns:
        log("   - Cleaning Branch 01 bins...")
        full_inv['pi_bin'] = full_inv['pi_bin'].astype(str).replace(['nan', 'None'], '')
        
        def is_invalid_bin(x):
            s = str(x).strip()
            if not s: return True # Empty bin
            if len(s) > 1 and set(s) == {'*'}: return True # Asterisk-only bin
            return False
            
        exclude_mask = full_inv['pi_bin'].apply(is_invalid_bin)
        full_inv = full_inv[~exclude_mask]
        
    # Apply Active Sales Filter to the newly aggregated company-wide sales
    log("   - Filtering active parts...")
    existing_check_cols = [c for c in sales_cols_for_agg if c in full_inv.columns]
    if existing_check_cols:
        full_inv = full_inv[full_inv[existing_check_cols].sum(axis=1) > 0].copy()
    
    if 'pi_inventory_cost' in full_inv.columns and 'pi_cost' not in full_inv.columns: 
        full_inv['pi_cost'] = full_inv['pi_inventory_cost']

    # 4. AI FORECASTING
    log("Running AI Forecasting (Seasonal Average)...")
    now = datetime.now()
    current_month_idx = now.month

    # Map each history_col to its calendar month (1-12)
    month_mapping = {}
    for i, col in enumerate(history_cols):
        months_ago = i + 1
        cal_month = (current_month_idx - months_ago - 1) % 12 + 1
        if cal_month not in month_mapping: month_mapping[cal_month] = []
        month_mapping[cal_month].append(col)

    def parse_creation_date(date_str):
        if pd.isna(date_str): return None
        try:
            if isinstance(date_str, datetime): return date_str
            return pd.to_datetime(date_str)
        except:
            return None

    def predict_demand_seasonal_avg(row):
        try:
            # 1. Determine valid history columns based on Creation Date
            cdate_col = next((c for c in row.index if c.lower() in ['creation date', 'creation_date', 'pi_creation_date']), None)
            cdate = parse_creation_date(row.get(cdate_col, None)) if cdate_col else None
            
            valid_history_cols = history_cols.copy()
            if cdate:
                months_since_creation = (now.year - cdate.year) * 12 + now.month - cdate.month
                if months_since_creation < 0: months_since_creation = 0
                if months_since_creation < len(history_cols):
                    valid_history_cols = history_cols[:max(1, months_since_creation)]

            y_all = row[valid_history_cols].values.astype(float)
            y_all = np.nan_to_num(y_all)
            
            if np.all(y_all == 0):
                return pd.Series([0] * 12 + ['High'])
                
            max_y = np.max(y_all)
            overall_avg = np.mean(y_all)
            overall_std = np.std(y_all)
            
            # Coefficient of Variation (CV)
            cv = overall_std / overall_avg if overall_avg > 0 else 0
            if cv < 0.75:
                confidence = 'High'
            elif cv < 1.5:
                confidence = 'Medium'
            else:
                confidence = 'Low'
            
            predictions = []
            for future_step in range(1, 13):
                target_cal_month = (current_month_idx + future_step - 1) % 12 + 1
                cols_for_month = [c for c in month_mapping[target_cal_month] if c in valid_history_cols]
                
                if not cols_for_month:
                    pred = overall_avg
                else:
                    y_month = row[cols_for_month].values.astype(float)
                    y_month = np.nan_to_num(y_month)
                    pred = np.mean(y_month)
                    
                pred = min(max(0, pred), max_y * 1.5)
                predictions.append(pred)
                
            predictions.append(confidence)
            return pd.Series(predictions)
        except Exception as e:
            return pd.Series([0] * 12 + ['Low'])

    forecast_cols = [f'AI_Forecast_M{i}' for i in range(1, 13)]
    full_inv[forecast_cols + ['AI_Confidence']] = full_inv.apply(predict_demand_seasonal_avg, axis=1)

    from accuracy_tracker import track_and_adjust_forecasts
    log("Tracking accuracy and applying historical bias...")
    full_inv, accuracy_df, chart_data = track_and_adjust_forecasts(full_inv)

    # 5. ORDER CALCULATIONS
    log("Calculating inventory metrics...")
    lt_df['Vendor Code'] = pd.to_numeric(lt_df['Vendor Code'], errors='coerce').fillna(0).astype(int)
    full_inv['pi_vendor_code'] = pd.to_numeric(full_inv['pi_vendor_code'], errors='coerce').fillna(0).astype(int)
    full_inv = full_inv.merge(lt_df[['Vendor Code', 'Lead Time Days', 'Vendor Name']], 
                           left_on='pi_vendor_code', right_on='Vendor Code', how='left')
    
    if 'vendor_slicer' in full_inv.columns:
        full_inv['Vendor Name'] = full_inv['vendor_slicer'].combine_first(full_inv['Vendor Name'])
    
    full_inv['Lead Time Days'] = pd.to_numeric(full_inv['Lead Time Days'], errors='coerce').fillna(14)
    full_inv['Demand_During_Lead_Time'] = (full_inv['AI_Forecast_M1'] / 30) * full_inv['Lead Time Days']
    full_inv['Safety_Stock'] = full_inv['Demand_During_Lead_Time'] * 0.20
    full_inv['Reorder_Point'] = np.ceil(full_inv['Demand_During_Lead_Time'] + full_inv['Safety_Stock'])
    full_inv['Target_Stock'] = full_inv['AI_Forecast_M1'] + full_inv['AI_Forecast_M2']
    full_inv['Total_Available'] = full_inv.get('pi_bin_qty', 0) + full_inv.get('pi_on_order', 0)

    full_inv['Suggested_Order_Qty'] = np.where(
        full_inv['Total_Available'] < full_inv['Reorder_Point'],
        (full_inv['Target_Stock'] - full_inv['Total_Available']).clip(lower=0),
        0
    ).round(0)
    full_inv['Line_Cost'] = full_inv['Suggested_Order_Qty'] * full_inv.get('pi_cost', 0)

    # 6. OUTPUT GENERATION
    log("Formatting report...")
    to_buy = full_inv[full_inv['Suggested_Order_Qty'] > 0].copy()
    to_buy['Shortage'] = to_buy['Reorder_Point'] - to_buy['Total_Available']
    sort_col = 'Vendor Name' if 'Vendor Name' in to_buy.columns else 'pi_vendor_code'
    to_buy = to_buy.sort_values(by=[sort_col, 'Shortage'], ascending=[True, False])

    report_cols = {
        'pi_vendor_code': 'Vendor Code',
        'Vendor Name': 'Vendor',
        'pi_part_no': 'Part Number',
        'pi_bin': 'Bin Location',
        'pi_description': 'Description',
        'pi_cost': 'Unit Cost',
        'pi_bin_qty': 'On Hand',
        'pi_on_order': 'On Order',
        'Total_Available': 'Total Avail',
        'Lead Time Days': 'Lead Time (Days)',
        'Reorder_Point': 'Reorder Point (ROP)',
        'Suggested_Order_Qty': 'Suggested Order',
        'Line_Cost': 'Total Cost',
        'AI_Confidence': 'Confidence'
    }
    
    available_cols = [c for c in report_cols.keys() if c in to_buy.columns]
    final_report = to_buy[available_cols].rename(columns=report_cols)
    
    # Rounding for Line Details
    numeric_fixes = ['On Hand', 'On Order', 'Total Avail', 'Lead Time (Days)', 'Reorder Point (ROP)', 'Suggested Order']
    for col in numeric_fixes:
        if col in final_report.columns:
            final_report[col] = final_report[col].fillna(0).round(0).astype(int)
            
    money_fixes = ['Unit Cost', 'Total Cost']
    for col in money_fixes:
        if col in final_report.columns:
            final_report[col] = final_report[col].fillna(0).round(2)
    
    # Forecast tab rounding
    month_names = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
    rename_forecast = {'pi_vendor_code': 'Vendor Code', 'Vendor Name': 'Vendor', 'pi_part_no': 'Part Number', 'pi_description': 'Description'}
    curr_m0 = current_month_idx - 1
    for i in range(1, 13):
        m_name = month_names[(curr_m0 + i) % 12]
        rename_forecast[f'AI_Forecast_M{i}'] = f"AI_Forecast_M{i} ({m_name})"
    
    forecast_target_cols = ['pi_vendor_code', 'Vendor Name', 'pi_part_no', 'pi_description'] + forecast_cols
    available_forecast_cols = [c for c in forecast_target_cols if c in to_buy.columns]
    forecast_df = to_buy[available_forecast_cols].rename(columns=rename_forecast)
    
    for col in forecast_df.columns:
        if 'AI_' in col:
            forecast_df[col] = forecast_df[col].fillna(0).round(0).astype(int)

    # Vendor Summary
    if 'Vendor' in final_report.columns and 'Total Cost' in final_report.columns:
        vendor_summary = final_report.groupby('Vendor')['Total Cost'].sum().reset_index()
        vendor_summary = vendor_summary.sort_values(by='Total Cost', ascending=False)
        vendor_summary.rename(columns={'Total Cost': 'Total PO Value'}, inplace=True)
    else:
        vendor_summary = pd.DataFrame(columns=['Vendor', 'Total PO Value'])

    # Save and Format
    log("Formatting report and generating Excel output...")
    excel_buffer = io.BytesIO()
    
    ds_mask = final_report['Bin Location'].astype(str).str.strip().str.upper() == 'DS'
    regular_report = final_report[~ds_mask]
    ds_report = final_report[ds_mask]
    
    with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
        regular_report.to_excel(writer, sheet_name='Line Details', index=False)
        ds_report.to_excel(writer, sheet_name='DS Suggestions', index=False)
        forecast_df.to_excel(writer, sheet_name='AI Forecast', index=False)
        vendor_summary.to_excel(writer, sheet_name='Vendor Summary', index=False)
        if not accuracy_df.empty:
            accuracy_df.to_excel(writer, sheet_name='AI Accuracy', index=False)
            
        # 7. DEAD STOCK RADAR
        log("Calculating Dead Stock...")
        full_inv['12M_Forecast_Total'] = full_inv[forecast_cols].sum(axis=1)
        
        dead_stock = full_inv[
            (full_inv['Total_Available'] > 0) & 
            (full_inv['Total_Available'] > full_inv['12M_Forecast_Total']) &
            (full_inv['AI_Confidence'] != 'Low')
        ].copy()
        dead_stock['Total_Available'] = dead_stock['Total_Available'].fillna(0).round(0).astype(int)
        dead_stock['12M_Forecast_Total'] = dead_stock['12M_Forecast_Total'].fillna(0).round(0).astype(int)
        dead_stock['Excess_Qty'] = dead_stock['Total_Available'] - dead_stock['12M_Forecast_Total']
        dead_stock['Locked_Capital'] = dead_stock['Excess_Qty'] * dead_stock.get('pi_cost', 0)
        
        dead_stock_cols = {
            'Vendor Name': 'Vendor',
            'pi_part_no': 'Part Number',
            'pi_description': 'Description',
            'pi_cost': 'Unit Cost',
            'Total_Available': 'On Hand',
            '12M_Forecast_Total': '12M Predicted Demand',
            'Excess_Qty': 'Excess Qty',
            'Locked_Capital': 'Locked Capital',
            'AI_Confidence': 'Confidence'
        }
        ds_radar = dead_stock[[c for c in dead_stock_cols.keys() if c in dead_stock.columns]].rename(columns=dead_stock_cols)
        ds_radar = ds_radar.sort_values(by='Locked Capital', ascending=False)
        
        if 'Locked Capital' in ds_radar.columns:
            ds_radar['Locked Capital'] = ds_radar['Locked Capital'].fillna(0).round(2)
            
        ds_radar.to_excel(writer, sheet_name='Dead Stock Radar', index=False)
        
        # Apply Excel Formatting
        workbook = writer.book
        currency_fmt = '$#,##0.00'
        
        def apply_currency(sheet_name, df, col_names):
            if sheet_name not in writer.sheets: return
            ws = writer.sheets[sheet_name]
            for col_name in col_names:
                if col_name in df.columns:
                    col_idx = df.columns.get_loc(col_name) + 1
                    for row in range(2, ws.max_row + 1):
                        ws.cell(row=row, column=col_idx).number_format = currency_fmt

        apply_currency('Line Details', regular_report, ['Unit Cost', 'Total Cost'])
        apply_currency('DS Suggestions', ds_report, ['Unit Cost', 'Total Cost'])
        apply_currency('Vendor Summary', vendor_summary, ['Total PO Value'])
        apply_currency('Dead Stock Radar', ds_radar, ['Unit Cost', 'Locked Capital'])
        
    # Save ROPs to database
    try:
        import sqlite3
        db_path = r"S:\Inventory Data\forecast_history.db"
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        run_date_str = now.strftime('%Y-%m-%d')
        cursor.execute("SELECT COUNT(*) FROM suggested_rop_history WHERE run_date = ?", (run_date_str,))
        if cursor.fetchone()[0] == 0:
            log("Saving ROP snapshots to database...")
            rop_records = []
            for _, row in full_inv.iterrows():
                if pd.notna(row.get('Reorder_Point')) and pd.notna(row.get('pi_part_no')):
                    rop_records.append((str(row['pi_part_no']), int(row['Reorder_Point']), run_date_str))
            cursor.executemany("INSERT INTO suggested_rop_history (part_no, suggested_rop, run_date) VALUES (?, ?, ?)", rop_records)
            conn.commit()
        conn.close()
    except Exception as e:
        log(f"Error saving ROPs: {e}")

    # Prepare full inventory for Freight Optimizer
    # Exclude DS items so they don't get accidentally added to stock orders!
    ds_mask = full_inv['Bin Location'].astype(str).str.strip().str.upper() == 'DS' if 'Bin Location' in full_inv.columns else pd.Series(False, index=full_inv.index)
    optimizer_inv = full_inv[~ds_mask].copy()
    
    fi_cols = [c for c in ['pi_vendor_code', 'Vendor Name', 'pi_part_no', 'pi_description', 'pi_cost', 'Total_Available', 'Reorder_Point', 'Suggested_Order_Qty', 'AI_Forecast_M1', 'Target_Stock'] if c in optimizer_inv.columns]
    full_inventory = optimizer_inv[fi_cols].copy()
    
    log("Processing complete!")
    
    return {
        "line_details": regular_report,
        "ds_suggestions": ds_report,
        "ai_forecast": forecast_df,
        "vendor_summary": vendor_summary,
        "accuracy_summary": accuracy_df,
        "dead_stock_radar": ds_radar,
        "chart_data": chart_data,
        "full_inventory": full_inventory,
        "excel_bytes": excel_buffer.getvalue()
    }
