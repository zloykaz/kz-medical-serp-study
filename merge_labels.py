"""Слить разметку сайтов всех раундов и выбрать сайты для человека (п. 5 методики, отступления 2–4).

  python merge_labels.py OUT_DIR

Раунды (пути ниже, в ROUNDS): список, по которому шла разметка, и ответы двух моделей. Метка сайта берётся из
последнего раунда, где модель на него ответила (повтор отклонённых пачек дополняет первый раунд). Имена сайтов
старых списков приводятся к нынешнему виду (build_domains.norm_unit: punycode → кириллица); если у одного
сайта два старых имени с разными ответами (категория, связь с фармой, собственность или страна), сайт идёт
человеку.
Сайты исследования — объединение списков снимков 1–3 (domains/fixed). Внимание сайта — среднее по трём
снимкам его доли внимания (att_a/b/c; снимок, где сайта нет, — 0).
Человеку (колонка why, причины через «; »):
  - сайты снимка 1 по правилу отступлений 2–3 (human_check_snapshot1: 80 % внимания и 10 % жребием);
  - по отступлению 3: сайты 80 % внимания по трём снимкам вместе при любом наборе весов, которых нет выше,
    и 10 % остальных новых сайтов (снимки 2–3) жребием, seed 20261030;
  - все сайты с разной категорией у моделей, пометкой «спорно», ненайденной цитатой или без ответа модели.
Пишет OUT_DIR/labels_all.csv (все сайты) и OUT_DIR/human_check_all.csv (только для человека, по убыванию
внимания, веса а).
"""
import csv, os, random, sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # запуск с python -I
from build_domains import SEED, norm_unit  # noqa: E402
from compare_domains import COMPARED, FIELDS, evidence_text, labels, quote_ok, settle  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "domains")
MODELS = ("deepseek-v4.1-flash", "qwen3.8-flash")
# (список, по которому шла разметка; папка ответов) — в порядке раундов, поздний дополняет ранний
ROUNDS = [(os.path.join(D, "domains_snapshot1.csv"), os.path.join(D, "out_snapshot1")),
          (os.path.join(D, "round2", "retry_deepseek.csv"), os.path.join(D, "round2", "out_retry")),
          (os.path.join(D, "round2", "to_label_new.csv"), os.path.join(D, "round2", "out_new")),
          # повтор отклонённых пачек раунда 2 по одному сайту (deepseek и qwen — свои списки, одна папка)
          (os.path.join(D, "round2", "retry2_deepseek.csv"), os.path.join(D, "round2", "out_retry2"))]
SNAPSHOTS = [os.path.join(D, "fixed", f"domains_snapshot{n}.csv") for n in (1, 2, 3)]
WEIGHTS = ("a", "b", "c")


def read(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def model_labels() -> tuple[dict, set]:
    """{модель: {сайт: ответ}}, сайты с противоречивыми ответами одной модели под двумя старыми именами."""
    out = {m: {} for m in MODELS}
    conflict = set()
    for _, out_dir in ROUNDS:
        for m in MODELS:
            path = os.path.join(out_dir, m + ".jsonl")
            if not os.path.exists(path):
                continue
            seen = {}
            for unit, lab in labels(path).items():
                u = norm_unit(unit)
                if u in seen and any(seen[u][k] != lab[k] for k in COMPARED):
                    conflict.add(u)
                seen[u] = lab
            out[m].update(seen)
    return out, conflict


def site_rows() -> dict[str, dict]:
    """Сайт → подписи, заголовки, платформа и внимание по снимкам."""
    sites: dict[str, dict] = {}
    for n, path in enumerate(SNAPSHOTS, 1):
        for r in read(path):
            s = sites.setdefault(r["unit"], {"unit": r["unit"], "platform": r["platform"], "names": r["names"],
                                             "titles": r["titles"], "sample_urls": r["sample_urls"],
                                             "snapshots": [], **{f"att_{k}": 0.0 for k in WEIGHTS},
                                             "hc1": ""})
            s["snapshots"].append(str(n))
            s["sample_urls"] = s["sample_urls"] or r["sample_urls"]
            for k in WEIGHTS:
                s[f"att_{k}"] += float(r[f"att_{k}"]) / len(SNAPSHOTS)
            if n == 1:
                s["hc1"] = r["human_check"]
    return sites


def pick_human(sites: dict[str, dict]) -> dict[str, list[str]]:
    why = defaultdict(list)
    for u, s in sites.items():
        if s["hc1"]:
            why[u].append(f"снимок 1, {s['hc1'].replace('%', ' %')}")
    top80 = set()
    for k in WEIGHTS:
        acc = 0.0
        for s in sorted(sites.values(), key=lambda s: -s[f"att_{k}"]):
            if acc >= 80.0 or s[f"att_{k}"] == 0:
                break
            top80.add(s["unit"]); acc += s[f"att_{k}"]
    for u in sorted(top80):
        if u not in why:
            why[u].append("80 % внимания (снимки 1–3)")
    rest_new = sorted(u for u, s in sites.items() if "1" not in s["snapshots"] and u not in why)
    for u in random.Random(SEED).sample(rest_new, round(len(rest_new) * 0.10)):
        why[u].append("10 % жребий (новые в снимках 2–3)")
    return why


def main() -> None:
    out_dir = sys.argv[1]
    labs, conflict = model_labels()
    sites = site_rows()
    why = pick_human(sites)
    rows = []
    for u, s in sorted(sites.items(), key=lambda kv: -kv[1]["att_a"]):
        ev = evidence_text({"unit": u, "names": s["names"], "titles": s["titles"]}, os.path.join(D, "evidence"))
        a, b = (settle(labs[m].get(u), ev) for m in MODELS)
        rec = {"unit": u, "platform": s["platform"], "snapshots": ",".join(s["snapshots"]),
               **{f"att_{k}": round(s[f"att_{k}"], 4) for k in WEIGHTS}, "sample_url": s["sample_urls"].split(" ")[0]}
        for tag, lab in (("a", a), ("b", b)):
            for k in FIELDS:
                rec[f"{tag}_{k}"] = lab[k] if lab else ""
            rec[f"{tag}_quote_found"] = "" if not lab else quote_ok(lab["quote"], ev)
        reasons = list(why.get(u, []))
        if a is None or b is None:
            reasons.append("нет ответа модели")
        elif a["cat"] != b["cat"]:
            reasons.append("модели разошлись")
        if (a and a["doubt"]) or (b and b["doubt"]):
            reasons.append("«спорно»")
        if rec["a_quote_found"] == 0 or rec["b_quote_found"] == 0:
            reasons.append("цитата не найдена")
        if u in conflict:
            reasons.append("два имени сайта — разные ответы")
        rec["agreed_cat"] = a["cat"] if a and b and a["cat"] == b["cat"] else ""
        rec["why"] = "; ".join(reasons)
        rows.append(rec)
    os.makedirs(out_dir, exist_ok=True)
    for name, part in (("labels_all.csv", rows), ("human_check_all.csv", [r for r in rows if r["why"]])):
        with open(os.path.join(out_dir, name), "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(part)
    hc = [r for r in rows if r["why"]]
    print(f"сайтов {len(rows)}; обе модели ответили {sum(bool(r['a_cat'] and r['b_cat']) for r in rows)}; "
          f"согласны по категории {sum(bool(r['agreed_cat']) for r in rows)}; человеку {len(hc)} "
          f"(внимание а {sum(r['att_a'] for r in hc):.1f} %); конфликтов имён {len(conflict)}")
    cnt = defaultdict(int)
    for r in hc:
        for x in r["why"].split("; "):
            cnt[x.split(",")[0] if x.startswith("снимок 1") else x] += 1
    print("  причины:", dict(sorted(cnt.items(), key=lambda kv: -kv[1])))


if __name__ == "__main__":
    main()
