from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import pandas as pd
import os
import base64
import json
from dotenv import load_dotenv

load_dotenv()

from engine import run_forecast_logic
from fabric_connector import fetch_inventory_data

app = FastAPI(title="Express Inventory Forecaster API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://localhost:8000", "http://127.0.0.1", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DEFAULT_CONNECTION_STRING = os.getenv("FABRIC_CONNECTION_STRING", "")

class ForecastRequest(BaseModel):
    connection_string: str = None

@app.post("/api/forecast")
def generate_forecast(request: ForecastRequest):
    try:
        # 1. Fetch data from Fabric (or mock)
        conn_str = request.connection_string if request.connection_string else DEFAULT_CONNECTION_STRING
        express_inv, other_inv = fetch_inventory_data(conn_str)
        
        # 2. Read local lead time file
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        lt_path = os.path.join(base_dir, "..", "Vendor Lead Times 231215 BN - updated W9-29-2025.xlsx")
        if os.path.exists(lt_path):
            lead_time_df = pd.read_excel(lt_path, engine='openpyxl')
        else:
            print("Lead time file not found, using empty DF")
            lead_time_df = pd.DataFrame()

        # 3. Run engine
        results = run_forecast_logic(
            inventory_dfs=[express_inv, other_inv],
            lead_time_df=lead_time_df
        )
        
        # 4. Prepare JSON response
        # Convert DataFrames to dict (records)
        line_details_json = json.loads(results["line_details"].to_json(orient="records"))
        ds_suggestions_json = json.loads(results["ds_suggestions"].to_json(orient="records"))
        vendor_summary_json = json.loads(results["vendor_summary"].to_json(orient="records"))
        ai_forecast_json = json.loads(results["ai_forecast"].to_json(orient="records"))
        accuracy_summary_json = json.loads(results["accuracy_summary"].to_json(orient="records")) if not results["accuracy_summary"].empty else []
        
        full_inventory_json = json.loads(results["full_inventory"].to_json(orient="records"))
        
        # Encode Excel bytes as Base64 for download
        excel_b64 = base64.b64encode(results["excel_bytes"]).decode('utf-8')
        
        return {
            "status": "success",
            "data": {
                "line_details": line_details_json,
                "ds_suggestions": ds_suggestions_json,
                "vendor_summary": vendor_summary_json,
                "ai_forecast": ai_forecast_json,
                "ai_accuracy": accuracy_summary_json,
                "dead_stock_radar": json.loads(results["dead_stock_radar"].to_json(orient="records")),
                "chart_data": results.get("chart_data", []),
                "full_inventory": full_inventory_json
            },
            "excel_base64": excel_b64
        }
        
    except Exception as e:
        print(f"Error during forecast: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/rops")
def get_rop_history():
    try:
        import sqlite3
        db_path = r"S:\Inventory Data\forecast_history.db"
        conn = sqlite3.connect(db_path)
        df = pd.read_sql("SELECT part_no, suggested_rop, run_date FROM suggested_rop_history ORDER BY run_date ASC", conn)
        conn.close()
        return {"status": "success", "data": json.loads(df.to_json(orient="records"))}
    except Exception as e:
        print(f"Error fetching ROPs: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/accuracy/{part_no}")
def get_accuracy_history(part_no: str):
    try:
        import sqlite3
        db_path = r"S:\Inventory Data\forecast_history.db"
        
        # Fallback to local if S: drive not available
        if not os.path.exists(r"S:\Inventory Data"):
            db_path = "forecast_history.db"
            
        conn = sqlite3.connect(db_path)
        
        query = """
        SELECT month, SUM(predicted) as predicted, SUM(actual) as actual
        FROM (
            SELECT target_month as month, forecast_qty as predicted, 0 as actual 
            FROM forecast_history WHERE part_no = ?
            UNION ALL
            SELECT sales_month as month, 0 as predicted, actual_qty as actual 
            FROM actual_sales_history WHERE part_no = ?
        )
        GROUP BY month
        ORDER BY month
        """
        
        df = pd.read_sql(query, conn, params=(part_no, part_no))
        conn.close()
        return {"status": "success", "data": json.loads(df.to_json(orient="records"))}
    except Exception as e:
        print(f"Error fetching accuracy history: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Mount static files for the frontend dashboard
# Needs to be after API routes so it doesn't swallow them
frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
