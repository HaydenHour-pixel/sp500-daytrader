## Why I Built This
As a computer science major with a business minor, I thought that building a day trading bot would perfectly combine computer science and finance (two fields I am very interested in). Furthermore, I thought that the experience would give me the oportunity to learn more about micro patterns in the market and how they can be used to predict when to BUY, SELL, and HOLD within a very short period of time.

# Vectorized S&P 500 Momentum Scanning & Position Rotation Engine

An automated, data-driven quantitative trading pipeline built in Python that conducts a daily comprehensive alpha sweep across the entire S&P 500 index composition. The system executes optimized momentum crossover strategies using the **Alpaca Trading Client API** and high-performance concurrent data scraping via **Yahoo Finance**.

## 🚀 System Architecture & Key Engineering Features

* **Live Index Synchronization:** Dynamically streams current S&P 500 asset composition directly via a remote pre-cleaned CSV data stream, bypassing heavy, error-prone HTML scrapers and adapting automatically to index additions/deletions.
* **Vectorized Macro Filtering:** Leverages `pandas` vectorized operations to fetch 3-year historical windows for over 500 tickers simultaneously, instantly filtering out equities locked in a structural macroeconomic downtrend (trading below their 200-day Simple Moving Average).
* **In-Memory Historical Optimization Grid Search:** Conducts a localized backtest matrix simulation on shortlisted assets. The model iteratively scores permutations of fast windows (`5`, `10`, `15`) and slow windows (`30`, `50`, `75`, `100`) to select the historically optimal, highest-performing moving average boundary unique to that asset's trading behavior.
* **Equal-Weight Capital Risk Allocation:** Strictly adheres to a defensive risk profile by distributing capital in hardcoded $10,000 asset tranches. To secure a safe capital structure, the engine evaluates real-time liquid cash availability and intentionally avoids borrowing against overnight margin.
* **Fault-Tolerant Gateways:** Employs pre-flight connection checks via Alpaca's live `get_clock()` API wrapper to identify weekends and stock market holidays, gracefully shutting down the pipeline within seconds to prevent redundant log writing and data distortion.

## ⚙️ Unattended Production Deployment (Session 0 Environment)
This pipeline is engineered to run as a true "set-and-forget" local background server using **Windows Task Scheduler**. To run autonomously without active human interaction, it overcomes common desktop script limitations via the following design patterns:
1. **Unattended Execution Security:** Configured to run whether a user is logged on or not, shifting execution into the secure, isolated Windows background (**Session 0**).
2. **Absolute File Path Hardening:** Explicitly overrides default operating system path directories (which typically default back to `System32` for background tasks) by hardcoding working runtime parameters and system Python interpreters, protecting local persistence tracking in `trading_log.csv`.
3. **Hardware Wake Inversion:** Leverages Windows kernel wake timers, allowing a sleeping or locked computer to wake up, execute the data pipeline at the opening bell, and return to an idle state cleanly.

## 📊 Tech Stack & Core Libraries
* **Language:** Python 3.11+
* **Data Ingestion & Matrix Analysis:** Pandas, NumPy, YFinance
* **Brokerage Pipeline:** Alpaca-py (TradingClient, MarketOrderRequest)
* **Automation Hub:** Windows Task Scheduler (Background Engine)

## 📋 Execution Footprint Example
When triggered, the system documents its choices in a localized comma-separated log matrix (`trading_log.csv`):
```csv
Timestamp,Ticker,Optimized_Strategy,Signal,Action_Executed
2026-06-05 10:00:03,HON,SMA_15/SMA_50,BUY,EXECUTED_BUY
2026-06-05 10:01:14,BMY,SMA_5/SMA_75,HOLD,NONE_HOLD
2026-06-05 10:02:22,AAPL,SMA_10/SMA_30,SELL,EXECUTED_SELL
