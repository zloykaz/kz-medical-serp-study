"""Список сайтов из снимка выдачи для разметки по codebook.md (п. 5 методики).

  python build_domains.py SNAPSHOT.jsonl.gz OUT_DIR [GOTO.csv [PREV_DOMAINS.csv]]

PREV_DOMAINS.csv — прежний список ТОГО ЖЕ снимка: его случайная 10 %-выборка для человека сохраняется,
жребий (тот же seed) тянется только среди сайтов, которых в прежнем списке не было. Если в снимке есть
нераскрытые ссылки google.com/goto (нет таблицы или ссылка не раскрылась), скрипт останавливается.

Сайт обычного результата — из breadcrumb (адрес в url бывает переадресацией google.com/goto), без адреса —
из website_name «Платформа · автор». Сайт ссылки ответа ИИ — из её url; если url — переадресация
google.com/goto, адрес берётся из GOTO.csv (resolve_goto.py, отступление 3), нераскрытая ссылка идёт
в единицу «?goto» и останавливает скрипт, а не уходит в google.com. Единица разметки — хост без
www./m., метки punycode раскодированы в кириллицу; у платформ (YouTube, Instagram…) — платформа + автор, если автор виден.
Внимание (метрика 2) — частота × вес позиции по трём наборам весов ctr_curves.md; запросы — выборки
после правила многозначных (u_rule_snapshot1.csv).
"""
import csv, gzip, json, os, random, sys
from collections import defaultdict
from urllib.parse import urlparse

SEED = 20261030
CTR = {1: 18.08, 2: 13.44, 3: 8.91, 4: 6.66, 5: 4.04, 6: 3.02, 7: 2.15, 8: 1.79, 9: 1.06, 10: 1.19}
WEIGHTS = {"a": lambda p: CTR[p], "b": lambda p: 1.0 if p <= 3 else 0.5, "c": lambda p: 1.0}
PLATFORMS = {"youtube.com": "YouTube", "music.youtube.com": "YouTube", "instagram.com": "Instagram",
             "facebook.com": "Facebook", "threads.net": "Threads", "threads.com": "Threads",
             "tiktok.com": "TikTok", "t.me": "Telegram", "dzen.ru": "Дзен", "vk.com": "VK",
             "kaspi.kz": "Kaspi", "ok.ru": "OK", "reddit.com": "Reddit"}
NAME_TO_HOST = {"YouTube": "youtube.com", "Instagram": "instagram.com", "Facebook": "facebook.com",
                "Threads": "threads.net", "TikTok": "tiktok.com", "Telegram": "t.me", "VK": "vk.com",
                "Reddit": "reddit.com"}
HERE = os.path.dirname(os.path.abspath(__file__))


def unpuny(label: str) -> str:
    """xn--b1aghuag4a → инновет: адрес ответа ИИ приходит в punycode, подпись выдачи — кириллицей."""
    if not label.startswith("xn--"):
        return label
    try:
        return label.encode("ascii").decode("idna")
    except UnicodeError:
        return label


def host_of(url: str) -> str:
    """Единый вид хоста: без www./m., строчными, метки punycode — кириллицей (отступление 3)."""
    h = urlparse(url.split(" ")[0].strip()).hostname or ""
    for p in ("www.", "m."):
        if h.startswith(p):
            h = h[len(p):]
    return ".".join(unpuny(x) for x in h.lower().split("."))


def organic_unit(it: dict) -> tuple[str, str]:
    """(единица, платформа)."""
    name = it.get("website_name") or ""
    bc = it.get("breadcrumb") or ""
    host = host_of(bc) if bc.startswith("http") else ""
    if "·" in name:
        plat, author = (s.strip() for s in name.split("·", 1))
        phost = NAME_TO_HOST.get(plat) or (host if host in PLATFORMS else "")
        if phost:
            return f"{phost}/{author}", PLATFORMS[phost]
    if not host:
        return f"?{name}", ""
    return host, PLATFORMS.get(host, "")


def load_goto(path: str | None) -> dict[str, str]:
    """goto-адрес → настоящий адрес (только раскрытые)."""
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["goto"]: r["url"] for r in csv.DictReader(f) if r["status"] == "ok"}


def norm_unit(unit: str) -> str:
    """Имя единицы из прежнего списка в нынешнем виде (хост punycode → кириллица)."""
    host, sep, rest = unit.partition("/")
    return ".".join(unpuny(x) for x in host.split(".")) + sep + rest


def is_goto(url: str) -> bool:
    return "google." in (urlparse(url).hostname or "") and urlparse(url).path == "/goto"


def real_url(url: str, goto: dict[str, str]) -> str:
    """Настоящий адрес ссылки; нераскрытая переадресация Google — пустая строка."""
    u = goto.get(url, url)
    return "" if is_goto(u) else u


def used_queries() -> dict[str, tuple[str, int]]:
    """keyword → (выборка, частота) после правила многозначных и замены запасными."""
    out_rule = {}
    with open(os.path.join(HERE, "u_rule_snapshot1.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out_rule[r["keyword"]] = r
    dropped = {k for k, r in out_rule.items() if r["decision"] == "выбыл"}
    replacements = {r["replaced_by"] for r in out_rule.values() if r["replaced_by"]}
    q = {}
    for name, fn in (("main", "sample_main.csv"), ("kk", "sample_kk.csv"),
                     ("check", "sample_check.csv"), ("reserve", "sample_reserve.csv")):
        with open(os.path.join(HERE, fn), encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["keyword"] in dropped:
                    continue
                if name == "reserve":
                    if r["keyword"] not in replacements:
                        continue
                    name_ = "main"
                else:
                    name_ = name
                q[r["keyword"]] = (name_, int(r["volume"]))
    return q


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    goto = load_goto(sys.argv[3] if len(sys.argv) > 3 else None)
    prev = None
    if len(sys.argv) > 4:
        with open(sys.argv[4], encoding="utf-8") as f:
            prev = {}
            for r in csv.DictReader(f):  # два имени одного сайта (punycode и кириллица) — пометка не теряется
                u = norm_unit(r["unit"])
                prev[u] = prev.get(u) or r["human_check"]
    os.makedirs(out, exist_ok=True)
    queries = used_queries()
    units = defaultdict(lambda: {"platform": "", "org_places": 0, "ai_refs": 0, "paid": 0, "queries": set(),
                                 "att": {"a": 0.0, "b": 0.0, "c": 0.0}, "titles": [], "urls": [], "names": set()})
    total = {"a": 0.0, "b": 0.0, "c": 0.0}
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            kw = row["params"]["keyword"]
            if kw not in queries:
                continue
            vol = queries[kw][1]
            for it in row["response"][0].get("items") or []:
                if it["type"] == "organic" and it["rank_group"] <= 10:
                    u, plat = organic_unit(it)
                    d = units[u]
                    d["platform"] = d["platform"] or plat
                    d["org_places"] += 1
                    d["queries"].add(kw)
                    if it.get("website_name"):
                        d["names"].add(it["website_name"])
                    if len(d["titles"]) < 3:
                        d["titles"].append(it.get("title") or "")
                    for k, w in WEIGHTS.items():
                        d["att"][k] += vol * w(it["rank_group"])
                        total[k] += vol * w(it["rank_group"])
                elif it["type"] == "ai_overview":
                    for ref in it.get("references") or []:
                        url = real_url(ref.get("url") or "", goto)
                        h = host_of(url) if url else ("?goto" if ref.get("url") else "")
                        # на gov.kz сайты разных организаций: категория — по организации (codebook, п. 6)
                        parts = urlparse(url).path.split("/")
                        if h == "gov.kz" and len(parts) > 2 and parts[1] in ("org", "memleket"):
                            h = "gov.kz/" + "/".join(parts[1:4] if parts[1] == "memleket" else parts[1:3])
                        if not h:
                            continue
                        d = units[h]
                        d["platform"] = d["platform"] or PLATFORMS.get(h, "")
                        d["ai_refs"] += 1
                        d["queries"].add(kw)
                        if ref.get("source"):
                            d["names"].add(ref["source"])
                        if url and len(d["urls"]) < 3 and url not in d["urls"]:
                            d["urls"].append(url)
                        if len(d["titles"]) < 3:
                            d["titles"].append(ref.get("title") or "")
                elif it["type"] == "paid":
                    h = host_of(real_url(it.get("url") or "", goto)) or host_of(it.get("breadcrumb") or "")
                    if h:
                        units[h]["paid"] += 1
                        units[h]["queries"].add(kw)

    if "?goto" in units:
        sys.exit(f"нераскрытых ссылок google.com/goto: {units['?goto']['ai_refs']} — сначала resolve_goto.py, "
                 "его таблицу — третьим аргументом")

    rows = []
    for u, d in units.items():
        rows.append({"unit": u, "platform": d["platform"], "org_places": d["org_places"], "ai_refs": d["ai_refs"],
                     "paid": d["paid"], "n_queries": len(d["queries"]),
                     **{f"att_{k}": round(100 * d["att"][k] / total[k], 4) for k in WEIGHTS},
                     "names": " | ".join(sorted(d["names"]))[:200], "titles": " | ".join(d["titles"])[:400],
                     "sample_urls": " ".join(d["urls"])})
    rows.sort(key=lambda r: -r["att_a"])

    # человек: все сайты, дающие 80 % внимания при любом из трёх наборов весов, + 10 % остальных (жребий)
    top80 = set()
    for k in WEIGHTS:
        acc = 0.0
        for r in sorted(rows, key=lambda r: -r[f"att_{k}"]):
            if acc >= 80.0 or r[f"att_{k}"] == 0:
                break
            top80.add(r["unit"]); acc += r[f"att_{k}"]
    rest = sorted(r["unit"] for r in rows if r["unit"] not in top80)
    if prev is None:
        rnd = random.Random(SEED).sample(rest, round(len(rest) * 0.10))
    else:
        # отступление 3: прежняя случайная выборка остаётся, 10 % добираются только из новых сайтов
        kept = [u for u in rest if prev.get(u) == "10%"]
        new = [u for u in rest if u not in prev]
        rnd = kept + random.Random(SEED).sample(new, round(len(new) * 0.10))
    for r in rows:
        r["human_check"] = "80%" if r["unit"] in top80 else ("10%" if r["unit"] in rnd else "")

    fields = list(rows[0])
    tag = os.path.basename(src).split("_")[0]  # snapshot1_serp.jsonl.gz → snapshot1
    with open(os.path.join(out, f"domains_{tag}.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields); w.writeheader(); w.writerows(rows)
    with open(os.path.join(out, f"human_check_{tag}.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fields); w.writeheader()
        w.writerows([r for r in rows if r["human_check"]])
    print(f"запросов {len(queries)}, сайтов {len(rows)} (в обычных {sum(r['org_places'] > 0 for r in rows)}, "
          f"только в ответе ИИ {sum(r['org_places'] == 0 and r['ai_refs'] > 0 for r in rows)}), "
          f"80 % внимания {len(top80)}, 10 % остальных {len(rnd)} из {len(rest)}")


if __name__ == "__main__":
    main()
