"""Сравнение разметки моделей на пилоте: согласие по полям, каппа Коэна, токены."""
import json, sys
from collections import Counter
from itertools import combinations

FIELDS = ["medical", "group", "drug", "lang"]


def load(path: str) -> tuple[dict, dict]:
    labels, usage = {}, Counter()
    for line in open(path, encoding="utf-8"):
        rec = json.loads(line)
        for k, v in rec["usage"].items():
            if isinstance(v, int):
                usage[k] += v
        for parts in rec["lines"]:
            try:
                n = int(parts[0]) - 1
            except ValueError:
                continue
            if 0 <= n < len(rec["queries"]):
                labels[rec["queries"][n]] = dict(zip(FIELDS, (p.strip() for p in parts[1:5])))
    return labels, usage


def kappa(a: list[str], b: list[str]) -> float:
    n = len(a)
    po = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / n / n
    return (po - pe) / (1 - pe) if pe < 1 else 1.0


def main() -> None:
    models = {"/".join(p.split("/")[-2:]).removesuffix(".jsonl"): load(p) for p in sys.argv[1:]}
    for m, (lab, use) in models.items():
        print(f"{m}: размечено {len(lab)}, токены {dict(use)}, medical={dict(Counter(x['medical'] for x in lab.values()))}")
    for (m1, (l1, _)), (m2, (l2, _)) in combinations(models.items(), 2):
        common = [q for q in l1 if q in l2]
        print(f"\n{m1} vs {m2}: общих {len(common)}")
        for f in FIELDS:
            a, b = [l1[q][f] for q in common], [l2[q][f] for q in common]
            agree = sum(x == y for x, y in zip(a, b)) / len(common)
            print(f"  {f}: совпадение {agree:.1%}, каппа {kappa(a, b):.2f}")
        diff = [q for q in common if l1[q]["medical"] != l2[q]["medical"]]
        for q in diff[:15]:
            print(f"   ≠ {q}: {l1[q]['medical']}/{l2[q]['medical']}")


if __name__ == "__main__":
    main()
