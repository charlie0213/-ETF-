import sqlite3
import os

DB_PATH = os.path.join("data", "chip_tracker.db")

def get_conn():
    os.makedirs("data", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # 1. 大盤與三大法人每日摘要
    cur.execute("""
    CREATE TABLE IF NOT EXISTS market_summary (
        trade_date TEXT PRIMARY KEY,
        taiex_close REAL,
        taiex_change REAL,
        taiex_pct REAL,
        turnover_billion REAL,
        foreign_net_billion REAL,
        trust_net_billion REAL,
        dealer_net_billion REAL,
        total_inst_billion REAL,
        foreign_streak_days INTEGER,
        foreign_streak_amount REAL,
        source TEXT,
        updated_at TEXT
    )""")

    # 2. 每日全市場個股收盤行情 (上市+上櫃)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS stock_quotes (
        trade_date TEXT,
        stock_code TEXT,
        stock_name TEXT,
        market TEXT,
        close_price REAL,
        price_change REAL,
        pct_change REAL,
        volume_lots INTEGER,
        sector TEXT,
        PRIMARY KEY (trade_date, stock_code)
    )""")

    # 3. 上市外資買賣超 (外陸資不含自營商)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS foreign_net (
        trade_date TEXT,
        stock_code TEXT,
        stock_name TEXT,
        buy_lots INTEGER,
        sell_lots INTEGER,
        net_lots INTEGER,
        source TEXT,
        updated_at TEXT,
        PRIMARY KEY (trade_date, stock_code)
    )""")

    # 4. ETF 每日基金規模與流通受益權單位數
    cur.execute("""
    CREATE TABLE IF NOT EXISTS etf_meta (
        trade_date TEXT,
        etf_code TEXT,
        etf_name TEXT,
        nav REAL,
        aum_million REAL,
        units_thousand REAL,
        status TEXT,
        source TEXT,
        error_msg TEXT,
        updated_at TEXT,
        PRIMARY KEY (trade_date, etf_code)
    )""")

    # 5. ETF 每日完整持股明細 (嚴格區分完整投資組合與 PCF)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS etf_holdings (
        trade_date TEXT,
        etf_code TEXT,
        stock_code TEXT,
        stock_name TEXT,
        shares INTEGER,
        weight_pct REAL,
        portfolio_type TEXT,
        source TEXT,
        updated_at TEXT,
        PRIMARY KEY (trade_date, etf_code, stock_code)
    )""")

    # 6. 每日系統執行與異常紀錄
    cur.execute("""
    CREATE TABLE IF NOT EXISTS system_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_time TEXT,
        trade_date TEXT,
        task_name TEXT,
        status TEXT,
        message TEXT
    )""")

    conn.commit()
    conn.close()
