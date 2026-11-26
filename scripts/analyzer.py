import json
import os
from database import get_conn
from config import now_tw

def get_prev_trading_date(conn, date_str):
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT trade_date FROM market_summary WHERE trade_date < ? ORDER BY trade_date DESC LIMIT 1", (date_str,))
    row = cur.fetchone()
    return row["trade_date"] if row else None

def analyze_etf_changes(conn, date_str, prev_date):
    cur = conn.cursor()
    cur.execute("SELECT * FROM etf_meta WHERE trade_date = ?", (date_str,))
    today_metas = {r["etf_code"]: dict(r) for r in cur.fetchall()}

    cur.execute("SELECT * FROM etf_meta WHERE trade_date = ?", (prev_date,))
    prev_metas = {r["etf_code"]: dict(r) for r in cur.fetchall()} if prev_date else {}

    cur.execute("SELECT * FROM stock_quotes WHERE trade_date = ?", (date_str,))
    quotes = {r["stock_code"]: dict(r) for r in cur.fetchall()}

    all_etf_results = {}
    stock_agg = {}

    for code, meta in today_metas.items():
        if meta["status"] != "UPDATED":
            all_etf_results[code] = {"meta": meta, "changes": [], "note": "當日資料尚未完成更新，不進行出清判定"}
            continue

        prev_meta = prev_metas.get(code)
        if not prev_meta or prev_meta["status"] != "UPDATED":
            all_etf_results[code] = {"meta": meta, "changes": [], "note": "缺乏前一交易日完整基準資料，僅顯示當日持股"}
            continue

        u_today = meta.get("units_thousand") or 0
        u_prev = prev_meta.get("units_thousand") or 0
        unit_ratio = (u_today / u_prev) if (u_today > 0 and u_prev > 0) else 1.0

        cur.execute("SELECT * FROM etf_holdings WHERE trade_date = ? AND etf_code = ?", (date_str, code))
        h_today = {r["stock_code"]: dict(r) for r in cur.fetchall()}

        cur.execute("SELECT * FROM etf_holdings WHERE trade_date = ? AND etf_code = ?", (prev_date, code))
        h_prev = {r["stock_code"]: dict(r) for r in cur.fetchall()}

        all_stocks = set(h_today.keys()) | set(h_prev.keys())
        changes = []

        for sc in all_stocks:
            t_item = h_today.get(sc)
            p_item = h_prev.get(sc)
            q = quotes.get(sc, {})
            close_p = q.get("close_price", 0.0)
            pct_chg = q.get("pct_change", 0.0)
            sector = q.get("sector", "其他")
            sname = (t_item or p_item)["stock_name"]

            s_prev = p_item["shares"] if p_item else 0
            s_today = t_item["shares"] if t_item else 0
            w_prev = p_item["weight_pct"] if p_item else 0.0
            w_today = t_item["weight_pct"] if t_item else 0.0

            diff_shares = s_today - s_prev
            if diff_shares == 0 and round(w_today - w_prev, 4) == 0:
                continue

            if s_prev == 0 and s_today > 0:
                action = "新增持股"
            elif s_prev > 0 and s_today == 0:
                action = "完全出清"
            elif diff_shares > 0:
                action = "加碼持股"
            else:
                action = "減碼持股"

            expected_shares = round(s_prev * unit_ratio)
            active_adj_shares = s_today - expected_shares

            if unit_ratio > 1.005 and diff_shares > 0 and active_adj_shares <= 0:
                driver_tag = "規模擴大被動增加(估算)"
            elif unit_ratio > 1.005 and diff_shares < 0:
                driver_tag = "規模增加但逆勢減碼"
            elif unit_ratio < 0.995 and diff_shares > 0:
                driver_tag = "規模縮減但逆勢加碼"
            elif active_adj_shares > 0:
                driver_tag = "經理人主動加碼(估算)"
            elif active_adj_shares < 0:
                driver_tag = "經理人主動減碼(估算)"
            else:
                driver_tag = "維持比例"

            est_amount_wan = round((diff_shares * close_p) / 10000, 2)
            active_amount_wan = round((active_adj_shares * close_p) / 10000, 2)

            record = {
                "stock_code": sc,
                "stock_name": sname,
                "sector": sector,
                "prev_lots": round(s_prev / 1000, 2),
                "today_lots": round(s_today / 1000, 2),
                "diff_lots": round(diff_shares / 1000, 2),
                "diff_pct": round((diff_shares / s_prev * 100), 2) if s_prev > 0 else 100.0,
                "prev_weight": w_prev,
                "today_weight": w_today,
                "weight_diff": round(w_today - w_prev, 3),
                "close_price": close_p,
                "pct_change": pct_chg,
                "est_amount_wan": est_amount_wan,
                "active_adj_lots": round(active_adj_shares / 1000, 2),
                "active_amount_wan": active_amount_wan,
                "action": action,
                "driver_tag": driver_tag
            }
            changes.append(record)

            agg = stock_agg.setdefault(sc, {
                "stock_code": sc, "stock_name": sname, "sector": sector,
                "close_price": close_p, "pct_change": pct_chg,
                "total_diff_lots": 0.0, "total_est_wan": 0.0,
                "total_active_lots": 0.0, "total_active_wan": 0.0,
                "buy_etf_count": 0, "sell_etf_count": 0, "details": []
            })
            agg["total_diff_lots"] = round(agg["total_diff_lots"] + record["diff_lots"], 2)
            agg["total_est_wan"] = round(agg["total_est_wan"] + est_amount_wan, 2)
            agg["total_active_lots"] = round(agg["total_active_lots"] + record["active_adj_lots"], 2)
            agg["total_active_wan"] = round(agg["total_active_wan"] + active_amount_wan, 2)
            if diff_shares > 0:
                agg["buy_etf_count"] += 1
            elif diff_shares < 0:
                agg["sell_etf_count"] += 1
            agg["details"].append({
                "etf_code": code,
                "diff_lots": record["diff_lots"],
                "est_amount_wan": est_amount_wan,
                "action": action
            })

        changes.sort(key=lambda x: abs(x["est_amount_wan"]), reverse=True)
        all_etf_results[code] = {
            "meta": meta,
            "prev_meta": prev_meta,
            "unit_ratio": round(unit_ratio, 5),
            "estimation_disclaimer": "調整後持股異動係依流通受益權單位數比例推算之估算值，不等於基金經理人實際成交紀錄。",
            "changes": changes
        }

    return all_etf_results, stock_agg

def build_daily_snapshot_and_report(date_str):
    conn = get_conn()
    cur = conn.cursor()
    prev_date = get_prev_trading_date(conn, date_str)

    cur.execute("SELECT * FROM market_summary WHERE trade_date = ?", (date_str,))
    mkt = dict(cur.fetchone())

    cur.execute("SELECT trade_date, foreign_net_billion, trust_net_billion, taiex_close FROM market_summary WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 20", (date_str,))
    trend_20d = [dict(r) for r in cur.fetchall()][::-1]

    cur.execute("""
        SELECT f.stock_code, f.stock_name, f.net_lots, q.close_price, q.price_change, q.pct_change
        FROM foreign_net f
        JOIN stock_quotes q ON f.trade_date = q.trade_date AND f.stock_code = q.stock_code
        WHERE f.trade_date = ? AND q.market = 'TWSE'
        ORDER BY f.net_lots DESC LIMIT 10
    """, (date_str,))
    foreign_top10_buy = [dict(r) for r in cur.fetchall()]

    cur.execute("""
        SELECT f.stock_code, f.stock_name, f.net_lots, q.close_price, q.price_change, q.pct_change
        FROM foreign_net f
        JOIN stock_quotes q ON f.trade_date = q.trade_date AND f.stock_code = q.stock_code
        WHERE f.trade_date = ? AND q.market = 'TWSE'
        ORDER BY f.net_lots ASC LIMIT 10
    """, (date_str,))
    foreign_top10_sell = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT stock_code, net_lots FROM foreign_net WHERE trade_date = ?", (date_str,))
    foreign_map = {r["stock_code"]: r["net_lots"] for r in cur.fetchall()}

    etf_results, stock_agg = analyze_etf_changes(conn, date_str, prev_date)
    agg_list = list(stock_agg.values())

    rankings = {
        "top_buy_amount": sorted([x for x in agg_list if x["total_est_wan"] > 0], key=lambda x: x["total_est_wan"], reverse=True)[:10],
        "top_sell_amount": sorted([x for x in agg_list if x["total_est_wan"] < 0], key=lambda x: x["total_est_wan"])[:10],
        "top_buy_lots": sorted([x for x in agg_list if x["total_diff_lots"] > 0], key=lambda x: x["total_diff_lots"], reverse=True)[:10],
        "top_sell_lots": sorted([x for x in agg_list if x["total_diff_lots"] < 0], key=lambda x: x["total_diff_lots"])[:10],
        "most_etf_buy": sorted([x for x in agg_list if x["buy_etf_count"] > 0], key=lambda x: (x["buy_etf_count"], x["total_est_wan"]), reverse=True)[:10],
        "most_etf_sell": sorted([x for x in agg_list if x["sell_etf_count"] > 0], key=lambda x: (x["sell_etf_count"], -x["total_est_wan"]), reverse=True)[:10],
        "active_adj_buy": sorted([x for x in agg_list if x["total_active_wan"] > 0], key=lambda x: x["total_active_wan"], reverse=True)[:10],
        "active_adj_sell": sorted([x for x in agg_list if x["total_active_wan"] < 0], key=lambda x: x["total_active_wan"])[:10],
    }

    sector_flow = {}
    for x in agg_list:
        sec = x["sector"]
        s = sector_flow.setdefault(sec, {"sector": sec, "net_amount_wan": 0.0, "active_net_wan": 0.0, "buy_stocks": 0, "sell_stocks": 0})
        s["net_amount_wan"] = round(s["net_amount_wan"] + x["total_est_wan"], 2)
        s["active_net_wan"] = round(s["active_net_wan"] + x["total_active_wan"], 2)
        if x["total_diff_lots"] > 0:
            s["buy_stocks"] += 1
        elif x["total_diff_lots"] < 0:
            s["sell_stocks"] += 1

    cross = {"both_buy": [], "both_sell": [], "foreign_sell_etf_buy": [], "foreign_buy_etf_sell": [], "active_etf_foreign": []}
    for x in agg_list:
        f_lots = foreign_map.get(x["stock_code"], 0)
        item = {**x, "foreign_net_lots": f_lots}
        if f_lots > 500 and x["total_diff_lots"] > 50:
            cross["both_buy"].append(item)
        elif f_lots < -500 and x["total_diff_lots"] < -50:
            cross["both_sell"].append(item)
        elif f_lots < -500 and x["total_diff_lots"] > 50:
            cross["foreign_sell_etf_buy"].append(item)
        elif f_lots > 500 and x["total_diff_lots"] < -50:
            cross["foreign_buy_etf_sell"].append(item)

    for target in ["00981A", "00980A", "00982A", "00991A", "00403A", "0050"]:
        if target in foreign_map:
            cross["active_etf_foreign"].append({"etf_code": target, "foreign_net_lots": foreign_map[target]})

    report_md = generate_markdown_report(date_str, mkt, etf_results, rankings, foreign_top10_buy, foreign_top10_sell, cross, sector_flow)

    output = {
        "trade_date": date_str,
        "prev_date": prev_date,
        "generated_at": now_tw().strftime("%Y-%m-%d %H:%M:%S CST"),
        "market_summary": mkt,
        "trend_20d": trend_20d,
        "etf_details": etf_results,
        "rankings": rankings,
        "sector_flow": sorted(sector_flow.values(), key=lambda x: x["net_amount_wan"], reverse=True),
        "foreign_top10_buy": foreign_top10_buy,
        "foreign_top10_sell": foreign_top10_sell,
        "cross_analysis": cross,
        "daily_report_markdown": report_md
    }

    os.makedirs(os.path.join("data", "json"), exist_ok=True)
    with open(os.path.join("data", "json", f"{date_str}.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(os.path.join("data", "json", "latest.json"), "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    cur.execute("SELECT DISTINCT trade_date FROM market_summary ORDER BY trade_date DESC")
    dates = [r["trade_date"] for r in cur.fetchall()]
    with open(os.path.join("data", "json", "index.json"), "w", encoding="utf-8") as f:
        json.dump({"dates": dates, "latest": date_str, "updated_at": output["generated_at"]}, f, ensure_ascii=False, indent=2)

    conn.close()

def generate_markdown_report(date_str, mkt, etf_results, rankings, f_buy, f_sell, cross, sector_flow):
    pending_etfs = [k for k, v in etf_results.items() if v["meta"]["status"] != "UPDATED"]
    u_981 = etf_results.get("00981A", {})
    changes_981 = u_981.get("changes", [])

    lines = [
        f"# 台股主動型 ETF 與外資籌碼日報（{date_str}）",
        f"> 產出時間：{now_tw().strftime('%Y-%m-%d %H:%M:%S')} (Asia/Taipei)｜資料口徑：TWSE 官方數據與各投信完整投資組合",
        "",
        "## 1. 今日台股大盤與三大法人摘要（已確認事實）",
        f"- **加權指數**：{mkt['taiex_close']} 點（漲跌 {mkt['taiex_change']:+.2f} 點 / {mkt['taiex_pct']:+.2f}%），成交金額 **{mkt['turnover_billion']} 億元**",
        f"- **外資（不含自營商）**：**{mkt['foreign_net_billion']:+.2f} 億元**（連續 {mkt['foreign_streak_days']} 日，累計 {mkt['foreign_streak_amount']:+.2f} 億元）",
        f"- **投信**：**{mkt['trust_net_billion']:+.2f} 億元**｜**自營商**：**{mkt['dealer_net_billion']:+.2f} 億元**｜**三大法人合計**：**{mkt['total_inst_billion']:+.2f} 億元**",
        "",
        "## 2. 00981A 主動統一台股增長 完整持股異動",
    ]
    if u_981.get("meta", {}).get("status") != "UPDATED":
        lines.append(f"- ⚠️ 00981A 今日資料狀態：{u_981.get('meta', {}).get('status', '尚未公布')}，系統持續自動輪詢補抓中。")
    elif not changes_981:
        lines.append("- 今日 00981A 完整投資組合無股數異動（或為首日基準日）。")
    else:
        lines.append(f"- 異動檔數共 **{len(changes_981)}** 檔（已區分流通單位數變化估算，非實際成交單）：")
        for c in changes_981:
            lines.append(f"  - **{c['stock_code']} {c['stock_name']}** [{c['action']}]：{c['prev_lots']} → {c['today_lots']} 張（{c['diff_lots']:+.1f} 張 / 估算 {c['est_amount_wan']:+.0f} 萬｜權重 {c['weight_diff']:+.2f}%｜判讀：{c['driver_tag']}）")

    lines.extend([
        "",
        "## 3. 主動型 ETF 整體加減碼排行榜（估算金額前 5 名）",
        "- **合計加碼金額前 5**：" + ("、".join([f"{x['stock_code']} {x['stock_name']}({x['total_est_wan']:+.0f}萬)" for x in rankings["top_buy_amount"][:5]]) or "無"),
        "- **合計減碼金額前 5**：" + ("、".join([f"{x['stock_code']} {x['stock_name']}({x['total_est_wan']:+.0f}萬)" for x in rankings["top_sell_amount"][:5]]) or "無"),
        "",
        "## 4. 外資與主動型 ETF 交叉分析（推論與比對）",
        "- **土洋同買（外資買超且主動ETF加碼）**：" + ("、".join([f"{x['stock_code']} {x['stock_name']}" for x in cross["both_buy"][:5]]) or "無顯著重疊"),
        "- **土洋對作（外資賣超但主動ETF逆勢加碼）**：" + ("、".join([f"{x['stock_code']} {x['stock_name']}" for x in cross["foreign_sell_etf_buy"][:5]]) or "無顯著重疊"),
        "- **備註**：外資買進主動型 ETF 受益憑證屬於次級市場交易，不等同基金經理人直接買進成分股。",
        "",
        "## 5. 尚未更新或待確認資料",
        f"- 尚未公布當日完整持股之 ETF：{', '.join(pending_etfs) if pending_etfs else '全數已更新完畢'}（排程將於 23:00 前每 15 分鐘自動補抓並更新本報告）。"
    ])
    return "\n".join(lines)
