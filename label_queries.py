"""Разметка запросов по смыслу моделями вслепую (цель исследования модели не сообщается).

Запуск на сервере в контейнере worker (ключ ALIBABA_API_KEY только там):
  docker exec seointel-worker-tengrihealth-1 python /spool/med/label_queries.py SRC OUT_DIR MODEL [MODEL...]
Ответ модели — короткие строки «номер|medical|group|drug|lang|reason»; каждый ответ пишется сразу
в OUT_DIR/<model>.jsonl вместе с usage (токены); повторный запуск пропускает готовые пачки.
"""
import csv, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

BATCH = 80
WORKERS = 4
# рассуждения модели перед ответом: ~90 % токенов, но без них на пилоте каппа «medical» 0,46–0,82 вместо 1,00
THINKING = os.environ.get("LABEL_THINKING", "1") == "1"
BASE = os.environ.get("ALIBABA_API_BASE", "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1")
KEY = os.environ["ALIBABA_API_KEY"]

PROMPT = """Размечай поисковые запросы жителей Казахстана (русский, казахский).
Для каждого запроса одна строка: номер|medical|group|drug|lang|reason

medical: y — вопрос о здоровье: симптом, болезнь, состояние, анализ и норма, лечение, препарат
(название, инструкция, аналог, дозировка, побочные эффекты, совместимость, при беременности),
прививка, контрацепция, обследование.
n — иное: конкретная клиника/аптека по названию или адресу, покупка (купить, цена, доставка, рядом),
новости, ветеринария, косметика без медвопроса, больничный лист, пособия, ОСМС, право на бесплатные
лекарства, погода, физика, техника.
u — нельзя понять по запросу (например «давление» или «температура» без уточнения).
group: s — симптом/болезнь/состояние; t — анализ/норма/обследование; r — лечение; d — препарат;
v — прививка/контрацепция; o — другое.
drug: t — есть торговое название препарата (нурофен, кагоцел, магне в6); i — только название вещества
(ибупрофен, парацетамол); - — нет препарата.
lang: ru | kk | mx
reason: только при n или u — 2–4 слова; иначе пусто.
Пример: 7|y|d|t|ru|
Только строки, без пояснений.

Запросы:
"""


def call(model: str, items: list[str]) -> tuple[list[list[str]], dict]:
    numbered = "\n".join(f"{n}|{q}" for n, q in enumerate(items, 1))
    body = json.dumps({"model": model, "temperature": 0, "enable_thinking": THINKING,
                       "messages": [{"role": "user", "content": PROMPT + numbered}]}).encode()
    req = urllib.request.Request(BASE + "/chat/completions", body,
                                 {"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    err = ""
    for attempt in range(4):
        try:
            r = json.load(urllib.request.urlopen(req, timeout=300))
            lines = [ln.strip().split("|") for ln in r["choices"][0]["message"]["content"].splitlines() if "|" in ln]
            return lines, r.get("usage", {})
        except Exception as e:  # сеть, лимит — повтор с паузой
            err = str(e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"{model}: {err}")


def run(model: str, batches: list[list[str]], out_dir: str) -> None:
    path = os.path.join(out_dir, model + ".jsonl")
    done = set()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            done = {json.loads(line)["batch"] for line in f}
    todo = [(i, b) for i, b in enumerate(batches) if i not in done]

    def one(arg):
        i, b = arg
        try:
            lines, usage = call(model, b)
            return {"batch": i, "queries": b, "lines": lines, "usage": usage, "ok": len(lines) == len(b)}
        except RuntimeError as e:
            return {"batch": i, "queries": b, "lines": [], "usage": {}, "ok": False, "error": str(e)}

    with open(path, "a", encoding="utf-8") as f, ThreadPoolExecutor(WORKERS) as ex:
        for rec in ex.map(one, todo):
            f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
    print(model, "пачек:", len(batches), "новых:", len(todo))


def main() -> None:
    src, out_dir, models = sys.argv[1], sys.argv[2], sys.argv[3:]
    os.makedirs(out_dir, exist_ok=True)
    with open(src, encoding="utf-8") as f:
        queries = [row["keyword"] for row in csv.DictReader(f)]
    batches = [queries[i:i + BATCH] for i in range(0, len(queries), BATCH)]
    with ThreadPoolExecutor(len(models)) as ex:
        list(ex.map(lambda m: run(m, batches, out_dir), models))


if __name__ == "__main__":
    main()
