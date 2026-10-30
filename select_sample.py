"""Очистка совокупности и выборки (README п. 2–3).

  python select_sample.py MAIN_JSONL CHECK_JSONL [decisions.csv]
MAIN_JSONL — разметка основной модели по всем запросам, CHECK_JSONL — второй модели по check20.csv.
decisions.csv (keyword,medical,drug) — решения человека по расхождениям; без него расхождения
пишутся в conflicts.csv и выборки не строятся.

Склейка: одинаковый набор лемм (pymorphy3 для русских слов; казахские слова — как есть, в нижнем
регистре). Частота склейки — максимум вариантов: Ads даёт близким вариантам частоту одной группы,
сумма удвоила бы спрос. Представитель — самый частый вариант.
"""
import csv, random, re, sys
from collections import Counter

import pymorphy3

from compare_pilot import load

SEED = 20261030
MAIN_N, CHECK_N = 300, 100
KK = set("әғқңөұүһі")
morph = pymorphy3.MorphAnalyzer()


def lemma(w: str) -> str:
    if KK & set(w) or not re.search("[а-я]", w):
        return w
    parses = morph.parse(w)
    best = parses[0]
    # названия препаратов pymorphy угадывает: «ибупрофен» → «ибупрофный», «кагоцела» → «кагоцелый»
    if best.tag.POS == "ADJS" or best.methods_stack[0][0].__class__.__name__ == "FakeDictionary":
        best = next((p for p in parses if p.tag.POS == "NOUN"), best)
    return best.normal_form.replace("ё", "е")


def lemma_key(q: str) -> frozenset:
    return frozenset(lemma(w) for w in re.findall(r"\w+", q.lower().replace("ё", "е")))


def main() -> None:
    main_lab, _ = load(sys.argv[1])
    check_lab, _ = load(sys.argv[2])
    decisions = {}
    if len(sys.argv) > 3:
        decisions = {r["keyword"]: r for r in csv.DictReader(open(sys.argv[3], encoding="utf-8"))}
    rows = list(csv.DictReader(open("queries_ge50.csv", encoding="utf-8")))

    conflicts, unlabeled = [], []
    for r in rows:
        q = r["keyword"]
        lab = main_lab.get(q)
        if lab is None:
            unlabeled.append(q); continue
        r.update(lab)
        other = check_lab.get(q)
        if q in decisions:  # расхождение моделей или ручная проверка выборки (поправка 2)
            r["medical"], r["drug"] = decisions[q]["medical"], decisions[q]["drug"]
            r["resolved"] = "human"
        elif other and (other["medical"], other["drug"]) != (lab["medical"], lab["drug"]):
            conflicts.append({"keyword": q, "main": f'{lab["medical"]}/{lab["drug"]}',
                              "check": f'{other["medical"]}/{other["drug"]}'})
    print(f"запросов {len(rows)}, без разметки {len(unlabeled)}, расхождений без решения {len(conflicts)}")
    if unlabeled:
        print("  без разметки, примеры:", unlabeled[:10])
    if conflicts:
        with open("conflicts.csv", "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["keyword", "main", "check"]); w.writeheader(); w.writerows(conflicts)
        print("  → conflicts.csv; выборки не строю"); return

    groups: dict[frozenset, list[dict]] = {}
    for r in rows:
        if "medical" in r:
            groups.setdefault(lemma_key(r["keyword"]), []).append(r)
    merged = []
    for variants in groups.values():
        variants.sort(key=lambda v: -int(v["volume"]))
        rep = dict(variants[0])
        rep["src"] = "".join(sorted(set("".join(v["src"] for v in variants))))
        rep["variants"] = " | ".join(v["keyword"] for v in variants[1:])
        merged.append(rep)
    print(f"после склейки {len(merged)} (склеено {len(rows) - len(unlabeled) - len(merged)})")
    print("medical:", dict(Counter(r["medical"] for r in merged)))

    keep = [r for r in merged if r["medical"] in ("y", "u")]
    excluded = [r for r in merged if r["medical"] not in ("y", "u")]
    rnd = random.Random(SEED)
    tiebreak = {r["keyword"]: rnd.random() for r in keep}  # Ads округляет частоты — равные места по жребию
    keep.sort(key=lambda r: (-int(r["volume"]), tiebreak[r["keyword"]]))
    main_s = keep[:MAIN_N]
    # запасные — на случай, если многозначный (u) выбудет по снимку 1 (поправка 2)
    reserve = [r for r in keep[MAIN_N:] if r["medical"] == "y"][:sum(r["medical"] == "u" for r in main_s)]
    taken = {r["keyword"] for r in main_s + reserve}
    # казахских в топе по частоте почти нет — отдельный слой целиком (поправка 2)
    kk_s = [r for r in keep if r["lang"] in ("kk", "mx") and r["keyword"] not in taken]
    taken |= {r["keyword"] for r in kk_s}
    check_s = random.Random(SEED).sample([r for r in keep if r["keyword"] not in taken], CHECK_N)
    print(f"запасных {len(reserve)}, казахский слой {len(kk_s)}")
    print(f"в совокупности {len(keep)}; основная: частота от {main_s[-1]['volume']}, "
          f"на границе с той же частотой ещё {sum(r['volume'] == main_s[-1]['volume'] for r in keep[MAIN_N:])}")
    for name, s in (("основная", main_s), ("проверочная", check_s)):
        print(f"  {name}: drug {dict(Counter(r['drug'] for r in s))}, lang {dict(Counter(r['lang'] for r in s))}, "
              f"medical {dict(Counter(r['medical'] for r in s))}")

    fields = ["keyword", "volume", "src", "medical", "group", "drug", "lang", "reason", "resolved", "variants"]
    for path, data in (("population_clean.csv", keep), ("excluded_meaning.csv", excluded),
                       ("sample_main.csv", main_s), ("sample_reserve.csv", reserve), ("sample_kk.csv", kk_s),
                       ("sample_check.csv", check_s)):
        with open(path, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(data)


if __name__ == "__main__":
    main()
