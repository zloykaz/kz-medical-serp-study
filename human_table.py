"""Таблица Excel для ручной проверки сайтов (из merge_labels.py).

  python human_table.py domains/merged/human_check_all.csv OUT.xlsx

По методике проверяются ВСЕ строки; очередь — только порядок работы. Очередь 1 — заметные сайты (снимок 1:
80 % и 10 %; 80 % внимания снимков 1–3; 10 % новых), расхождение моделей, нет ответа, два имени сайта с разными
ответами. Очередь 2 — модели согласны по типу, но одна пометила «спорно» или цитата не найдена. Внутри очереди —
по убыванию внимания (веса а, среднее по снимкам 1–3).
"""
import csv, sys
from urllib.parse import quote_plus

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

CATS = {"1": "ФАРМА", "2": "АПТЕКА", "3": "СПРАВОЧНИК ЛЕКАРСТВ", "4": "КЛИНИКА", "5": "МЕДИА", "6": "ГОСОРГАН / МЕЖДУНАР.",
        "7": "АГРЕГАТОР ВРАЧЕЙ", "8": "ЭНЦИКЛОПЕДИЯ / ВОПРОС-ОТВЕТ", "9": "ПРОЧЕЕ"}
MAKER = {"own": "собственность", "spons": "спонсорство", "no": "нет", "unk": "не определено"}
OWNER = {"gov": "государственный", "priv": "частный", "unk": "не определено"}
QUEUE1 = ("снимок 1", "80 %", "10 %", "разошлись", "нет ответа", "два имени")
MODEL_COLS = ["тип", "связь с фармой", "гос./частный", "страна", "цитата", "где цитата", "сомнение"]
HEAD = (["№", "Очередь", "Сайт", "Открыть", "Внимание, %", "В снимках", "Почему проверить"]
        + [f"deepseek: {c}" for c in MODEL_COLS] + [f"qwen: {c}" for c in MODEL_COLS]
        + ["ВАШ ОТВЕТ: тип (1–9)", "ВАШ ОТВЕТ: связь с фармой", "ВАШ ОТВЕТ: гос./частный", "ВАШ ОТВЕТ: страна",
           "Комментарий"])
WIDTH = [6, 9, 28, 30, 11, 10, 30] + [20, 14, 13, 8, 45, 30, 35] * 2 + [16, 16, 16, 12, 30]
ANS = len(HEAD) - 4  # первая колонка ответа (с 1)
CHOICES = ('"1,2,3,4,5,6,7,8,9"', '"собственность,спонсорство,нет,не определено"',
           '"государственный,частный,не определено"')
HOW = [
    "Задача: для каждого сайта заполнить жёлтые колонки «ВАШ ОТВЕТ». Типы сайтов — на листе «Типы сайтов».",
    "Если модели правы — повторите их ответ. Если ошиблись — ваш ответ главный.",
    "По методике проверяются ВСЕ строки. «Очередь» — только порядок: сначала 1 (заметные сайты и спорные случаи),",
    "  потом 2 (модели согласны по типу, но одна сомневается или её цитата не нашлась на сайте).",
    "«Внимание, %» — доля внимания читателей, которая приходится на сайт в выдаче (среднее по трём снимкам).",
    "«Почему проверить» — по какой причине сайт попал в таблицу.",
    "«Открыть» — страница сайта из выдачи; у авторов в YouTube, Instagram и т. п. — поиск по имени автора.",
    "«цитата» и «где цитата» — на чём модель основала ответ. Красный фон у типа — модели ответили по-разному.",
    "Страна — код страны юрлица (KZ, RU, UA…); со знаком ~ модель судила только по домену и языку.",
    "Связь с фармой: сайт принадлежит производителю лекарств / спонсорство («при поддержке») / нет / не определено.",
    "Гос./частный: государственная ли организация (больница на gov.kz — государственная клиника).",
    "Тип, связь с фармой и гос./частный — только из выпадающего списка; страна — код из двух букв.",
    "Комментарий — по желанию, если случай неочевидный.",
]
TYPES = [
    ("1 ФАРМА", "Производитель или владелец регистрации лекарства; бренд-сайт препарата; дистрибьютор, продвигающий свои марки"),
    ("2 АПТЕКА", "Продажа лекарств: аптеки, онлайн-аптеки, агрегаторы цен. Есть корзина или «наличие в аптеках» — сюда"),
    ("3 СПРАВОЧНИК ЛЕКАРСТВ", "Базы инструкций без продажи (vidal, rlsnet)"),
    ("4 КЛИНИКА", "Клиники, медцентры, лаборатории, стоматологии; блог клиники"),
    ("5 МЕДИА", "Издание с редакцией: новости, журналы, медразделы СМИ (если не принадлежат клинике или аптеке)"),
    ("6 ГОСОРГАН / МЕЖДУНАР.", "Минздрав, egov, нацреестр лекарств, ВОЗ, CDC, NHS. Больница на gov.kz — КЛИНИКА"),
    ("7 АГРЕГАТОР ВРАЧЕЙ", "Каталоги врачей и клиник, запись, онлайн-консультации"),
    ("8 ЭНЦИКЛОПЕДИЯ / ВОПРОС-ОТВЕТ", "Википедия, энциклопедии болезней без продажи услуг, сервисы вопросов"),
    ("9 ПРОЧЕЕ", "Форумы и всё остальное"),
    ("Правило", "Тип — по главному делу владельца сайта (на чём зарабатывает), а не по одной странице. "
                "Канал на YouTube/Instagram, продавец на Kaspi — по автору или продавцу."),
]


def cat(c: str) -> str:
    return f"{c} {CATS[c]}" if c in CATS else (c or "— нет ответа —")


def link_of(r: dict) -> str:
    """Страница из выдачи; у автора на платформе — поиск Google по платформе и имени автора."""
    if r["sample_url"]:
        return r["sample_url"]
    unit = r["unit"].lstrip("?")
    if "/" in unit or "·" in unit or r["platform"]:
        return "https://www.google.com/search?q=" + quote_plus(unit.replace("/", " ").replace("·", " "))
    return "https://" + unit


def model_cells(r: dict, t: str) -> list[str]:
    return [cat(r[f"{t}_cat"]), MAKER.get(r[f"{t}_maker"], r[f"{t}_maker"]),
            OWNER.get(r[f"{t}_owner"], r[f"{t}_owner"]), r[f"{t}_country"], r[f"{t}_quote"], r[f"{t}_ev_url"],
            r[f"{t}_doubt"]]


def review_sheet(ws, rows: list[dict]) -> None:
    ws.append(HEAD)
    for i, r in enumerate(rows, 1):
        link = link_of(r)
        ws.append([i, r["queue"], r["unit"], link, round(float(r["att_a"]), 3), r["snapshots"], r["why"],
                   *model_cells(r, "a"), *model_cells(r, "b"), "", "", "", "", ""])
        ws.cell(i + 1, 4).hyperlink = link
        ws.cell(i + 1, 4).font = Font(color="1F5FBF", underline="single")
        if r["a_cat"] != r["b_cat"]:
            for col in (8, 8 + len(MODEL_COLS)):
                ws.cell(i + 1, col).fill = PatternFill("solid", fgColor="FDE2E1")
    for col, w in enumerate(WIDTH, 1):
        ws.column_dimensions[ws.cell(1, col).column_letter].width = w
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for col in range(ANS, len(HEAD) + 1):
        ws.cell(1, col).fill = PatternFill("solid", fgColor="FFF2B3")
    ws.freeze_panes = "D2"
    ws.auto_filter.ref = ws.dimensions
    for offset, values in enumerate(CHOICES):
        dv = DataValidation(type="list", formula1=values, allow_blank=True, showErrorMessage=True,
                            errorTitle="Выберите из списка", error="Значение — только из выпадающего списка")
        ws.add_data_validation(dv)
        letter = ws.cell(1, ANS + offset).column_letter
        dv.add(f"{letter}2:{letter}{len(rows) + 1}")


def main() -> None:
    src, out = sys.argv[1], sys.argv[2]
    with open(src, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["queue"] = 1 if any(x in r["why"] for x in QUEUE1) else 2
    rows.sort(key=lambda r: (r["queue"], -float(r["att_a"])))

    wb = Workbook()
    how = wb.active
    how.title = "Как заполнять"
    how.column_dimensions["A"].width = 120
    for line in HOW:
        how.append([line])
    how["A1"].font = Font(bold=True)
    review_sheet(wb.create_sheet("Проверка"), rows)
    cb = wb.create_sheet("Типы сайтов")
    cb.append(["Тип", "Что сюда относится"])
    for row in TYPES:
        cb.append(row)
    cb.column_dimensions["A"].width = 30
    cb.column_dimensions["B"].width = 110
    for c in cb[1]:
        c.font = Font(bold=True)
    wb.save(out)
    q1 = [r for r in rows if r["queue"] == 1]
    print(f"строк {len(rows)}: очередь 1 — {len(q1)} (внимание {sum(float(r['att_a']) for r in q1):.1f} %), "
          f"очередь 2 — {len(rows) - len(q1)} (внимание {sum(float(r['att_a']) for r in rows if r['queue'] == 2):.1f} %)")


if __name__ == "__main__":
    main()
