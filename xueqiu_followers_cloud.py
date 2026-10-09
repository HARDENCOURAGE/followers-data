# -*- coding: utf-8 -*-
"""雪球全市场采集 - v12（多窗口变化率：T-3/7/30/90 + T-30增速榜 + 原始JSON传输层）"""
import time, random, os, re, glob, traceback
import requests, urllib3, pandas as pd
from datetime import datetime, timezone, timedelta
urllib3.disable_warnings()

BJ = timezone(timedelta(hours=8))
NOW = datetime.now(BJ)
today = NOW.strftime("%Y%m%d")
OUT = "data"
os.makedirs(OUT, exist_ok=True)

def log(*a):
    print(f"[{datetime.now(BJ).strftime('%H:%M:%S')}]", *a, flush=True)

s = requests.Session()
s.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
    "Referer": "https://xueqiu.com",
})
try:
    s.get("https://xueqiu.com", verify=False, timeout=15)
except Exception:
    traceback.print_exc()

def get_json(url, label):
    for a in range(3):
        try:
            return s.get(url, verify=False, timeout=30).json()
        except Exception as e:
            log(f"{label} retry{a+1}: {e}")
            time.sleep(random.uniform(5, 10))
    return {}

def stage(name):
    log(f"=== STAGE {name} start ===")

# ---------- STAGE 1: 采集列表 ----------
stage("crawl")
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
        if p % 20 == 0:
            log(f"{label} p{p}: {len(d)}")
        time.sleep(random.uniform(1.5, 4))
        if len(d) < 30:
            break
    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(columns=["symbol", "name"])

df = pd.concat([crawl_list("CN", "sh_sz", "A股"), crawl_list("HK", "hk", "港股")],
               ignore_index=True)
df = df.dropna(subset=["symbol"]).drop_duplicates(subset="symbol")
log(f"pass1 total: {len(df)}")
for c in ["current", "chg", "followers", "market_capital", "turnover_rate", "percent"]:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
df["last_close"] = (df["current"] - df["chg"]).round(4)

# ---------- STAGE 2: 估值补全 ----------
stage("detail")
pe, pb, dy = {}, {}, {}
targets = df["symbol"].tolist()
for i in range(0, len(targets), 30):
    chunk = ",".join(targets[i:i+30])
    items = get_json(f"https://stock.xueqiu.com/v5/stock/batch/quote.json?symbol={chunk}&extend=detail",
                     f"detail {i}").get("data", {}).get("items", [])
    for it in items:
        q = it.get("quote", {})
        pe[q.get("symbol")] = q.get("pe_ttm")
        pb[q.get("symbol")] = q.get("pb")
        dy[q.get("symbol")] = q.get("dividend_yield")
    if i % 1500 == 0:
        log(f"pass2 {i}/{len(targets)}")
    time.sleep(random.uniform(0.8, 2))
df["pe_ttm"], df["pb"], df["dividend_yield"] = df["symbol"].map(pe), df["symbol"].map(pb), df["symbol"].map(dy)
log(f"pe filled: {df['pe_ttm'].notna().sum()}")

# ---------- STAGE 3: 关注数兜底 ----------
stage("fill")
MISSING_BEFORE, FILLED = 0, 0
try:
    miss = df[df["followers"].isna() | (df["followers"] <= 0)]["symbol"].tolist()
    MISSING_BEFORE = len(miss)
    log(f"followers missing: {MISSING_BEFORE}")
    fill = {}
    for i, sym in enumerate(miss[:5000]):
        j = get_json(f"https://xueqiu.com/query/v1/symbol/search/status.json?count=1&page=1&symbol={sym}", sym)
        try:
            f = j["list"][0]["followers"]
            if f is not None:
                fill[sym] = float(f)
        except Exception:
            pass
        if (i + 1) % 300 == 0:
            log(f"fill {i+1}/{MISSING_BEFORE} got {len(fill)}")
        time.sleep(random.uniform(0.4, 0.9))
    if fill:
        idx = df.set_index("symbol")
        for sym, f in fill.items():
            try:
                idx.at[sym, "followers"] = f
            except Exception:
                pass
        df["followers"] = idx["followers"].values
    FILLED = len(fill)
    log(f"followers filled: {FILLED}")
except Exception:
    traceback.print_exc()

# ---------- STAGE 4: 板块分类 + 分市场落盘 ----------
stage("boards")
def board(sym):
    if sym.startswith("SH688"): return "科创板"
    if sym.startswith("SH689"): return "科创板CDR"
    if sym.startswith(("SH600","SH601","SH603","SH605")): return "沪市主板"
    if sym.startswith(("SZ300","SZ301","SZ302")): return "创业板"
    if sym.startswith(("SZ000","SZ001","SZ002","SZ003")): return "深市主板"
    if sym.startswith(("SH9","SZ2")): return "B股"
    if sym.startswith("08"): return "港股GEM"
    return "港股主板"

df["board"] = df["symbol"].map(board)
df = df.sort_values("followers", ascending=False)
out_cols = ["symbol","name","followers","current","last_close","percent",
            "market_capital","turnover_rate","pe_ttm","pb","dividend_yield"]
sh = df[df.symbol.str.startswith(("SH6", "SH9"))]
sz = df[df.symbol.str.startswith(("SZ0", "SZ2", "SZ3"))]
hk = df[~df.index.isin(sh.index.union(sz.index))]
sh[out_cols].to_csv(f"{OUT}/f_{today}_sh.csv", index=False)
sz[out_cols].to_csv(f"{OUT}/f_{today}_sz.csv", index=False)
hk[out_cols].to_csv(f"{OUT}/f_{today}_hk.csv", index=False)
log(f"sh {len(sh)} sz {len(sz)} hk {len(hk)}")

# ---------- STAGE 5: 多窗口变化率 ----------
stage("rates")
hist = {}
for b in ["sh", "sz", "hk"]:
    for fp in sorted(glob.glob(f"{OUT}/f_*_{b}.csv")):
        m = re.search(r"f_(\d{8})_", fp)
        if not m or m.group(1) >= today:
            continue
        try:
            old = pd.read_csv(fp, usecols=["symbol", "followers"])
        except Exception:
            continue
        for sym, f in zip(old["symbol"], old["followers"]):
            try:
                hist.setdefault(sym, {})[m.group(1)] = float(f)
            except Exception:
                pass
log(f"history symbols: {len(hist)}")

def prev_for(sym, days):
    target = (NOW.date() - timedelta(days=days)).strftime("%Y%m%d")
    snaps = hist.get(sym)
    if not snaps:
        return None
    cands = [d for d in snaps if d <= target]
    return snaps[max(cands)] if cands else None

d = df.copy()
for W in (3, 7, 30, 90):
    d[f"prev_{W}d"] = [prev_for(sym, W) for sym in d["symbol"]]
    d[f"rate_{W}d"] = (d["followers"] - d[f"prev_{W}d"]) / d[f"prev_{W}d"] * 100
    d[f"chg_{W}d"] = d["followers"] - d[f"prev_{W}d"]
log("rates computed")

base = d[(d["followers"] >= 100) & (d["rate_3d"].notna())]
key = base["board"].str.contains("港", na=False).map({True: "hk", False: "cn"})
top3 = base.sort_values("rate_3d", ascending=False).groupby(key).head(300)
rate_cols = ["symbol","name","board","followers","rate_3d","chg_3d","rate_7d","rate_30d","rate_90d",
             "current","last_close","percent","market_capital","turnover_rate","pe_ttm","pb","dividend_yield"]
top3[[c for c in rate_cols if c in top3.columns]].to_csv(f"{OUT}/f_{today}_top_rates.csv", index=False)
d[["symbol","followers","board"]].to_csv(f"{OUT}/f_{today}_followers.csv", index=False)

win = {W: int(d[f"rate_{W}d"].notna().sum()) for W in (3, 7, 30, 90)}
meta = {"date": today, "sh": len(sh), "sz": len(sz), "hk": len(hk),
        "pe_filled": int(df["pe_ttm"].notna().sum()), "total": len(df),
        "prev_matched": int(d["prev_3d"].notna().sum()),
        "qualifying": len(base),
        "win3": win[3], "win7": win[7], "win30": win[30], "win90": win[90],
        "followers_missing_before": MISSING_BEFORE, "followers_filled": FILLED,
        "hk_followers_filled": int(df[df["board"].str.contains("港", na=False)]["followers"].notna().sum())}
pd.DataFrame([meta]).to_csv(f"{OUT}/f_{today}_meta.csv", index=False)
log(f"meta: {meta}")

# ---------- STAGE 6: report.md ----------
stage("report")
def w2yi(v):
    try: return f"{float(v)/1e8:.0f}"
    except Exception: return ""
def pct(v):
    try: return f"{float(v):.1f}"
    except Exception: return "—"
def fw(v):
    try:
        v = float(v)
        return f"{v/10000:.1f}万" if v >= 10000 else f"{v:.0f}"
    except Exception: return ""
def row_md(r):
    return (f"|{r['symbol']}|{r['name']}|{r['board']}|{fw(r['followers'])}"
            f"|{pct(r['rate_3d'])}|{pct(r['rate_7d'])}|{pct(r['rate_30d'])}|{pct(r['rate_90d'])}"
            f"|{fw(r['chg_3d'])}|{r.get('current','')}|{pct(r.get('percent'))}"
            f"|{w2yi(r.get('market_capital'))}|{pct(r.get('turnover_rate'))}"
            f"|{pct(r.get('pe_ttm'))}|{pct(r.get('pb'))}|{pct(r.get('dividend_yield'))}|")
HDR = ("|代码|名称|板块|关注T|T-3%|T-7%|T-30%|T-90%|净增|现价|涨幅%|市值亿|换手%|PE|PB|股息率%|\n"
       "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
md = [f"# 关注数变化率日报 {today}", "",
      f"全市场 {len(df)} 只 | 入围(关注>=100) {len(base)} 只 | 窗口覆盖 T-3:{win[3]} T-7:{win[7]} T-30:{win[30]} T-90:{win[90]} (—=积累中)", ""]
for label, is_hk in [("A股", False), ("港股", True)]:
    sub = top3[top3["board"].str.contains("港", na=False) == is_hk]
    md += [f"## {label} TOP300（T-3变化率降序）", "", HDR]
    md += [row_md(r) for _, r in sub.iterrows()]
    md.append("")
for label, is_hk in [("A股", False), ("港股", True)]:
    q30 = d[(d["followers"] >= 100) & (d["rate_30d"].notna())]
    q30 = q30[q30["board"].str.contains("港", na=False) == is_hk].sort_values("rate_30d", ascending=False).head(100)
    md += [f"## {label} T-30 增速 TOP100", "", HDR]
    if len(q30):
        md += [row_md(r) for _, r in q30.iterrows()]
    else:
        md.append("（积累中：T-30 窗口需约30天历史）")
    md.append("")
os.makedirs("report", exist_ok=True)
with open(f"report/r_{today}.md", "w", encoding="utf-8") as f:
    f.write("\n".join(md))
log(f"report.md rows: cn={len(top3[top3['board'].str.contains('港',na=False)==False])} hk={len(top3[top3['board'].str.contains('港',na=False)])}")

# ---------- STAGE 7: raw JSON-in-HTML ----------
stage("raw")
try:
    os.makedirs("raw", exist_ok=True)
    raw_cols = out_cols + ["board"]
    def esc(v):
        if v is None or (isinstance(v, float) and v != v):
            return ""
        return str(v).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for part, tag in [(sh, "sh"), (sz, "sz"), (hk, "hk")]:
        half = (len(part) + 1) // 2
        for i, chunkdf in enumerate([part.head(half), part.tail(len(part) - half)], 1):
            lines = ["{" + ",".join(f'\"{k}\":\"{esc(r.get(k))}\"' for k in raw_cols) + "}"
                     for _, r in chunkdf.iterrows()]
            html = ('<html><head><meta charset="utf-8"></head><body><pre>'
                    + "\n".join(lines) + "</pre></body></html>")
            with open(f"raw/{today}_{tag}_{i}.html", "w", encoding="utf-8") as f:
                f.write(html)
            log(f"raw {tag}_{i}: {len(chunkdf)} rows")
except Exception:
    traceback.print_exc()

log("ALL DONE")
