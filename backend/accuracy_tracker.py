import sqlite3
import os
import pandas as pd
from datetime import datetime

DB_DIR = r"S:\Inventory Data"
DB_FILE = "forecast_history.db"

def get_db_connection():
    try:
        os.makedirs(DB_DIR, exist_ok=True)
        db_path = os.path.join(DB_DIR, DB_FILE)
    except Exception as e:
        print(f"Failed to use {DB_DIR}, falling back to local directory. Error: {e}")
        db_path = DB_FILE
        
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS actual_sales_history (
            part_no TEXT,
            sales_month TEXT,
            actual_qty REAL,
            recorded_date TEXT
        )
    ''')
    return conn

def get_target_month_str(months_ahead=1):
    now = datetime.now()
    y = now.year
    m = now.month + months_ahead
    while m > 12:
        m -= 12
        y += 1
    while m < 1:
        m += 12
        y -= 1
    return f"{y}-{m:02d}"

def get_current_month_str():
    now = datetime.now()
    return f"{now.year}-{now.month:02d}"

def track_and_adjust_forecasts(full_inv):
    conn = get_db_connection()
    current_month = get_current_month_str()
    next_month = get_target_month_str(1)
    eval_month = get_target_month_str(-1)
    
    history_df = pd.read_sql(
        "SELECT part_no, forecast_qty as past_forecast FROM forecast_history WHERE target_month = ?", 
        conn, 
        params=(eval_month,)
    )
    
    accuracy_data = []
    bias_dict = {}
    
    if not history_df.empty:
        history_df = history_df.groupby('part_no').last().reset_index()
        
        for idx, row in full_inv.iterrows():
            part_no = str(row.get('pi_part_no', ''))
            actual_sales = row.get('pi_sales_history_02', 0)
            
            past_match = history_df[history_df['part_no'] == part_no]
            if not past_match.empty:
                past_forecast = past_match['past_forecast'].values[0]
                error = actual_sales - past_forecast
                
                bias_adjustment = error * 0.25
                bias_dict[part_no] = bias_adjustment
                
                accuracy_data.append({
                    'Part Number': part_no,
                    'Description': row.get('pi_description', ''),
                    'Past Forecast': round(past_forecast, 2),
                    'Actual Sales': round(actual_sales, 2),
                    'Variance': round(error, 2),
                    'Bias Adjustment': round(bias_adjustment, 2),
                    'Confidence': row.get('AI_Confidence', 'N/A')
                })
                
    accuracy_df = pd.DataFrame(accuracy_data)
    if accuracy_df.empty:
        accuracy_df = pd.DataFrame(columns=['Part Number', 'Description', 'Past Forecast', 'Actual Sales', 'Variance', 'Bias Adjustment', 'Confidence'])
        
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Save Actuals
    existing_actuals = pd.read_sql(
        "SELECT part_no, sales_month FROM actual_sales_history WHERE recorded_date LIKE ?", 
        conn, 
        params=(f"{today_str}%",)
    )
    saved_actuals_today = set(zip(existing_actuals['part_no'], existing_actuals['sales_month']))
    insert_actuals = []
    
    # Save Forecasts
    existing_forecasts = pd.read_sql(
        "SELECT part_no FROM forecast_history WHERE run_date LIKE ? AND target_month = ?", 
        conn, 
        params=(f"{today_str}%", next_month)
    )
    saved_forecasts_today = set(existing_forecasts['part_no'].values)
    insert_forecasts = []

    for idx, row in full_inv.iterrows():
        part_no = str(row.get('pi_part_no', ''))
        bias = bias_dict.get(part_no, 0)
        current_actual_sales = row.get('pi_current_mo_sales', 0)
        eval_actual_sales = row.get('pi_sales_history_02', 0)
        
        # Adjust forecasts
        if bias != 0:
            for i in range(1, 13):
                col = f'AI_Forecast_M{i}'
                if col in full_inv.columns:
                    adj_val = full_inv.at[idx, col] + bias
                    full_inv.at[idx, col] = max(0, adj_val)
                
        # Queue Actuals for insertion
        if (part_no, current_month) not in saved_actuals_today:
            insert_actuals.append((part_no, current_month, current_actual_sales, now_str))
        if (part_no, eval_month) not in saved_actuals_today:
            insert_actuals.append((part_no, eval_month, eval_actual_sales, now_str))
            
        # Queue Forecasts for insertion
        if part_no not in saved_forecasts_today:
            m1_forecast = full_inv.at[idx, 'AI_Forecast_M1']
            insert_forecasts.append((part_no, next_month, m1_forecast, now_str))
                     
    if insert_actuals:
        conn.executemany("INSERT INTO actual_sales_history (part_no, sales_month, actual_qty, recorded_date) VALUES (?, ?, ?, ?)", insert_actuals)
    if insert_forecasts:
        conn.executemany("INSERT INTO forecast_history (part_no, target_month, forecast_qty, run_date) VALUES (?, ?, ?, ?)", insert_forecasts)
        
    # Build Chart Data
    forecast_agg = pd.read_sql("SELECT target_month as month, SUM(forecast_qty) as total_forecast FROM (SELECT target_month, part_no, forecast_qty FROM forecast_history GROUP BY target_month, part_no) GROUP BY target_month", conn)
    actual_agg = pd.read_sql("SELECT sales_month as month, SUM(actual_qty) as total_actual FROM (SELECT sales_month, part_no, MAX(actual_qty) as actual_qty FROM actual_sales_history GROUP BY sales_month, part_no) GROUP BY sales_month", conn)
    
    chart_data = []
    if not (forecast_agg.empty and actual_agg.empty):
        if forecast_agg.empty:
            merged = actual_agg
            merged['total_forecast'] = 0
        elif actual_agg.empty:
            merged = forecast_agg
            merged['total_actual'] = 0
        else:
            merged = pd.merge(forecast_agg, actual_agg, on='month', how='outer').fillna(0)
            
        merged = merged.sort_values('month')
        chart_data = merged.to_dict(orient="records")
        
    conn.commit()
    conn.close()
    
    return full_inv, accuracy_df, chart_data
