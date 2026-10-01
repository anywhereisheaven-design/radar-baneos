"""Radar de baneos: revisa las fuentes, calcula el % de peligro y avisa por ntfy."""
import json, os, re, sys, time, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
TH = int(os.environ.get("THRESHOLD") or 40)
STATE = "state.json"
KW = [(r"ban ?waves?|oleadas? de ban|banwave", 25), (r"baneo|banead|banned|\bbans?\b", 8),
      (r"patch|parche|detected|detectad", 15), (r"hyperion|byfron|anti-?cheat", 10),
      (r"delta", 5), (r"updat|actualiz|version|mantenim|maintenance", 6)]
REC = {"PELIGRO": "Riesgo alto. No ejecutes hasta que el ejecutor confirme que ya está actualizado.",
       "PRECAUCION": "Hay señales. Espera 2 o 3 días antes de ejecutar.",
       "AVISO": "Algo se mueve. Revisa las fuentes antes de ejecutar."}
NEWS = ['roblox ("ban wave" OR "ban waves" OR byfron OR hyperion)',
        "roblox ola de baneos OR baneos masivos",
        '"delta executor" OR "roblox executor" (patched OR update OR detected OR actualización)',
        "roblox anti-cheat update"]
REDDIT = ["roblox ban wave", '"delta executor"', "roblox hyperion byfron"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (radar-baneos)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", "replace")


def fresh(ts):
    age = time.time() - ts
    return 1 if age < 86400 else .6 if age < 259200 else .3 if age < 604800 else 0


def st():
    j = json.loads(get("https://status.roblox.com/api/v2/summary.json"))
    for i in j.get("incidents", []) + j.get("scheduled_maintenances", []):
        d = i.get("updated_at") or i["created_at"]
        yield i["name"], i.get("shortlink") or "https://status.roblox.com", datetime.fromisoformat(d.replace("Z", "+00:00")).timestamp(), 12


def versions(S):
    got = 0
    for b in ("WindowsPlayer", "AndroidApp"):
        try:
            v = json.loads(get(f"https://clientsettingscdn.roblox.com/v2/client-version/{b}"))["clientVersionUpload"]
        except Exception as e:
            print("versión", b, "falló:", e)
            continue
        got += 1
        old = S.setdefault("ver", {}).get(b)
        if old is None:
            S["ver"][b] = {"v": v, "t": 0}
        elif old["v"] != v:
            S["ver"][b] = {"v": v, "t": time.time()}
    if not got:
        raise RuntimeError("sin respuesta")
    for b, o in S["ver"].items():
        if o["t"]:
            yield f"Roblox sacó una versión nueva del cliente ({b})", "https://status.roblox.com", o["t"], 20


def rss(u):
    for i in ET.fromstring(get(u)).iter("item"):
        yield i.findtext("title", ""), i.findtext("link", ""), parsedate_to_datetime(i.findtext("pubDate")).timestamp(), 0


def gnews(q):
    return rss("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:7d") + "&hl=es-419&gl=MX&ceid=MX:es-419")


def bing(q):
    return rss("https://www.bing.com/news/search?format=rss&q=" + urllib.parse.quote(q))


def reddit(q):
    j = json.loads(get("https://www.reddit.com/search.json?q=" + urllib.parse.quote(q) + "&sort=new&t=week&limit=30"))
    for c in j["data"]["children"]:
        d = c["data"]
        yield d["title"], "https://www.reddit.com" + d["permalink"], d["created_utc"], 0


def push(title, body, prio, click):
    h = {"Title": title, "Priority": str(prio), "Tags": "rotating_light" if prio >= 4 else "white_check_mark"}
    if click:
        h["Click"] = click.encode("ascii", "ignore").decode()
    urllib.request.urlopen(urllib.request.Request(f"https://ntfy.sh/{TOPIC}", body.encode(), h), timeout=20)


def main():
    S = json.load(open(STATE)) if os.path.exists(STATE) else {"ln": 0}
    json.dump(S, open(STATE, "w"))
    if not TOPIC:
        sys.exit("Falta el secreto NTFY_TOPIC")
    if os.environ.get("TEST"):
        push("PRUEBA - Radar de baneos", "Si ves esto, las alertas funcionan.", 3, "")
        return
    srcs = [("estado de Roblox", st), ("versiones", lambda: versions(S))]
    srcs += [("google: " + q, lambda q=q: gnews(q)) for q in NEWS]
    srcs += [("bing: " + q, lambda q=q: bing(q)) for q in NEWS[:3]]
    srcs += [("reddit: " + q, lambda q=q: reddit(q)) for q in REDDIT]
    items, ok = {}, 0
    for name, fn in srcs:
        try:
            for t, u, ts, m in list(fn()):
                k = round(min(30, max(m, sum(p[1] for p in KW if re.search(p[0], t, re.I)))) * fresh(ts))
                key = re.sub(r"\W+", " ", t.lower())[:80]
                if k > 0 and (key not in items or items[key][0] < k):
                    items[key] = (k, u, t)
            ok += 1
        except Exception as e:
            print(name, "falló:", e)
        time.sleep(1)
    print(f"{ok}/{len(srcs)} fuentes respondieron")
    if not ok:
        return
    ev = sorted(items.values(), key=lambda x: -x[0])[:30]
    v = min(100, round(1.2 * sum(e[0] * .8 ** i for i, e in enumerate(ev))))
    ln = S.get("ln", 0)
    if v < TH:
        ln = 0
    elif not ln or v >= ln + 10:
        ln = v
        lvl = "PELIGRO" if v >= 60 else "PRECAUCION" if v >= 25 else "AVISO"
        top = ev[0] if ev else None
        push(f"RADAR {v}% - {lvl}", (top[2] + ". " if top else "") + REC[lvl], 5 if v >= 60 else 4, top[1] if top else "")
    S["ln"] = ln
    json.dump(S, open(STATE, "w"))
    print("peligro", v)


main()
