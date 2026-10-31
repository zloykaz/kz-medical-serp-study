"""Разметка сайтов выдачи по codebook.md двумя моделями вслепую (п. 5 методики).

Запуск на сервере в контейнере worker (ключ ALIBABA_API_KEY только там), ночью (19:00–05:00 Алматы):
  docker exec seointel-worker-tengrihealth-1 python /spool/med/domains/label_domains.py \
      DOMAINS.csv EVIDENCE_DIR CODEBOOK.md OUT_DIR MODEL [MODEL...]
Модели получают кодовую книгу и только свидетельства: страницы сайта (главная, «О нас»), как сайт
подписан в выдаче, заголовки. Ответ — строка на сайт; каждый ответ пишется сразу в OUT_DIR/<model>.jsonl
вместе с usage; повторный запуск пропускает готовые пачки (как label_queries.py).
"""
import csv, json, os, re, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

BATCH = 8
WORKERS = 4
THINKING = os.environ.get("LABEL_THINKING", "1") == "1"
BASE = os.environ.get("ALIBABA_API_BASE", "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1")
KEY = os.environ["ALIBABA_API_KEY"]

PROMPT = """Ты размечаешь сайты по кодовой книге ниже. Категорию ставь ТОЛЬКО по свидетельствам, которые даны
(текст страниц сайта, подпись в выдаче, заголовки), а не по тому, что помнишь о сайте. Если свидетельств мало —
ставь лучшую категорию и пометку «спорно» с причиной.

{codebook}

Для каждого сайта одна строка:
номер|категория|производитель|собственность|страна|платформа|адрес_доказательства|цитата|спорно
категория: 1–9 по кодовой книге.
производитель (связь с производителем лекарств): own — собственность, spons — спонсорство, no — нет, unk — не определено.
собственность: gov | priv | unk.
страна: код страны юрлица (KZ, RU, UA, BY, US…) или unk; по домену и языку без юрлица — код со знаком ~ (~RU).
платформа: имя платформы (YouTube, Instagram, Kaspi…) или -.
адрес_доказательства: адрес страницы из свидетельств, на которой основана категория.
цитата: дословный кусок 3–15 слов из свидетельств (юрлицо, «О нас», чем занимается); без символа |.
спорно: пусто, или причина в одну строку.
Только строки, без пояснений.

Сайты:
"""


def evidence(row: dict, ev_dir: str) -> str:
    lines = [f"Сайт: {row['unit']}"]
    if row["platform"]:
        lines.append(f"Платформа: {row['platform']} (страница автора не открывалась — судить по подписи и заголовкам)")
    if row["names"]:
        lines.append(f"Подпись в выдаче Google: {row['names']}")
    if row["titles"]:
        lines.append(f"Заголовки результатов: {row['titles']}")
    path = os.path.join(ev_dir, re.sub(r"[^\w.-]", "_", row["unit"]) + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            rec = json.load(f)
        for p in rec["pages"]:
            lines.append(f"Страница {p['url']}\n  заголовок: {p['title']}\n  описание: {p['description']}\n"
                         f"  начало: {p['head'][:900]}\n  подвал: {p['footer'][-1100:]}")
        if not rec["pages"]:
            lines.append(f"Страницы сайта не открылись ({rec['error'][:80]})")
    elif not row["platform"]:
        lines.append("Страницы сайта не скачивались")
    return "\n".join(lines)


def call(model: str, prompt: str) -> tuple[str, dict]:
    body = json.dumps({"model": model, "temperature": 0, "enable_thinking": THINKING,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", body,
                                 {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    err = ""
    for attempt in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=600))
            return r["choices"][0]["message"]["content"], r.get("usage", {})
        except Exception as e:  # сеть, лимит — повтор с паузой
            err = str(e)
            time.sleep(15 * (attempt + 1))
    raise RuntimeError(f"{model}: {err}")


def run(model: str, batches: list[list[dict]], ev_dir: str, codebook: str, out_dir: str) -> None:
    path = os.path.join(out_dir, model + ".jsonl")
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            done = {json.loads(line)["batch"] for line in f if json.loads(line)["ok"]}
    todo = [(i, b) for i, b in enumerate(batches) if i not in done]

    def one(arg):
        i, b = arg
        blocks = "\n\n".join(f"### {n}\n{evidence(r, ev_dir)}" for n, r in enumerate(b, 1))
        try:
            text, usage = call(model, PROMPT.format(codebook=codebook) + blocks)
            lines = [ln.strip().split("|") for ln in text.splitlines() if ln.count("|") >= 8]
            return {"batch": i, "units": [r["unit"] for r in b], "lines": lines, "usage": usage,
                    "ok": len(lines) == len(b)}
        except RuntimeError as e:
            return {"batch": i, "units": [r["unit"] for r in b], "lines": [], "usage": {}, "ok": False,
                    "error": str(e)}

    with open(path, "a", encoding="utf-8") as f, ThreadPoolExecutor(WORKERS) as ex:
        for rec in ex.map(one, todo):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
    print(model, "пачек:", len(batches), "новых:", len(todo), flush=True)


def main() -> None:
    src, ev_dir, cb, out_dir, models = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]
    os.makedirs(out_dir, exist_ok=True)
    with open(cb, encoding="utf-8") as f:
        codebook = f.read()
    with open(src, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    batches = [rows[i:i + BATCH] for i in range(0, len(rows), BATCH)]
    with ThreadPoolExecutor(len(models)) as ex:
        list(ex.map(lambda m: run(m, batches, ev_dir, codebook, out_dir), models))


if __name__ == "__main__":
    main()
