"""
renderer.py — рендерит текст решения в одну или несколько читаемых картинок.
Светлая тема, крупный шрифт, разбивка на страницы при длинном тексте.
"""
import io
import re
import textwrap
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# ── Цвета светлой темы ────────────────────────────────────────────
BG         = "#FFFFFF"
BG_HEADER  = "#EEF2FF"
BG_STEP    = "#F0FFF4"
BG_FORMULA = "#FFFBEB"
BG_ANSWER  = "#FFF0F0"

C_TITLE    = "#1E3A8A"   # тёмно-синий
C_STEP     = "#065F46"   # тёмно-зелёный
C_FORMULA  = "#92400E"   # коричневый
C_ANSWER   = "#B91C1C"   # красный
C_TEXT     = "#1F2937"   # почти чёрный
C_MUTED    = "#6B7280"   # серый
C_BORDER   = "#D1D5DB"

FONT       = "DejaVu Sans"
LINES_PER_PAGE = 28       # строк на одну картинку
FIG_W      = 12           # ширина (дюймы)
LINE_H     = 0.5          # высота строки (дюймы)
PADDING    = 0.4          # отступ сверху/снизу
DPI        = 150


# ── Публичный API ─────────────────────────────────────────────────

def render_solution(text: str, title: str = "") -> io.BytesIO:
    """
    Обратная совместимость: возвращает ОДНУ картинку (первую страницу).
    Для многостраничного вывода используй render_pages().
    """
    pages = render_pages(text, title)
    return pages[0]


def render_pages(text: str, title: str = "") -> list[io.BytesIO]:
    """
    Разбивает текст на страницы и рендерит каждую в отдельный BytesIO (PNG).
    Возвращает список BytesIO — по одному на каждую картинку.
    """
    blocks = _parse_blocks(text)
    pages  = _paginate(blocks, LINES_PER_PAGE)
    result = []
    total  = len(pages)
    for idx, page_blocks in enumerate(pages):
        page_title = title
        if total > 1:
            page_title = f"{title}  [{idx+1}/{total}]" if title else f"Страница {idx+1}/{total}"
        result.append(_render_page(page_blocks, page_title))
    return result


# ── Структура блока ───────────────────────────────────────────────

class Block:
    """Одна визуальная строка с метаданными."""
    __slots__ = ("text", "kind", "indent")

    def __init__(self, text: str, kind: str = "text", indent: int = 0):
        self.text   = text
        self.kind   = kind    # "title"|"h2"|"step"|"formula"|"answer"|"text"|"muted"|"blank"
        self.indent = indent  # 0..3


# ── Парсинг текста в блоки ────────────────────────────────────────

def _parse_blocks(text: str) -> list[Block]:
    blocks = []
    for raw in text.split("\n"):
        line = raw.rstrip()

        if not line.strip():
            blocks.append(Block("", "blank"))
            continue

        stripped = line.strip()

        # Заголовки markdown
        if stripped.startswith("### "):
            blocks.append(Block(stripped[4:], "h2"))
            continue
        if stripped.startswith("## "):
            blocks.append(Block(stripped[3:], "h2"))
            continue
        if stripped.startswith("# "):
            blocks.append(Block(stripped[2:], "h2"))
            continue

        # **Жирный** → step
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            blocks.append(Block(stripped[2:-2], "step"))
            continue

        # Шаг / Дано / Ответ
        low = stripped.lower()
        if re.match(r"^(шаг\s*\d+|step\s*\d+|\d+[\.\)])", low):
            blocks.append(Block(stripped, "step"))
            continue
        if re.match(r"^(дано|найти|решение|вывод|итог)[\s:：]", low):
            blocks.append(Block(stripped, "step"))
            continue
        if re.match(r"^(ответ|answer|результат)[\s:：]", low):
            blocks.append(Block(stripped, "answer"))
            continue

        # Формулы: строка содержит $...$ или = и математические символы
        formula_pat = r"\$[^$]+\$|[a-zA-Zα-ωА-Яа-я]\s*=\s*[\d\$\(]"
        if re.search(formula_pat, stripped) and len(stripped) < 120:
            blocks.append(Block(stripped, "formula"))
            continue

        # Отступ = вложенный текст
        indent = (len(line) - len(line.lstrip())) // 2
        blocks.append(Block(stripped, "text", indent=min(indent, 3)))

    # Убираем лишние пустые строки подряд
    result = []
    prev_blank = False
    for b in blocks:
        if b.kind == "blank":
            if not prev_blank:
                result.append(b)
            prev_blank = True
        else:
            prev_blank = False
            result.append(b)
    return result


# ── Перенос строк ─────────────────────────────────────────────────

def _expand_block(block: Block, max_chars: int = 80) -> list[Block]:
    """Разбивает длинный блок на несколько строк."""
    if len(block.text) <= max_chars or block.kind == "blank":
        return [block]
    parts = textwrap.wrap(block.text, width=max_chars,
                          break_long_words=False, break_on_hyphens=True)
    result = []
    for i, p in enumerate(parts):
        kind = block.kind if i == 0 else "text"
        result.append(Block(p, kind, block.indent))
    return result


# ── Разбивка на страницы ──────────────────────────────────────────

def _paginate(blocks: list[Block], per_page: int) -> list[list[Block]]:
    expanded = []
    for b in blocks:
        expanded.extend(_expand_block(b))

    pages = []
    cur   = []
    count = 0
    for b in expanded:
        line_cost = 0 if b.kind == "blank" else 1
        if count + line_cost > per_page and cur:
            pages.append(cur)
            cur   = []
            count = 0
        cur.append(b)
        count += line_cost

    if cur:
        pages.append(cur)
    return pages or [[]]


# ── Рендер одной страницы ─────────────────────────────────────────

def _render_page(blocks: list[Block], title: str) -> io.BytesIO:
    # Считаем реальные строки (без blank)
    real_lines = sum(1 for b in blocks if b.kind != "blank")
    blank_lines = sum(1 for b in blocks if b.kind == "blank")

    fig_h = PADDING * 2 + real_lines * LINE_H + blank_lines * (LINE_H * 0.4)
    if title:
        fig_h += 0.7
    fig_h = max(fig_h, 3.0)

    fig = Figure(figsize=(FIG_W, fig_h), facecolor=BG)
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, FIG_W)
    ax.set_ylim(0, fig_h)
    ax.axis("off")
    ax.set_facecolor(BG)

    # Тонкая рамка вокруг всего
    for spine in ["top", "bottom", "left", "right"]:
        ax.spines[spine].set_visible(False)

    y = fig_h - PADDING

    # ── Заголовок ──
    if title:
        # Фон заголовка
        ax.add_patch(plt.Rectangle(
            (0, y - 0.55), FIG_W, 0.65,
            facecolor=BG_HEADER, edgecolor=C_BORDER, lw=1.5,
            transform=ax.transData, clip_on=False
        ))
        ax.text(
            FIG_W / 2, y - 0.12,
            _clean(title),
            fontsize=16, fontweight="bold",
            color=C_TITLE, ha="center", va="top",
            fontfamily=FONT
        )
        y -= 0.7

    # ── Строки ──
    for block in blocks:
        if block.kind == "blank":
            y -= LINE_H * 0.35
            continue

        x_left   = 0.25 + block.indent * 0.35
        x_right  = FIG_W - 0.25
        text_x   = x_left + 0.15

        cfg = _style(block.kind)

        # Фон строки
        if cfg["bg"]:
            ax.add_patch(plt.Rectangle(
                (x_left, y - LINE_H * 0.85),
                x_right - x_left, LINE_H * 0.92,
                facecolor=cfg["bg"], edgecolor="none",
                transform=ax.transData, clip_on=False,
                zorder=1
            ))
            # Левая полоска-акцент
            if cfg.get("bar"):
                ax.add_patch(plt.Rectangle(
                    (x_left, y - LINE_H * 0.85),
                    0.07, LINE_H * 0.92,
                    facecolor=cfg["bar"], edgecolor="none",
                    transform=ax.transData, clip_on=False,
                    zorder=2
                ))

        ax.text(
            text_x, y - LINE_H * 0.15,
            _clean(block.text),
            fontsize=cfg["size"],
            fontweight=cfg["weight"],
            color=cfg["color"],
            ha="left", va="top",
            fontfamily=FONT,
            zorder=3
        )
        y -= LINE_H

    # Нижняя подпись
    ax.text(
        FIG_W - 0.25, PADDING * 0.4,
        "Homework Helper Bot",
        fontsize=8, color=C_MUTED, ha="right", va="bottom",
        fontfamily=FONT
    )

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, bbox_inches="tight",
                facecolor=BG)
    buf.seek(0)
    plt.close("all")
    return buf


# ── Стили по типу блока ───────────────────────────────────────────

def _style(kind: str) -> dict:
    return {
        "title":   {"size": 17, "weight": "bold",   "color": C_TITLE,   "bg": BG_HEADER, "bar": C_TITLE},
        "h2":      {"size": 14, "weight": "bold",   "color": C_TITLE,   "bg": BG_HEADER, "bar": C_TITLE},
        "step":    {"size": 13, "weight": "bold",   "color": C_STEP,    "bg": BG_STEP,   "bar": C_STEP},
        "formula": {"size": 13, "weight": "normal", "color": C_FORMULA, "bg": BG_FORMULA,"bar": C_FORMULA},
        "answer":  {"size": 14, "weight": "bold",   "color": C_ANSWER,  "bg": BG_ANSWER, "bar": C_ANSWER},
        "text":    {"size": 12, "weight": "normal", "color": C_TEXT,    "bg": None,      "bar": None},
        "muted":   {"size": 11, "weight": "normal", "color": C_MUTED,   "bg": None,      "bar": None},
    }.get(kind, {"size": 12, "weight": "normal", "color": C_TEXT, "bg": None, "bar": None})


def _clean(text: str) -> str:
    """Убираем markdown-символы которые matplotlib не понимает."""
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)  # **bold**, *italic*
    text = re.sub(r"`([^`]*)`", r"\1", text)              # `code`
    text = re.sub(r"_{1,2}(.*?)_{1,2}", r"\1", text)      # __underline__
    # Убираем $ вокруг формул (оставляем сам текст формулы)
    text = re.sub(r"\$\$([^$]+)\$\$", r"\1", text)
    text = re.sub(r"\$([^$]+)\$", r"\1", text)
    return text.strip()
