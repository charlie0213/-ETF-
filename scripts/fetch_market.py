import requests
import urllib3
from datetime import datetime
from config import now_tw, SECTOR_MAPPING
from database import get_conn

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
}

def clean_num(val):
    if val is None:
        return 0.0
    s = str(val).replace(",", "").replace("+", "").replace("%", "").strip()
    if s in ("", "--", "---", "N/A", "X"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0

def check_is_trading_day(date_str):
    """透過 TWSE 大盤成交資訊確認當日是否為實際交易日 (非週末/國定假日)"""
    ymd = date_str.replace("-", "")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ymd}&response=json"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, verify=False).json()
        if r.get("stat") != "OK":
            return False
        roc_date = f"{int(date_str[:4])-1911}/{date_str[5:7]}/{date_str[8:10]}"
        for row in r.get("data", []):
            if row[0].strip() == roc_date:
                return True
        return False
    except Exception:
        return False

def fetch_twse_quotes(date_str):
    """抓取 TWSE 每日收盤行情 (MI_INDEX ALLBUT0999) 與大盤指數"""
    ymd = date_str.replace("-", "")
    url = f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={ymd}&type=ALLBUT0999&response=json"
    r = requests.get(url, headers=HEADERS, timeout=20, verify=False).json()
    if r.get("stat") != "OK":
        return False

    conn = get_conn()
    cur = conn.cursor()
    now_str = now_tw().strftime("%Y-%m-%d %H:%M:%S")

    taiex_close, taiex_change, taiex_pct, turnover_billion = 0.0, 0.0, 0.0, 0.0
    for table in r.get("tables", []):
        title = table.get("title", "")
        if "價格指數" in title:
            for row in table.get("data", []):
                if "發行量加權股價指數" in row[0]:
                    taiex_close = clean_num(row[1])
                    sign = -1 if "-" in str(row[2]) else 1
                    taiex_change = sign * clean_num(row[3])
                    taiex_pct = clean_num(row[4])
        elif "大盤統計資訊" in title:
            for row in table.get("data", []):
                if "總計" in row[0]:
                    turnover_billion = round(clean_num(row[1]) / 1e8, 2)

        if "每日收盤行情" in title:
            for row in table.get("data", []):
                code = row[0].strip()
                name = row[1].strip()
                vol_lots = int(clean_num(row[2]) // 1000)
                close_p = clean_num(row[8])
                sign = -1 if "-" in str(row[9]) else 1
                diff = sign * clean_num(row[10])
                prev_p = close_p - diff
                pct = round((diff / prev_p * 100), 2) if prev_p > 0 else 0.0
                sector = SECTOR_MAPPING.get(code, "ETF" if code.startswith("00") else "其他")
                cur.execute("""
                    INSERT OR REPLACE INTO stock_quotes
                    (trade_date, stock_code, stock_name, market, close_price, price_change, pct_change, volume_lots, sector)
                    VALUES (?, ?, ?, 'TWSE', ?, ?, ?, ?, ?)
                """, (date_str, code, name, close_p, diff, pct, vol_lots, sector))

    # 抓取三大法人買賣金額統計表 (BFI82U)
    bfi_url = f"https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={ymd}&type=day&response=json"
    bfi = requests.get(bfi_url, headers=HEADERS, timeout=15, verify=False).json()
    f_net, t_net, d_net = 0.0, 0.0, 0.0
    if bfi.get("stat") == "OK":
        for row in bfi.get("data", []):
            item = row[0].strip()
            net_val = round(clean_num(row[3]) / 1e8, 2)
            if "外資及陸資(不含外資自營商)" in item:
                f_net = net_val
            elif "投信" in item:
                t_net = net_val
            elif "自營商(自行買賣)" in item or "自營商(避險)" in item:
                d_net = round(d_net + net_val, 2)

    total_inst = round(f_net + t_net + d_net, 2)

    cur.execute("SELECT trade_date, foreign_net_billion FROM market_summary WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 30", (date_str,))
    hist = cur.fetchall()
    streak_days = 1 if f_net != 0 else 0
    streak_amt = f_net
    if f_net != 0:
        is_buy = f_net > 0
        for h in hist:
            val = h["foreign_net_billion"]
            if (is_buy and val > 0) or (not is_buy and val < 0):
                streak_days += 1 if is_buy else -1
                streak_amt = round(streak_amt + val, 2)
            else:
                break
        if not is_buy and streak_days > 0:
            streak_days = -streak_days

    cur.execute("""
        INSERT OR REPLACE INTO market_summary
        (trade_date, taiex_close, taiex_change, taiex_pct, turnover_billion,
         foreign_net_billion, trust_net_billion, dealer_net_billion, total_inst_billion,
         foreign_streak_days, foreign_streak_amount, source, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'TWSE 官方資料', ?)
    """, (date_str, taiex_close, taiex_change, taiex_pct, turnover_billion,
          f_net, t_net, d_net, total_inst, streak_days, streak_amt, now_str))

    conn.commit()
    conn.close()
    return True

def fetch_twse_foreign_net(date_str):
    """抓取 TWSE 外資及陸資買賣超彙總表 (TWT38U) - 嚴格採用不含外資自營商口徑"""
    ymd = date_str.replace("-", "")
    url = f"https://www.twse.com.tw/rwd/zh/fund/TWT38U?date={ymd}&response=json"
    r = requests.get(url, headers=HEADERS, timeout=20, verify=False).json()
    if r.get("stat") != "OK":
        return False

    conn = get_conn()
    cur = conn.cursor()
    now_str = now_tw().strftime("%Y-%m-%d %H:%M:%S")

    for row in r.get("data", []):
        code = row[1].strip()
        name = row[2].strip()
        if len(code) > 6:
            continue
        buy_lots = int(round(clean_num(row[3]) / 1000))
        sell_lots = int(round(clean_num(row[4]) / 1000))
        net_lots = int(round(clean_num(row[5]) / 1000))
        cur.execute("""
            INSERT OR REPLACE INTO foreign_net
            (trade_date, stock_code, stock_name, buy_lots, sell_lots, net_lots, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'TWSE TWT38U (外陸資不含自營商)', ?)
        """, (date_str, code, name, buy_lots, sell_lots, net_lots, now_str))

    conn.commit()
    conn.close()
    return True
