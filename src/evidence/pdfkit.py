"""Shared look and feel for the SkillSprint AI submission PDFs (ReportLab).
Espresso / gold palette, serif titles, numbered contents page, header and footer on every page."""
import os
import textwrap
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph, Spacer, Table, TableStyle,
                                PageBreak, KeepTogether, Preformatted, NextPageTemplate, CondPageBreak, Flowable)
from reportlab.platypus.tableofcontents import TableOfContents

FD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts") + os.sep   # fonts ship with the project, so this works on Windows too
for name, f in [("Sans", "LiberationSans-Regular"), ("Sans-B", "LiberationSans-Bold"), ("Sans-I", "LiberationSans-Italic"),
                ("Sans-BI", "LiberationSans-BoldItalic"), ("Serif", "LiberationSerif-Regular"), ("Serif-B", "LiberationSerif-Bold"),
                ("Serif-I", "LiberationSerif-Italic"), ("Mono", "LiberationMono-Regular"), ("Mono-B", "LiberationMono-Bold")]:
    pdfmetrics.registerFont(TTFont(name, FD + f + ".ttf"))
pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-B", italic="Sans-I", boldItalic="Sans-BI")
pdfmetrics.registerFontFamily("Serif", normal="Serif", bold="Serif-B", italic="Serif-I", boldItalic="Serif-B")
pdfmetrics.registerFontFamily("Mono", normal="Mono", bold="Mono-B", italic="Mono", boldItalic="Mono-B")

ESP = colors.HexColor("#3d3028")
DARK = colors.HexColor("#241b16")
GOLD = colors.HexColor("#c9922e")
GOLD_L = colors.HexColor("#e3b562")
CREAM = colors.HexColor("#f7f1ea")
CREAM2 = colors.HexColor("#efe6db")
LINE = colors.HexColor("#d9ccbd")
MUTED = colors.HexColor("#6b5a4d")
INK = colors.HexColor("#231c17")
GREEN = colors.HexColor("#2b7a53")
GREEN_L = colors.HexColor("#e3f2e9")
RED = colors.HexColor("#a3372a")
RED_L = colors.HexColor("#f8e4e0")
AMBER_L = colors.HexColor("#fbf0d4")
BLUE = colors.HexColor("#2a5d8f")
BLUE_L = colors.HexColor("#e2edf7")

S = {
    "body": ParagraphStyle("body", fontName="Sans", fontSize=9.4, leading=13.6, textColor=INK, spaceAfter=5),
    "small": ParagraphStyle("small", fontName="Sans", fontSize=8, leading=11, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Sans", fontSize=8, leading=10.2, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Sans-B", fontSize=8, leading=10.2, textColor=INK),
    "cellh": ParagraphStyle("cellh", fontName="Sans-B", fontSize=7.8, leading=10, textColor=colors.white),
    "cellm": ParagraphStyle("cellm", fontName="Mono", fontSize=7.4, leading=9.6, textColor=INK),
    "h1": ParagraphStyle("h1", fontName="Serif-B", fontSize=21, leading=25, textColor=DARK, spaceBefore=0, spaceAfter=4),
    "h2": ParagraphStyle("h2", fontName="Sans-B", fontSize=12, leading=15, textColor=ESP, spaceBefore=12, spaceAfter=4, keepWithNext=1),
    "h3": ParagraphStyle("h3", fontName="Sans-B", fontSize=10, leading=13, textColor=ESP, spaceBefore=8, spaceAfter=3, keepWithNext=1),
    "lead": ParagraphStyle("lead", fontName="Serif-I", fontSize=11.2, leading=15.5, textColor=MUTED, spaceAfter=8),
    "bullet": ParagraphStyle("bullet", fontName="Sans", fontSize=9.4, leading=13.4, textColor=INK, leftIndent=13, bulletIndent=2, spaceAfter=2.5),
    "toc0": ParagraphStyle("toc0", fontName="Sans-B", fontSize=9.6, leading=14.6, spaceBefore=1.5, textColor=DARK, leftIndent=0),
    "toc1": ParagraphStyle("toc1", fontName="Sans", fontSize=8.4, leading=11.2, textColor=MUTED, leftIndent=16),
    "clause": ParagraphStyle("clause", fontName="Sans", fontSize=9.3, leading=13.2, textColor=INK, leftIndent=34, firstLineIndent=-34, spaceAfter=3),
    "tag": ParagraphStyle("tag", fontName="Sans-I", fontSize=8, leading=11, textColor=MUTED, spaceAfter=3),
}


def P(text, style="body"):
    return Paragraph(text, S[style] if isinstance(style, str) else style)


def esc(t):
    return escape(str(t if t is not None else ""))


class Heading(Paragraph):
    """A heading that the table of contents can pick up."""
    def __init__(self, text, level=0, style=None):
        super().__init__(text, S[style or ("h1" if level == 0 else "h2")])
        self.level, self.toc_text = level, text


def H1(text):
    return [CondPageBreak(60 * mm), Heading(text, 0), GoldRule()]


def H2(text):
    return Heading(text, 1)


class GoldRule(Flowable):
    def __init__(self, width=None, thickness=2):
        super().__init__()
        self.w, self.t = width, thickness
        self.height = 6

    def wrap(self, aw, ah):
        self.aw = self.w or aw
        return aw, 8

    def draw(self):
        self.canv.setStrokeColor(GOLD)
        self.canv.setLineWidth(self.t)
        self.canv.line(0, 2, 38 * mm, 2)
        self.canv.setStrokeColor(LINE)
        self.canv.setLineWidth(0.6)
        self.canv.line(38 * mm, 2, self.aw, 2)


def bullets(items, style="bullet"):
    return [Paragraph(i, S[style], bulletText="•") for i in items]


def callout(title, text, kind="info", width=None):
    bar, bg = {"info": (GOLD, AMBER_L), "ok": (GREEN, GREEN_L), "warn": (RED, RED_L), "note": (BLUE, BLUE_L)}[kind]
    inner = [Paragraph(f"<b>{title}</b>", ParagraphStyle("ct", fontName="Sans-B", fontSize=9, leading=12, textColor=INK, spaceAfter=2)),
             Paragraph(text, ParagraphStyle("cx", fontName="Sans", fontSize=8.8, leading=12.4, textColor=INK))]
    t = Table([[inner]], colWidths=[width] if width else None)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), bg), ("LINEBEFORE", (0, 0), (0, -1), 3.2, bar),
                           ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    return [t, Spacer(1, 7)]


def code(text, width_chars=104, size=7.3, label=None, max_lines=None):
    """Monospace block on a cream panel. Long lines are wrapped so nothing runs off the page."""
    lines = []
    for raw in str(text).splitlines() or [""]:
        indent = len(raw) - len(raw.lstrip(" "))
        wrapped = textwrap.wrap(raw, width=width_chars, subsequent_indent=" " * min(indent + 2, 24), break_long_words=True,
                                replace_whitespace=False, drop_whitespace=False) or [""]
        lines.extend(wrapped)
    if max_lines and len(lines) > max_lines:
        cut = len(lines) - max_lines
        lines = lines[: max_lines // 2] + [f"   ... [{cut} lines omitted here - full text is in the evidence bundle] ..."] + lines[-(max_lines // 2):]
    st = ParagraphStyle("code", fontName="Mono", fontSize=size, leading=size * 1.32, textColor=INK, backColor=colors.HexColor("#f4eee6"),
                        borderColor=LINE, borderWidth=0.6, borderPadding=(6, 7, 6, 7), leftIndent=8, rightIndent=8, spaceBefore=8, spaceAfter=10)
    out = []
    if label:
        out.append(Paragraph(f"<font name='Sans-B' size='7.6' color='#6b5a4d'>{esc(label).upper()}</font>",
                             ParagraphStyle("cl", fontName="Sans-B", fontSize=7.6, leading=10, spaceBefore=4, spaceAfter=0)))
    out.append(Preformatted("\n".join(lines), st))
    return out


def table(rows, widths, header=True, zebra=True, font=None, align_right=(), col_style=None, repeat=1, pad=4):
    """rows: list of lists of str / Paragraph. First row is the header."""
    data = []
    for ri, r in enumerate(rows):
        row = []
        for ci, c in enumerate(r):
            if isinstance(c, Flowable):
                row.append(c)
            else:
                st = "cellh" if (header and ri == 0) else ((col_style or {}).get(ci, "cell"))
                row.append(Paragraph(esc(c) if not str(c).startswith("<") else str(c), S[st]))
        data.append(row)
    t = Table(data, colWidths=widths, repeatRows=repeat if header else 0)
    st = [("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), pad), ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
          ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
          ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BOX", (0, 0), (-1, -1), 0.6, LINE)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), ESP), ("LINEBELOW", (0, 0), (-1, 0), 1.4, GOLD)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if (i % 2) == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), CREAM))
    t.setStyle(TableStyle(st))
    return t


def kv(rows, widths=(48 * mm, 126 * mm)):
    data = [[Paragraph(f"<b>{esc(k)}</b>", S["cell"]), Paragraph(v if any(t in str(v) for t in ("<font", "<b>", "<i>")) else esc(v), S["cell"])] for k, v in rows]
    t = Table(data, colWidths=list(widths))
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BACKGROUND", (0, 0), (0, -1), CREAM2),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6)]))
    return t


def stat_cards(items, width=174 * mm):
    """items: [(big, label)] -> a row of number cards."""
    n = len(items)
    cw = width / n
    cells = [[Paragraph(f"<font name='Serif-B' size='19' color='#3d3028'>{esc(b)}</font><br/><font name='Sans' size='7.6' color='#6b5a4d'>{esc(l)}</font>",
                        ParagraphStyle("sc", leading=22, alignment=1)) for b, l in items]]
    t = Table(cells, colWidths=[cw] * n, rowHeights=[46])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), CREAM), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("INNERGRID", (0, 0), (-1, -1), 0.6, LINE), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                           ("LINEABOVE", (0, 0), (-1, 0), 2.2, GOLD)]))
    return t


class ReportDoc(BaseDocTemplate):
    """A4 document with a cover page, contents page, and portrait + landscape body templates."""
    def __init__(self, path, title, deliverable, cover, **kw):
        super().__init__(path, pagesize=A4, title=title, author="SkillSprint AI Team", subject=deliverable,
                         leftMargin=18 * mm, rightMargin=18 * mm, topMargin=22 * mm, bottomMargin=18 * mm, **kw)
        self.title_txt, self.deliverable, self.cover = title, deliverable, cover
        pw, ph = A4
        fp = Frame(18 * mm, 18 * mm, pw - 36 * mm, ph - 40 * mm, id="p", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        lw, lh = landscape(A4)
        fl = Frame(14 * mm, 16 * mm, lw - 28 * mm, lh - 36 * mm, id="l", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([
            PageTemplate("cover", frames=[Frame(0, 0, pw, ph, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=self._cover, pagesize=A4),
            PageTemplate("port", frames=[fp], onPage=self._page, pagesize=A4),
            PageTemplate("land", frames=[fl], onPage=self._page, pagesize=landscape(A4)),
        ])

    def afterFlowable(self, f):
        if isinstance(f, Heading):
            key = f"h{self.seq.nextf('bm')}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(f.toc_text.replace("<b>", "").replace("</b>", ""), key, level=f.level, closed=f.level == 1)
            self.notify("TOCEntry", (f.level, f.toc_text, self.page, key))

    def _cover(self, c, doc):
        self.cover(c, doc)

    def _page(self, c, doc):
        w, h = c._pagesize
        c.saveState()
        c.setFillColor(ESP)
        c.rect(0, h - 11 * mm, w, 11 * mm, fill=1, stroke=0)
        c.setFillColor(GOLD)
        c.rect(0, h - 11.6 * mm, w, 0.6 * mm, fill=1, stroke=0)
        c.setFont("Serif-B", 11)
        c.setFillColor(colors.HexColor("#f6eee5"))
        c.drawString(16 * mm, h - 7.4 * mm, "SkillSprint")
        c.setFont("Sans", 7.8)
        c.setFillColor(GOLD_L)
        c.drawRightString(w - 16 * mm, h - 7.2 * mm, self.deliverable)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.6)
        c.line(16 * mm, 12 * mm, w - 16 * mm, 12 * mm)
        c.setFont("Sans", 7.6)
        c.setFillColor(MUTED)
        c.drawString(16 * mm, 8 * mm, self.title_txt)
        c.drawRightString(w - 16 * mm, 8 * mm, f"Page {doc.page}")
        c.restoreState()


def make_toc():
    toc = TableOfContents(dotsMinLevel=0)
    toc.levelStyles = [S["toc0"], S["toc1"]]
    return toc


def draw_cover(c, doc, kicker, title_lines, subtitle, facts, badge):
    """Full-page cover: espresso top block with wordmark + title, cream lower block with facts."""
    w, h = A4
    c.saveState()
    c.setFillColor(ESP)
    c.rect(0, h * 0.40, w, h * 0.60, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#2f251e"))
    c.circle(w - 30 * mm, h - 26 * mm, 62 * mm, fill=1, stroke=0)
    c.setFillColor(ESP)
    c.rect(0, h * 0.40, w, 12, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.rect(0, h * 0.40 - 3, w, 3, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#f6eee5"))
    c.setFont("Serif-B", 30)
    c.drawString(24 * mm, h - 36 * mm, "SkillSprint")
    c.setStrokeColor(GOLD_L)
    c.setLineWidth(2.6)
    p = c.beginPath()
    p.moveTo(25 * mm, h - 40.5 * mm)
    p.curveTo(48 * mm, h - 43 * mm, 76 * mm, h - 42.5 * mm, 88 * mm, h - 37.5 * mm)
    c.drawPath(p, stroke=1, fill=0)
    c.setFont("Sans", 9.5)
    c.setFillColor(GOLD_L)
    c.drawString(25 * mm, h - 49 * mm, "Generative AI PowerPlay  ·  Theme: OnboardVerse")
    # badge
    c.setFillColor(GOLD)
    c.roundRect(24 * mm, h - 92 * mm, 62 * mm, 8 * mm, 4, fill=1, stroke=0)
    c.setFillColor(DARK)
    c.setFont("Sans-B", 8.6)
    c.drawString(28 * mm, h - 89.4 * mm, badge.upper())
    c.setFillColor(colors.HexColor("#f6eee5"))
    c.setFont("Serif-B", 34)
    y = h - 112 * mm
    for ln in title_lines:
        c.drawString(24 * mm, y, ln)
        y -= 14.5 * mm
    c.setFont("Serif-I", 13)
    c.setFillColor(colors.HexColor("#e3d6c8"))
    for i, ln in enumerate(textwrap.wrap(subtitle, 78)):
        c.drawString(24 * mm, y - 2 * mm - i * 6.4 * mm, ln)
    # facts
    c.setFillColor(CREAM)
    c.rect(0, 0, w, h * 0.40 - 3, fill=1, stroke=0)
    y = h * 0.40 - 22 * mm
    for k, v in facts:
        c.setFont("Sans-B", 8)
        c.setFillColor(MUTED)
        c.drawString(24 * mm, y, k.upper())
        c.setFont("Sans", 10.5)
        c.setFillColor(INK)
        c.drawString(68 * mm, y, v)
        c.setStrokeColor(LINE)
        c.setLineWidth(0.5)
        c.line(24 * mm, y - 3.2 * mm, w - 24 * mm, y - 3.2 * mm)
        y -= 9 * mm
    c.setFont("Sans", 7.8)
    c.setFillColor(MUTED)
    c.drawString(24 * mm, 14 * mm, "Submission document prepared in line with SRS Section 1.10 (Project Deliverables).")
    c.restoreState()
