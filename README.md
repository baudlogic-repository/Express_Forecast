# Express Inventory Forecaster

An intelligent inventory restocking and forecasting dashboard powered by Machine Learning and FastAPI.

## Features
- **AI Demand Forecasting:** Predicts demand for the next 12 months using historical sales patterns.
- **Accuracy Tracking & Bias Adjustment:** Automatically grades past predictions and self-adjusts future forecasts.
- **Dead Stock Radar:** Identifies massive overstocking issues, actively quantifying tied-up capital.
- **Confidence Scoring:** Applies statistical confidence (High, Medium, Low) to forecasts.

## Tech Stack
- **Backend:** Python, FastAPI, Pandas, Scikit-learn, SQLite
- **Frontend:** Vanilla JavaScript, HTML, CSS, Chart.js

## Installation & Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/baudlogic-repository/Express_Forecast.git
   cd Express_Forecast
   ```

2. **Install Python Dependencies:**
   Navigate into the `backend` directory and install the requirements:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   You must securely connect to the Azure Fabric Data Warehouse. In the `backend` directory, create a `.env` file (this file is ignored by git for security) and add your connection string:
   ```env
   FABRIC_CONNECTION_STRING="Driver={ODBC Driver 17 for SQL Server};Server=...;Database=...;UID=...;PWD=...;"
   ```

4. **Run the Server:**
   You can run the server directly using Uvicorn:
   ```bash
   uvicorn main:app --reload
   ```
   Or double-click the `Start_Server.bat` file.

5. **Access the Dashboard:**
   Open your browser and navigate to:
   [http://localhost:8000/index.html](http://localhost:8000/index.html)
