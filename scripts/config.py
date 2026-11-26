import pytz
from datetime import datetime

TZ = pytz.timezone("Asia/Taipei")

# 優先固定追蹤的主動型 ETF 清單 (00981A 置頂)
CORE_ETFS = [
    {"code": "00981A", "name": "主動統一台股增長", "issuer": "ezmoney", "priority": 1},
    {"code": "00980A", "name": "主動野村臺灣優選", "issuer": "nomura", "priority": 2},
    {"code": "00982A", "name": "主動群益台灣強棒", "issuer": "capital", "priority": 3},
    {"code": "00984A", "name": "主動安聯台灣高息", "issuer": "allianz", "priority": 4},
    {"code": "00991A", "name": "主動復華未來50", "issuer": "fhtrust", "priority": 5},
    {"code": "00992A", "name": "主動群益科技創新", "issuer": "capital", "priority": 6},
    {"code": "00993A", "name": "主動安聯台灣成長", "issuer": "allianz", "priority": 7},
    {"code": "00995A", "name": "主動中信台灣卓越", "issuer": "ctbc", "priority": 8},
    {"code": "00403A", "name": "主動元大台灣領航", "issuer": "yuanta", "priority": 9},
    {"code": "00405A", "name": "主動富邦台灣旗艦", "issuer": "fubon", "priority": 10},
    {"code": "00406A", "name": "主動國泰台灣動能", "issuer": "cathay", "priority": 11},
]

# 常見台股產業分類映射 (系統會結合 TWSE 官方產業別與此關鍵字細分)
SECTOR_MAPPING = {
    "2330": "半導體", "2454": "半導體", "2303": "半導體", "3711": "半導體", "3034": "半導體",
    "2379": "半導體", "3661": "半導體", "3443": "半導體", "5274": "半導體", "6415": "半導體",
    "2382": "AI 伺服器", "3231": "AI 伺服器", "6669": "AI 伺服器", "2356": "AI 伺服器", "2317": "AI 伺服器",
    "3017": "散熱", "3324": "散熱", "3653": "散熱", "2421": "散熱", "6230": "散熱",
    "2383": "PCB", "6274": "PCB", "6213": "PCB", "3037": "PCB", "8046": "PCB", "3189": "PCB", "2313": "PCB",
    "2345": "網通", "3596": "網通", "5388": "網通", "6285": "網通", "4977": "網通",
    "2408": "記憶體", "2344": "記憶體", "8299": "記憶體", "3260": "記憶體", "4967": "記憶體",
    "2308": "電子零組件", "2327": "電子零組件", "3008": "電子零組件", "2059": "電子零組件", "1519": "傳產",
    "2881": "金融", "2882": "金融", "2891": "金融", "2886": "金融", "2884": "金融",
}

def now_tw():
    return datetime.now(TZ)
