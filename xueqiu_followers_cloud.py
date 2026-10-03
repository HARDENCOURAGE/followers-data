# -*- coding: utf-8 -*-
"""雪球全市场关注人数采集 - 云端版 v2（自动翻页版）"""
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

def crawl(market, type_, label, max_pages=300):
    frames = []
    for p in range(1, max_pages + 1):
        url = ("https://xueqiu.com/service/v5/stock/screener/quote/list"
               f"?page={p}&size=30&order=desc&orderby=percent&order_by=percent"
               f"&market={market}&type={type_}")
        d = []
        for a in range(3):
            try:
                d = s.get(url, verify=False, timeout=30).json()["data"]["list"]
                break
            except Exception as e:
                print(f"{label} p{p} retry{a+1}: {e}")
                time.sleep(random.uniform(5, 10))
        if not d:
            break
        frames.append(pd.DataFrame(d))
        print(f"{label} p{p}: {len(d)}")
        time.sleep(random.uniform(1.5, 4))
        if len(d) < 30:
            break
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

a = crawl("CN", "sh_sz", "A股")   # 全A股约180页
h = crawl("HK", "hk", "港股")     # 港股约90页

df = pd.concat([a, h], ignore_index=True)
df = (df[["symbol", "name", "followers"]]
      .dropna(subset=["symbol"]).drop_duplicates(subset="symbol")
      .sort_values("followers", ascending=False))
print(f"total {len(df)}")

sh = df[df.symbol.str.startswith(("SH6", "SH9"))]
sz = df[df.symbol.str.startswith(("SZ0", "SZ2", "SZ3"))]
hk = df[~df.index.isin(sh.index.union(sz.index))]

sh.to_csv(f"{OUT}/f_{today}_sh.csv", index=False)
sz.to_csv(f"{OUT}/f_{today}_sz.csv", index=False)
hk.to_csv(f"{OUT}/f_{today}_hk.csv", index=False)
pd.DataFrame([{"date": today, "sh": len(sh), "sz": len(sz), "hk": len(hk), "total": len(df)}]).to_csv(
    f"{OUT}/f_{today}_meta.csv", index=False)
print("done")
