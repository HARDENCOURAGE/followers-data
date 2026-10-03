# -*- coding: utf-8 -*-
"""
雪球全市场关注人数采集 - GitHub Actions 云端版
输出紧凑3列(symbol,name,followers), 按市场拆4个文件, 便于下游单次读取
"""
import time, random, os, requests, urllib3, pandas as pd
from datetime import datetime, timezone, timedelta
urllib3.disable_warnings()

BJ = timezone(timedelta(hours=8))
today = datetime.now(BJ).strftime("%Y%m%d")
OUT = "data"                      # 仓库内目录
os.makedirs(OUT, exist_ok=True)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
    "Referer": "https://xueqiu.com",
})
s.get("https://xueqiu.com", verify=False, timeout=15)
ts = int(time.time() * 1000)

def fetch(url):
    for a in range(3):
        try:
            return s.get(url, verify=False, timeout=30).json()["data"]["list"]
        except Exception as e:
            print(f"retry {a+1}: {e}"); time.sleep(random.uniform(5, 10))
    return []

frames = []
# A股 2页 + 港股 3页
for p in range(1, 3):
    d = fetch("https://xueqiu.com/service/v5/stock/screener/quote/list"
              f"?page={p}&size=5000&order=desc&orderby=percent&order_by=percent"
              f"&market=CN&type=sh_sz&_={ts}")
    print(f"A股 p{p}: {len(d)}"); frames.append(pd.DataFrame(d)); time.sleep(random.uniform(2, 4))
for p in range(1, 4):
    d = fetch("https://xueqiu.com/service/v5/stock/screener/quote/list"
              f"?page={p}&size=1000&order=desc&orderby=percent&order_by=percent"
              f"&market=HK&type=hk&_={ts}")
    print(f"港股 p{p}: {len(d)}")
    if not d: break
    frames.append(pd.DataFrame(d)); time.sleep(random.uniform(2, 4))

df = pd.concat(frames, ignore_index=True)
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
print("done:", os.listdir(OUT))
