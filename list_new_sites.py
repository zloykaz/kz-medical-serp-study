"""Сайты, которых ещё нет в размеченном списке (отступление 3: новые из исправленного снимка 1 и из снимков 2–3).

  python list_new_sites.py LABELED.csv OUT.csv DOMAINS_snapshotN.csv [DOMAINS_snapshotM.csv ...]

LABELED.csv — список, по которому уже шла разметка; имена его сайтов приводятся к нынешнему виду
(punycode → кириллица, build_domains.norm_unit), поэтому переименованный сайт новым не считается.
Строка нового сайта берётся из первого списка, где он встретился (подписи и заголовки — для свидетельств);
колонка human_check не переносится: правило проверки человеком для новых сайтов — в README, отступление 3.
"""
import csv, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # запуск с python -I
from build_domains import norm_unit  # noqa: E402


def main() -> None:
    labeled_path, out_path, lists = sys.argv[1], sys.argv[2], sys.argv[3:]
    with open(labeled_path, encoding="utf-8") as f:
        labeled = {norm_unit(r["unit"]) for r in csv.DictReader(f)}
    new: dict[str, dict] = {}
    for path in lists:
        with open(path, encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r["unit"] not in labeled and r["unit"] not in new:
                    new[r["unit"]] = {**r, "human_check": "", "first_seen": path.rsplit("_", 1)[-1][:-4]}
    rows = sorted(new.values(), key=lambda r: r["unit"])
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(rows[0])); w.writeheader(); w.writerows(rows)
    print(f"новых сайтов {len(rows)}: " + ", ".join(
        f"{p.rsplit('_', 1)[-1][:-4]} {sum(r['first_seen'] == p.rsplit('_', 1)[-1][:-4] for r in rows)}"
        for p in lists))


if __name__ == "__main__":
    main()
