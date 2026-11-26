import requests
import re
from bs4 import BeautifulSoup
from config import CORE_ETFS, now_tw
from database import get_conn

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0.0.0 Safari/537.36"
}

def discover_active_etfs(date_str):
    """從當日 TWSE 行情自動發掘所有代碼以 'A' 結尾的主動型 ETF，動態加入追蹤清單"""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT stock_code, stock_name, volume_lots FROM stock_quotes
        WHERE trade_date = ? AND stock_code LIKE '00%A'
        ORDER BY volume_lots DESC
    """, (date_str,))
    rows = cur.fetchall()
    conn.close()

    tracked = {e["code"]: e for e in CORE_ETFS}
    priority = len(CORE_ETFS) + 1
    for r in rows:
        code = r["stock_code"]
        if code not in tracked:
            tracked[code] = {
                "code": code,
                "name": r["stock_name"],
                "issuer": "auto_detected",
                "priority": priority
            }
            priority += 1
    return sorted(tracked.values(), key=lambda x: x["priority"])

def fetch_ezmoney_00981a(date_str):
    """統一投信官方完整投資組合與基金規模抓取 (00981A 專屬高可靠度解析)"""
    url = "https://www.ezmoney.com.tw/ETF/Fund/Info?fundCode=49YTW"
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")

    page_text = soup.get_text(" ", strip=True)
    ymd_slash = date_str.replace("-", "/")
    if date_str not in page_text and ymd_slash not in page_text:
        return None

    aum_million = 0.0
    units_thousand = 0.0
    nav = 0.0
    m_aum = re.search(r"淨資產價值[^\d]*([\d,\.]+)", page_text)
    m_unit = re.search(r"受益權單位數[^\d]*([\d,\.]+)", page_text)
    m_nav = re.search(r"淨值[^\d]*([\d\.]+)", page_text)
    if m_aum:
        aum_million = round(float(m_aum.group(1).replace(",", "")) / 1e6, 2)
    if m_unit:
        units_thousand = round(float(m_unit.group(1).replace(",", "")) / 1000, 2)
    if m_nav:
        nav = float(m_nav.group(1))

    holdings = []
    for tr in soup.select("table tr"):
        tds = [td.get_text(strip=True) for td in tr.find_all("td")]
        if len(tds) >= 4 and re.match(r"^\d{4,6}$", tds[0]):
            code = tds[0]
            name = tds[1]
            shares = int(float(tds[2].replace(",", "")))
            weight = float(tds[3].replace("%", "").replace(",", ""))
            if shares > 0:
                holdings.append({
                    "stock_code": code,
                    "stock_name": name,
                    "shares": shares,
                    "weight_pct": weight
                })

    if not holdings:
        return None

    return {
        "etf_code": "00981A",
        "nav": nav,
        "aum_million": aum_million,
        "units_thousand": units_thousand,
        "holdings": holdings,
        "source": "統一投信官網 (完整投資組合)"
    }

def fetch_generic_issuer_etf(etf_info, date_str):
    code = etf_info["code"]
    if code == "00981A":
        return fetch_ezmoney_00981a(date_str)

    try:
        api_url = f"https://www.sitca.org.tw/ROC/Industry/IN2422.aspx?txtYEAR={date_str[:4]}&txtMONTH={date_str[5:7]}&txtDAY={date_str[8:10]}&txtETF={code}"
        resp = requests.get(api_url, headers=HEADERS, timeout=15)
        if date_str not in resp.text and date_str.replace("-", "/") not in resp.text:
            return None
        soup = BeautifulSoup(resp.text, "lxml")
        holdings = []
        for tr in soup.select("table tr"):
            tds = [td.get_text(strip=True) for td in tr.find_all("td")]
            if len(tds) >= 4 and re.match(r"^\d{4,6}$", tds[0]):
                shares = int(float(tds[2].replace(",", "")))
                weight = float(tds[3].replace("%", "").replace(",", ""))
                if shares > 0:
                    holdings.append({
                        "stock_code": tds[0],
                        "stock_name": tds[1],
                        "shares": shares,
                        "weight_pct": weight
                    })
        if not holdings:
            return None
        return {
            "etf_code": code,
            "nav": 0.0,
            "aum_million": 0.0,
            "units_thousand": 0.0,
            "holdings": holdings,
            "source": "投信官網 / 投信投顧公會申報資料"
        }
    except Exception:
        return None

def update_all_etfs(date_str):
    conn = get_conn()
    cur = conn.cursor()
    now_str = now_tw().strftime("%Y-%m-%d %H:%M:%S")
    etf_list = discover_active_etfs(date_str)

    for etf in etf_list:
        code = etf["code"]
        cur.execute("SELECT status FROM etf_meta WHERE trade_date = ? AND etf_code = ?", (date_str, code))
        row = cur.fetchone()
        if row and row["status"] == "UPDATED":
            continue

        try:
            data = fetch_generic_issuer_etf(etf, date_str)
            if data is None:
                cur.execute("""
                    INSERT OR REPLACE INTO etf_meta
                    (trade_date, etf_code, etf_name, status, source, error_msg, updated_at)
                    VALUES (?, ?, ?, 'PENDING', '官方網站', '今日資料尚未公布，排程持續輪詢中', ?)
                """, (date_str, code, etf["name"], now_str))
            else:
                cur.execute("""
                    INSERT OR REPLACE INTO etf_meta
                    (trade_date, etf_code, etf_name, nav, aum_million, units_thousand, status, source, error_msg, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'UPDATED', ?, '', ?)
                """, (date_str, code, etf["name"], data["nav"], data["aum_million"], data["units_thousand"], data["source"], now_str))

                for h in data["holdings"]:
                    cur.execute("""
                        INSERT OR REPLACE INTO etf_holdings
                        (trade_date, etf_code, stock_code, stock_name, shares, weight_pct, portfolio_type, source, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 'FULL_PORTFOLIO', ?, ?)
                    """, (date_str, code, h["stock_code"], h["stock_name"], h["shares"], h["weight_pct"], data["source"], now_str))
        except Exception as e:
            cur.execute("""
                INSERT OR REPLACE INTO etf_meta
                (trade_date, etf_code, etf_name, status, source, error_msg, updated_at)
                VALUES (?, ?, ?, 'FAILED', '官方網站', ?, ?)
            """, (date_str, code, etf["name"], str(e)[:200], now_str))

    conn.commit()
    conn.close()
