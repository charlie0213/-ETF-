from config import now_tw
from database import init_db, get_conn
from fetch_market import check_is_trading_day, fetch_twse_quotes, fetch_twse_foreign_net
from fetch_etf import update_all_etfs
from analyzer import build_daily_snapshot_and_report

def run_pipeline():
    init_db()
    now = now_tw()
    today_str = now.strftime("%Y-%m-%d")

    # 1. 隔日回補檢查：檢查前一個交易日是否有未更新完畢的 ETF，若有則自動補抓並重算快照
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT trade_date FROM etf_meta WHERE trade_date < ? AND status != 'UPDATED' ORDER BY trade_date DESC LIMIT 1", (today_str,))
    stale_row = cur.fetchone()
    conn.close()

    if stale_row:
        stale_date = stale_row["trade_date"]
        print(f"[補抓機制] 發現前一交易日 {stale_date} 尚有缺漏 ETF 資料，執行補抓...")
        update_all_etfs(stale_date)
        build_daily_snapshot_and_report(stale_date)

    # 2. 判斷今日是否為台股交易日 (週末或休市日直接安全結束，不產生虛假資料)
    if now.weekday() >= 5 or not check_is_trading_day(today_str):
        print(f"[{today_str}] 今日為週末或台股休市日，不產生交易資料。")
        return

    # 3. 13:30 後抓取大盤與收盤行情
    if now.hour >= 13:
        ok_q = fetch_twse_quotes(today_str)
        if not ok_q:
            print(f"[{today_str}] TWSE 收盤行情尚未公布，稍後重試。")
            return

    # 4. 15:00 後抓取外資買賣超與輪詢各投信 ETF 完整持股
    if now.hour >= 15:
        fetch_twse_foreign_net(today_str)
        update_all_etfs(today_str)
        build_daily_snapshot_and_report(today_str)
        print(f"[{today_str}] 籌碼資料庫與 JSON 快照已更新完成。")

if __name__ == "__main__":
    run_pipeline()
