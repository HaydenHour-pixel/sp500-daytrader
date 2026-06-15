import pandas as pd
import numpy as np
import os
def create_corrupt_log(file_name="trade_log.csv"):
    # Create valid base data
    data = {
    "Trade_ID": ["tr_1", "tr_2", "tr_3"],
    "Ticker": ["TSLA", "NVDA", "AAPL"],
    "Type": ["LONG", "LONG", "LONG"],
    "Qty": [10, 5, 20],
    "Entry_Time": ["2026-06-12 10:00:00", "2026-06-12 10:05:00",

    "2026-06-12 10:10:00"],

    "Entry_Price": [180.50, 450.25, 150.00],
    "Exit_Time": ["2026-06-12 10:30:00", "2026-06-12 10:35:00",

    "2026-06-12 10:40:00"],

    "Exit_Price": [182.00, 448.00, 151.50],
    "PnL": [15.00, -11.25, 30.00],
    "Status": ["CLOSED", "CLOSED", "CLOSED"],
    "Engine": ["ENGINE_A", "ENGINE_A", "ENGINE_A"]
    }
    df = pd.DataFrame(data)
    # Introduce Corruptions:
    # 1. Add a row with completely broken data
    df.loc[3] = ["tr_4", "BAD_DATA", "LONG", "abc", "invalid_date",
    "invalid_price", "invalid_date", "invalid_price", "NaN", "CLOSED",
    "ENGINE_A"]
    # 2. Add a row with missing critical information (NaN)
    df.loc[4] = ["tr_5", np.nan, "LONG", 10, "2026-06-12 11:00:00",
    100.00, "2026-06-12 11:30:00", 105.00, 50.00, "CLOSED", "ENGINE_A"]
    df.to_csv(file_name, index=False)
    print(f"✅ Generated corrupt '{file_name}' for testing.")
if __name__ == "__main__":
    create_corrupt_log()