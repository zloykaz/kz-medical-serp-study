"""Сверка разметки сайтов двумя моделями (п. 5 методики, отступление 2).

  python compare_domains.py DOMAINS.csv EVIDENCE_DIR OUT_DIR MODEL_A.jsonl MODEL_B.jsonl

Берёт последнюю полную пачку каждой модели, ставит сайт по номеру строки в пачке; считает согласие
и каппу Коэна по категории и признакам, проверяет цитату-доказательство на дословное совпадение со
свидетельствами (страницы сайта, подпись и заголовки в выдаче; без учёта регистра и лишних пробелов).
DOMAINS.csv — тот самый список, по которому шла разметка (номер строки в пачке → сайт берётся из
пачки, а внимание и подписи — из DOMAINS.csv; другой список даст «нет ответа» и чужие свидетельства).
Пишет OUT_DIR/labels_compare.csv (сайт, ответы обеих моделей, совпадение, проверка цитат, кому решать)
и печатает сводку. Внимание сайта (att_a/b/c) — из DOMAINS.csv, чтобы видеть вес расхождений.
"""
import csv, json, os, re, sys
from collections import Counter

FIELDS = ["cat", "maker", "owner", "country", "platform", "ev_url", "quote", "doubt"]
COMPARED = ["cat", "maker", "owner", "country"]
CAT_NAMES = {"ФАРМА": "1", "АПТЕКА": "2", "СПРАВОЧНИК": "3", "КЛИНИКА": "4", "МЕДИА": "5", "ГОСОРГАН": "6",
             "МЕЖДУНАРОД": "6", "АГРЕГАТОР": "7", "ЭНЦИКЛОПЕДИЯ": "8", "ПРОЧЕЕ": "9"}
MIN_QUOTE_WORDS = 3  # кодовая книга: цитата 3–15 слов


def cat_code(s: str) -> str:
    """Номер категории: модель иногда пишет название («ФАРМА», «3. СПРАВОЧНИК…») вместо номера."""
    m = re.match(r"\s*(\d)", s)
    if m:
        return m.group(1)
    up = s.upper()
    return next((code for name, code in CAT_NAMES.items() if name in up), s)


def labels(path: str) -> dict[str, dict]:
    """unit → ответ модели (последняя полная пачка)."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            if not rec["ok"]:
                continue
            by_name = {u.lower(): u for u in rec["units"]}
            for parts in rec["lines"]:
                key = parts[0].strip().lstrip("#")
                if key.isdigit() and 1 <= int(key) <= len(rec["units"]):
                    unit = rec["units"][int(key) - 1]
                elif key.lower() in by_name:  # модель иногда пишет имя сайта вместо номера строки
                    unit = by_name[key.lower()]
                else:
                    continue
                vals, ambiguous = split_fields(parts[1:])
                lab = dict(zip(FIELDS, vals))
                out[unit] = {**lab, "cat": cat_code(lab["cat"]), "ambiguous": ambiguous}
    return out


def settle(lab: dict | None, ev: str) -> dict | None:
    """Строка с лишним «|»: если «сомнение» дословно есть в свидетельствах, это продолжение цитаты
    (заголовок сайта вида «Клиника | Официальный сайт»), а не сомнение модели."""
    if not lab or not lab["ambiguous"] or not lab["doubt"] or norm(lab["doubt"]) not in ev:
        return lab
    return {**lab, "quote": f"{lab['quote']} | {lab['doubt']}", "doubt": ""}


def split_fields(parts: list[str]) -> tuple[list[str], bool]:
    """8 полей ответа и признак «лишний | — граница цитаты и сомнения неоднозначна» (её решает settle).

    Лишний «|» в конце отбрасывается; «|» внутри цитаты склеивается обратно в цитату.
    """
    vals = [p.strip() for p in parts]
    ambiguous = len(vals) > 8
    while len(vals) > 8 and vals[-1] == "":
        vals.pop()
    if len(vals) > 8:
        vals = vals[:6] + ["|".join(vals[6:-1])] + vals[-1:]
    return vals + [""] * (8 - len(vals)), ambiguous


def quote_ok(quote: str, ev: str) -> int:
    """1 — цитата от 3 слов и дословно есть в свидетельствах; пустая или короче — 0 (решает человек)."""
    pieces = [norm(x) for x in quote.split("|") if norm(x)]  # «|» внутри — куски заголовка, каждый ищется отдельно
    return int(len(quote.split()) >= MIN_QUOTE_WORDS and bool(pieces) and all(x in ev for x in pieces))


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip().lower().strip(".«»\"'… ")


def evidence_text(row: dict, ev_dir: str) -> str:
    parts = [row["unit"], row["names"], row["titles"]]
    path = os.path.join(ev_dir, re.sub(r"[^\w.-]", "_", row["unit"]) + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for p in json.load(f)["pages"]:
                parts += [p["url"], p["title"], p["description"], p["head"][:900], p["footer"][-1100:]]
    return norm(" ".join(parts))


def kappa(pairs: list[tuple[str, str]]) -> float:
    n = len(pairs)
    po = sum(a == b for a, b in pairs) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    pe = sum(ca[k] * cb[k] for k in ca) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main() -> None:
    src, ev_dir, out_dir, path_a, path_b = sys.argv[1:6]
    name_a, name_b = (os.path.basename(p).removesuffix(".jsonl") for p in (path_a, path_b))
    with open(src, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    la, lb = labels(path_a), labels(path_b)
    out = []
    for r in rows:
        ev = evidence_text(r, ev_dir)
        a, b = settle(la.get(r["unit"]), ev), settle(lb.get(r["unit"]), ev)
        rec = {"unit": r["unit"], "platform": r["platform"], "att_a": r["att_a"], "att_b": r["att_b"],
               "att_c": r["att_c"], "human_check": r["human_check"]}
        for tag, lab in (("a", a), ("b", b)):
            for k in FIELDS:
                rec[f"{tag}_{k}"] = lab[k] if lab else ""
            rec[f"{tag}_quote_found"] = "" if not lab else quote_ok(lab["quote"], ev)
        both = a is not None and b is not None
        rec["missing"] = ", ".join(n for n, lab in ((name_a, a), (name_b, b)) if lab is None)
        for k in COMPARED:
            rec[f"same_{k}"] = int(a[k] == b[k]) if both else ""
        rec["to_human"] = int(not both or a["cat"] != b["cat"] or bool(a["doubt"]) or bool(b["doubt"])
                              or rec["a_quote_found"] == 0 or rec["b_quote_found"] == 0)
        out.append(rec)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "labels_compare.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(out[0])); w.writeheader(); w.writerows(out)

    both = [r for r in out if not r["missing"]]
    print(f"сайтов {len(out)}; ответы обеих моделей {len(both)}; нет ответа: "
          f"{name_a} {sum(r['unit'] not in la for r in rows)}, {name_b} {sum(r['unit'] not in lb for r in rows)}")
    for k in COMPARED:
        pairs = [(r[f"a_{k}"], r[f"b_{k}"]) for r in both]
        print(f"  {k}: согласие {100 * sum(x == y for x, y in pairs) / len(pairs):.1f} %, каппа {kappa(pairs):.2f}")
        if k == "country":  # «~RU» (по домену и языку) и «RU» (по юрлицу) — одна страна, разная уверенность
            p2 = [(x.lstrip("~"), y.lstrip("~")) for x, y in pairs]
            print(f"  country без пометки «~»: согласие {100 * sum(x == y for x, y in p2) / len(p2):.1f} %, "
                  f"каппа {kappa(p2):.2f}")
    for k in ("a", "b"):
        q = [r[f"{k}_quote_found"] for r in out if r[f"{k}_quote_found"] != ""]
        print(f"  цитата найдена дословно ({name_a if k == 'a' else name_b}): {sum(q)} из {len(q)}")
    for w_ in ("a", "b", "c"):
        tot = sum(float(r[f"att_{w_}"]) for r in out)
        dis = sum(float(r[f"att_{w_}"]) for r in both if r["same_cat"] == 0)
        miss = sum(float(r[f"att_{w_}"]) for r in out if r["missing"])
        print(f"  внимание (веса {w_}): у сайтов с разной категорией {100 * dis / tot:.1f} %, "
              f"без ответа модели {100 * miss / tot:.2f} %")
    print("  пары категорий при расхождении:",
          Counter((r["a_cat"], r["b_cat"]) for r in both if r["same_cat"] == 0).most_common(10))
    print(f"  человеку решать (расхождение, «спорно», цитата не найдена или короче 3 слов, нет ответа): "
          f"{sum(r['to_human'] for r in out)}")


if __name__ == "__main__":
    main()
