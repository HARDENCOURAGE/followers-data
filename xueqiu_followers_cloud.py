# -*- coding: utf-8 -*-
"""雪球全市场采集 - 云端版 v5（完整字段 + T-3变化率 + 精简传输文件）"""
import time, random, os, glob, re, requests, urllib3, pandas as pd
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

for c in ["current", "chg", "followers", "market_capital", "turnover_rate", "percent"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
df["last_close"] = (df["current"] - df["chg"]).round(4)

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

def board(sym):
    if sym.startswith("SH688"): return "科创板"
    if sym.startswith(("SH600","SH601","SH603","SH605")): return "沪市主板"
    if sym.startswith(("SZ300","SZ301","SZ302")): return "创业板"
    if sym.startswith(("SZ000","SZ001","SZ002","SZ003")): return "深市主板"
    if sym.startswith(("SH9","SZ2")): return "B股"
    if sym.startswith("08"): return "港股GEM"
    return "港股主板"

df["board"] = df["symbol"].map(board)
df = df.sort_values("followers", ascending=False)

sh = df[df.symbol.str.startswith(("SH6", "SH9"))]
sz = df[df.symbol.str.startswith(("SZ0", "SZ2", "SZ3"))]
hk = df[~df.index.isin(sh.index.union(sz.index))]
sh.to_csv(f"{OUT}/f_{today}_sh.csv", index=False)
sz.to_csv(f"{OUT}/f_{today}_sz.csv", index=False)
hk.to_csv(f"{OUT}/f_{today}_hk.csv", index=False)

# ---- v5: 与上一期对比算 T-3 变化率(历史文件在检出目录里) ----
prev_f = {}
for b in ["sh", "sz", "hk"]:
    files = sorted(glob.glob(f"{OUT}/f_*_{b}.csv"))
    files = [f for f in files if re.search(r"f_(\d{8})_", f).group(1) < today]
    if files:
        old = pd.read_csv(files[-1])
        if "followers" in old.columns:
            for sym, f in zip(old["symbol"], old["followers"]):
                try: prev_f[sym] = float(f)
                except: pass
print(f"prev symbols: {len(prev_f)}")

d = df.copy()
d["prev"] = d["symbol"].map(prev_f)
d["rate_3d"] = (d["followers"] - d["prev"]) / d["prev"] * 100
d["chg_3d"] = d["followers"] - d["prev"]
qual = d[(d["followers"] >= 100) & (d["prev"] > 0) & (d["rate_3d"].notna())]
top = qual.sort_values("rate_3d", ascending=False).groupby(
    qual["board"].str.contains("港").map({True: "hk", False: "cn"})).head(300)
top = top.sort_values("rate_3d", ascending=False)
top.to_csv(f"{OUT}/f_{today}_top_rates.csv", index=False)
d[["symbol", "followers", "board"]].to_csv(f"{OUT}/f_{today}_followers.csv", index=False)

pd.DataFrame([{"date": today, "sh": len(sh), "sz": len(sz), "hk": len(hk),
               "pe_filled": df["pe_ttm"].notna().sum(), "total": len(df),
               "prev_matched": int(d["prev"].notna().sum()),
               "qualifying": len(qual)}]).to_csv(f"{OUT}/f_{today}_meta.csv", index=False)
print(f"top_rates: {len(top)}, qualifying: {len(qual)}")
