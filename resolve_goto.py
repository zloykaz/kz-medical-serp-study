"""Раскрыть ссылки-переадресации google.com/goto в снимке выдачи (отступление 3).

  python resolve_goto.py SNAPSHOT.jsonl.gz OUT.csv

В части ответов DataForSEO адрес ссылки ответа ИИ (и обычного результата) приходит как
google.com/goto?url=<шифр>, а domain = google.com. Адрес раскрывается переходом по переадресации
Google без захода на сам сайт: запрос без автоперехода, шаги по Location;
первый адрес, который не переходник Google (/goto, /url), и есть адрес ссылки (бывает и ресурсом Google,
например patents.google.com). Повторный запуск запрашивает только нераскрытые, файл OUT переписывается
целиком (по файлу на снимок). Ошибка одной ссылки (сеть, 429) — повтор с паузой, прогон не прерывается.
"""
import csv, gzip, json, os, sys, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse

WORKERS = 4
UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Mobile Safari/537.36"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def is_goto(url: str) -> bool:
    return "google." in (urlparse(url).hostname or "") and urlparse(url).path == "/goto"


def is_google_hop(url: str) -> bool:
    """Промежуточный переходник Google (/goto, /url), а не сам адрес ссылки."""
    return "google." in (urlparse(url).hostname or "") and urlparse(url).path in ("/goto", "/url")


def resolve(url: str) -> tuple[str, str]:
    """(статус, адрес): ok — первый адрес вне переадресации Google; иначе код ошибки и последний адрес.

    Цель может быть и ресурсом Google (patents.google.com) — признак конца цепочки не хост, а то,
    что адрес больше не google.*/goto.
    """
    status, last = "net_error", url
    for attempt in range(3):
        u = url
        try:
            for _ in range(6):
                try:
                    OPENER.open(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=20)
                    return "no_redirect", u
                except urllib.error.HTTPError as e:
                    loc = e.headers.get("Location")
                    if not loc:
                        status, last = f"http_{e.code}", u
                        break
                    u = urljoin(u, loc)
                    if not is_google_hop(u):
                        return "ok", u
            else:
                return "loop", u
            if status != "http_429":
                return status, last
        except Exception as e:  # сеть, обрыв ответа — повтор, ошибка одной ссылки не валит прогон
            status, last = "net_error", f"{type(e).__name__}: {e}"
        time.sleep(10 * (attempt + 1))
    return status, last


def goto_urls(src: str) -> list[str]:
    seen = []
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            for it in json.loads(line)["response"][0].get("items") or []:
                cands = [it.get("url") or ""]
                cands += [r.get("url") or "" for r in it.get("references") or []]
                seen += [u for u in cands if is_goto(u)]
    return list(dict.fromkeys(seen))


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    done = {}
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            done = {r["goto"]: r for r in csv.DictReader(f) if r["status"] == "ok"}
    urls = goto_urls(src)
    todo = [u for u in urls if u not in done]
    with ThreadPoolExecutor(WORKERS) as ex:
        res = dict(zip(todo, ex.map(resolve, todo)))
    rows = [done.get(u) or {"goto": u, "status": res[u][0], "url": res[u][1]} for u in urls]
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["goto", "status", "url"]); w.writeheader(); w.writerows(rows)
    bad = [r for r in rows if r["status"] != "ok"]
    print(f"ссылок goto {len(urls)}, раскрыто {len(rows) - len(bad)}, не раскрыто {len(bad)}")


if __name__ == "__main__":
    main()
