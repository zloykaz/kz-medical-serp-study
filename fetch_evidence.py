"""Свидетельства для разметки сайтов (codebook.md: категория — по странице, а не по памяти модели).

  python -I fetch_evidence.py domains/domains_snapshot1.csv domains/evidence

По каждому сайту (кроме авторов на платформах — их страницы без входа не открываются): главная и одна
страница «О нас / Контакты», если на главной есть ссылка на неё. Сохраняется: заголовок, описание,
начало текста, подвал (конец текста, где обычно юрлицо), адреса. Повторный запуск пропускает готовые.
"""
import csv, json, os, re, ssl, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

UA = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"
ABOUT = re.compile(r"(about|o-nas|o_nas|onas|o-kompanii|kompaniya|company|contact|kontakt|rekvizit|"
                   r"о нас|о компании|контакт|реквизит|біз туралы|байланыс)", re.I)
CTX = ssl.create_default_context()
MAX_BYTES = 1_500_000


class Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.skip = 0
        self.parts: list[str] = []
        self.links: list[tuple[str, str]] = []
        self.title = ""
        self.desc = ""
        self._a: str | None = None
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = dict(attrs)
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "meta" and (a.get("name") or "").lower() == "description":
            self.desc = (a.get("content") or "")[:400]
        elif tag == "a" and a.get("href"):
            self._a = a["href"]

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a":
            self._a = None

    def handle_data(self, data: str) -> None:
        if self.skip:
            return
        s = " ".join(data.split())
        if not s:
            return
        if self._in_title:
            self.title += s
            return
        self.parts.append(s)
        if self._a:
            self.links.append((self._a, s))


def get(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ru,kk;q=0.8"})
    with urllib.request.urlopen(req, timeout=20, context=CTX) as r:
        raw = r.read(MAX_BYTES)
        cs = r.headers.get_content_charset() or "utf-8"
        return r.geturl(), raw.decode(cs, errors="replace")


def page(url: str) -> dict:
    final, html = get(url)
    p = Text()
    p.feed(html)
    text = " ".join(p.parts)
    return {"url": final, "title": p.title[:200], "description": p.desc, "head": text[:1200],
            "footer": text[-1500:] if len(text) > 1200 else "", "links": p.links}


def one(unit: str, out: str) -> str:
    path = os.path.join(out, re.sub(r"[^\w.-]", "_", unit) + ".json")
    if os.path.exists(path):
        return "есть"
    rec = {"unit": unit, "pages": [], "error": ""}
    try:
        host, _, rest = unit.partition("/")
        home = page(f"https://{host.encode('idna').decode()}/{rest}")
        about = next((urljoin(home["url"], h) for h, t in home.pop("links")
                      if ABOUT.search(h + " " + t) and urlparse(urljoin(home["url"], h)).hostname
                      and unit.split("/")[0] in urlparse(urljoin(home["url"], h)).hostname), None)
        rec["pages"].append(home)
        if about:
            try:
                a = page(about)
                a.pop("links")
                rec["pages"].append(a)
            except Exception as e:  # главная есть — «О нас» не обязательна
                rec["error"] = f"about: {e}"[:200]
    except Exception as e:
        rec["error"] = str(e)[:200]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False)
    return "ошибка" if not rec["pages"] else "ок"


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    with open(src, encoding="utf-8") as f:
        units = [r["unit"] for r in csv.DictReader(f) if not r["platform"] and not r["unit"].startswith("?")]
    # gov.kz/org/<орг> — открываем как адрес организации
    with ThreadPoolExecutor(16) as ex:
        res = list(ex.map(lambda u: one(u, out), units))
    print({k: res.count(k) for k in set(res)}, "из", len(units))


if __name__ == "__main__":
    main()
