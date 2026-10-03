# -*- coding: utf-8 -*-
"""雪球全市场采集 - 云端版 v4（完整字段：关注数+行情+估值）"""
import time, random, os, requests, urllib3, pandas as pd
from datetime import datetime, timezone, timedelta
urllib3.disable_warnings()

BJ = timezone(timedelta(hours=8))
today = datetime.now(BJ).strftime("%Y%m%d")
OUT = "data"
os.makedirs(OUT, exist_ok=True)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
    "Referer": "https://xueqiu.com",
})
s.get("https://xueqiu.com", verify=False, timeout=15)

def get_json(url, label):
    for a in range(3):
        try:
            return s.get(url, verify=False, timeout=30).json()
        except Exception as e:
            print(f"{label} retry{a+1}: {e}")
            time.sleep(random.uniform(5, 10))
    return {}

def crawl_list(market, type_, label, max_pages=300):
    frames = []
    for p in range(1, max_pages + 1):
        url = ("https://xueqiu.com/service/v5/stock/screener/quote/list"
               f"?page={p}&size=30&order=desc&orderby=percent&order_by=percent"
               f"&market={market}&type={type_}")
        d = get_json(url, f"{label} p{p}").get("data", {}).get("list", [])
        if not d:
            break
        frames.append(pd.DataFrame(d))
        print(f"{label} p{p}: {len(d)}")
        time.sleep(random.uniform(1.5, 4))
        if len(d) < 30:
            break
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

a = crawl_list("CN", "sh_sz", "A股")
h = crawl_list("HK", "hk", "港股")
df = pd.concat([a, h], ignore_index=True)
df = df.dropna(subset=["symbol"]).drop_duplicates(subset="symbol")
print(f"pass1 total: {len(df)}")

# 昨收 = 现价 - 涨跌额（列表接口带 chg，零成本）
for c in ["current", "chg", "followers", "market_capital", "turnover_rate", "percent"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
df["last_close"] = (df["current"] - df["chg"]).round(4)

# pass2: 批量详情补 PE/PB/股息率（全部股票，30只/次）
targets = df["symbol"].tolist()
print(f"pass2 targets: {len(targets)}")
pe, pb, dy = {}, {}, {}
for i in range(0, len(targets), 30):
    chunk = ",".join(targets[i:i+30])
    url = f"https://stock.xueqiu.com/v5/stock/batch/quote.json?symbol={chunk}&extend=detail"
    items = get_json(url, f"detail {i}").get("data", {}).get("items", [])
    for it in items:
        q = it.get("quote", {})
        sym = q.get("symbol")
        pe[sym] = q.get("pe_ttm")
        pb[sym] = q.get("pb")
        dy[sym] = q.get("dividend_yield")
    if i % 600 == 0:
        print(f"pass2 {i}/{len(targets)}")
    time.sleep(random.uniform(0.8, 2))

df["pe_ttm"] = df["symbol"].map(pe)
df["pb"] = df["symbol"].map(pb)
df["dividend_yield"] = df["symbol"].map(dy)

cols = ["symbol", "name", "followers", "current", "last_close", "percent",
        "market_capital", "turnover_rate", "pe_ttm", "pb", "dividend_yield"]
cols = [c for c in cols if c in df.columns]
df = df[cols].sort_values("followers", ascending=False)

sh = df[df.symbol.str.startswith(("SH6", "SH9"))]
sz = df[df.symbol.str.startswith(("SZ0", "SZ2", "SZ3"))]
hk = df[~df.index.isin(sh.index.union(sz.index))]
sh.to_csv(f"{OUT}/f_{today}_sh.csv", index=False)
sz.to_csv(f"{OUT}/f_{today}_sz.csv", index=False)
hk.to_csv(f"{OUT}/f_{today}_hk.csv", index=False)
pd.DataFrame([{"date": today, "sh": len(sh), "sz": len(sz), "hk": len(hk),
               "pe_filled": df["pe_ttm"].notna().sum(), "total": len(df)}]).to_csv(
    f"{OUT}/f_{today}_meta.csv", index=False)
print("done")
