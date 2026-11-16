"""Server-side review card exports: a PNG card and a PowerPoint deck.

Same content as the review card in the app, so a link, the website or another
tool can download them without building them in a browser.
"""
import io
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).parent / "fonts"
NAVY, NAVY2, BLUE, SKY = "#0B1B3F", "#14295A", "#2F6BFF", "#7FA6FF"
MUTED, LINE, SOFT, INK2 = "#64748B", "#E2E8F0", "#F1F5FB", "#334155"
GREEN, AMBER, RED, GREY = "#16A34A", "#F59E0B", "#E11D48", "#94A3B8"
PLACEHOLDERS = {"VBM-Vacant", "SS Direct (NPO)", "Vacant-Zone A", "Unassigned"}


def _col(p):
    if p is None:
        return GREY
    return GREEN if p >= 100 else AMBER if p >= 50 else RED


def _visit(n):
    if n is None:
        return "Never"
    return "Today" if n == 0 else "Yesterday" if n == 1 else f"{n}d ago"


def _n(v):
    """Indian digit grouping: 1,23,456."""
    v = int(round(v or 0))
    s, neg = str(abs(v)), v < 0
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts + [tail])
    return ("-" if neg else "") + s


def _money(v):
    v = float(v or 0)
    if v >= 1e7:
        return f"₹{v / 1e7:.2f} Cr"
    if v >= 1e5:
        return f"₹{v / 1e5:.1f} L"
    return "₹" + _n(v)


def _day(iso):
    try:
        return datetime.fromisoformat(str(iso)[:10]).strftime("%d %b %Y").lstrip("0")
    except ValueError:
        return str(iso or "")


def _now_ist():
    return (datetime.utcnow() + timedelta(hours=5, minutes=30)).strftime("%H:%M")


def _subtitle(d):
    par = d.get("parents") or {}
    S = d["summary"]
    bits = []
    if d.get("limited_to"):
        bits.append(f"Only {d['limited_to']} area")
    if par.get("towns"):
        bits.append(", ".join(par["towns"]))
    if par.get("ss"):
        bits.append(f"SS {par['ss']}")
    if par.get("kam"):
        bits.append(f"KAM {par['kam']}")
    bits.append(f"{S['counters']} counters")
    return " · ".join(bits)


def _counters_for(d, limit=None):
    if d["role"] == "TL":
        cs = d["counters"]
    else:
        cs = sorted([c for c in d["counters"] if (c.get("gap") or 0) > 0], key=lambda c: -(c.get("gap") or 0))
    return cs[:limit] if limit else cs


def file_name(d, ext):
    return f"{d['name']} - {d['role']} review {d['period']['end']}.{ext}"


# ---------------------------------------------------------------- PNG
class _Canvas:
    W, PAD = 1080, 48

    def __init__(self):
        self.f = {}
        self.img = Image.new("RGB", (self.W, 6000), NAVY)
        self.dr = ImageDraw.Draw(self.img)
        self.y = self.PAD

    def font(self, size, weight="Regular"):
        key = (size, weight)
        if key not in self.f:
            self.f[key] = ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)
        return self.f[key]

    def text(self, xy, s, size, weight="Regular", fill="#FFFFFF", anchor="la"):
        self.dr.text(xy, str(s), font=self.font(size, weight), fill=fill, anchor=anchor)

    def width(self, s, size, weight="Regular"):
        return self.dr.textlength(str(s), font=self.font(size, weight))

    def fit(self, s, size, weight, max_w):
        s = str(s)
        if self.width(s, size, weight) <= max_w:
            return s
        while s and self.width(s + "…", size, weight) > max_w:
            s = s[:-1]
        return s + "…"

    def wrap(self, s, size, weight, max_w):
        lines, cur = [], ""
        for word in str(s).split():
            t = (cur + " " + word).strip()
            if self.width(t, size, weight) <= max_w:
                cur = t
            else:
                if cur:
                    lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    def rrect(self, box, fill, radius=22, outline=None, width=2):
        self.dr.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def build_png(d) -> bytes:
    c = _Canvas()
    W, P = c.W, c.PAD
    S, per = d["summary"], d["period"]
    inner = W - 2 * P

    c.text((P, c.y), f"ZONE A · {d['role']} REVIEW", 22, "SemiBold", SKY)
    c.text((W - P, c.y), _day(per.get("end")), 22, "SemiBold", "#B9C7E8", "ra")
    c.y += 40
    c.text((P, c.y), c.fit(d["name"], 58, "ExtraBold", inner - 200), 58, "ExtraBold")
    c.text((W - P, c.y + 10), f"live {_now_ist()}", 22, "SemiBold", "#B9C7E8", "ra")
    c.y += 80
    for line in c.wrap(_subtitle(d), 24, "SemiBold", inner):
        c.text((P, c.y), line, 24, "SemiBold", "#B9C7E8")
        c.y += 34
    c.y += 18

    tiles = [("MTD sale", _n(S["sales"]), f"of {_n(S['target'])}", "#FFFFFF"),
             ("Achieved", f"{round(S.get('pct') or 0)}%", f"Gap {_n(S['gap'])}", _col(S.get("pct"))),
             ("Need / day", _n(S["need"]), f"{per.get('days_remaining')} days left", "#FFFFFF"),
             ("Today", _n(S["ftd"]), f"{S['ftd_counters']}/{S['counters']} sold", "#FFFFFF")]
    tw = (inner - 3 * 14) / 4
    for i, (label, val, small, colr) in enumerate(tiles):
        x = P + i * (tw + 14)
        c.rrect((x, c.y, x + tw, c.y + 150), NAVY2)
        c.text((x + 20, c.y + 18), label, 20, "SemiBold", "#9FB3DD")
        c.text((x + 20, c.y + 46), val, 46, "ExtraBold", colr)
        c.text((x + 20, c.y + 108), c.fit(small, 18, "Regular", tw - 36), 18, "Regular", "#9FB3DD")
    c.y += 174

    for f in d.get("flags") or []:
        lines = c.wrap(f["text"], 23, "SemiBold", inner - 48)
        h = 30 + 32 * len(lines)
        warn = f.get("kind") == "warn"
        c.rrect((P, c.y, W - P, c.y + h), "#3A2A12" if warn else "#3B1730", 18, AMBER if warn else RED, 3)
        for j, line in enumerate(lines):
            c.text((P + 24, c.y + 15 + 32 * j), line, 23, "SemiBold")
        c.y += h + 14

    def table(title, head, rows, colw, aligns):
        c.y += 10
        c.text((P, c.y), title, 30, "ExtraBold")
        c.y += 48
        top = c.y
        rh, hh = 74, 46
        h = hh + rh * len(rows) + 16
        c.rrect((P, top, W - P, top + h), "#FFFFFF", 26)
        x0 = P + 24
        xs, x = [], x0
        for w in colw:
            xs.append(x)
            x += w
        for i, t in enumerate(head):
            ax = xs[i] if aligns[i] == "l" else xs[i] + colw[i]
            c.text((ax, top + 16), t.upper(), 16, "SemiBold", MUTED, "la" if aligns[i] == "l" else "ra")
        y = top + hh
        for r_i, row in enumerate(rows):
            if r_i:
                c.dr.line((x0, y, W - P - 24, y), fill="#EEF2F7", width=2)
            for i, cell in enumerate(row):
                ax = xs[i] if aligns[i] == "l" else xs[i] + colw[i]
                anc = "la" if aligns[i] == "l" else "ra"
                if isinstance(cell, dict):
                    if cell.get("bar") is not None:
                        c.text((ax, y + 12), c.fit(cell["main"], 23, "ExtraBold", colw[i] - 10), 23, "ExtraBold", NAVY, anc)
                        c.text((ax, y + 41), c.fit(cell.get("sub", ""), 16, "SemiBold", colw[i] - 10), 16, "SemiBold", MUTED, anc)
                        bw = colw[i] - 20
                        c.rrect((ax, y + 63, ax + bw, y + 69), "#E9EEF6", 3)
                        c.rrect((ax, y + 63, ax + bw * min(100, max(cell["bar"], 0)) / 100, y + 69), cell["colr"], 3)
                    else:
                        c.text((ax, y + 22), cell["t"], cell.get("size", 24), cell.get("w", "ExtraBold"), cell.get("colr", NAVY), anc)
                        if cell.get("small"):
                            c.text((ax, y + 50), cell["small"], 15, "SemiBold", cell.get("small_colr", MUTED), anc)
                else:
                    c.text((ax, y + 22), str(cell), 22, "SemiBold", NAVY, anc)
            y += rh
        c.y = top + h + 18

    if d.get("team"):
        rows = [[{"main": t["name"], "sub": f"{_n(t['sales'])} / {_n(t['target'])}", "bar": t.get("pct") or 0, "colr": _col(t.get("pct"))},
                 {"t": f"{round(t.get('pct') or 0)}%", "colr": _col(t.get("pct"))}, {"t": _n(t.get("ftd"))},
                 {"t": f"{_n(t.get('need'))}/d"}] for t in d["team"][:14]]
        table("TLs", ["TL · MTD / target", "Ach", "FTD", "Need"], rows, [520, 130, 120, 166], "lrrr")

    cs = _counters_for(d, 20 if d["role"] == "TL" else 10)
    rows = []
    for cn in cs:
        dhot = (cn.get("dos") or 0) >= 45
        vhot = cn.get("days_since_visit") is None or cn["days_since_visit"] >= 20
        extra = (cn.get("tl") if d["role"] != "TL" else cn.get("club")) or ""
        rows.append([{"main": cn["name"], "sub": f"{_n(cn['sales'])} / {_n(cn['target']) if cn.get('target') else '—'} · FTD {cn.get('ftd_sales') or 0}" + (f" · {extra}" if extra else ""),
                      "bar": cn.get("pct") or 0, "colr": _col(cn.get("pct"))},
                     {"t": "—" if cn.get("pct") is None else f"{round(cn['pct'])}%", "colr": _col(cn.get("pct"))},
                     {"t": _n(cn.get("stock")), "small": "main" if cn.get("chain") else ("" if cn.get("dos") is None else f"{round(cn['dos'])}d"), "small_colr": RED if dhot else MUTED},
                     {"t": _visit(cn.get("days_since_visit")), "size": 19, "w": "SemiBold", "colr": RED if vhot else "#475569"}])
    if rows:
        table("Counters" if d["role"] == "TL" else "Biggest counter gaps", ["Counter · MTD / target", "Ach", "Stock", "Visit"], rows, [500, 110, 140, 186], "lrrr")

    if d.get("actions"):
        c.y += 6
        c.text((P, c.y), "Action plan", 30, "ExtraBold")
        c.y += 50
        for i, a in enumerate(d["actions"], 1):
            tl = c.wrap(a["title"], 23, "ExtraBold", inner - 110)
            bl = c.wrap(a["text"], 20, "Regular", inner - 110)
            h = 26 + 31 * len(tl) + 28 * len(bl) + 8
            c.rrect((P, c.y, W - P, c.y + h), NAVY2, 22)
            c.dr.ellipse((P + 22, c.y + 20, P + 66, c.y + 64), fill=BLUE)
            c.text((P + 44, c.y + 42), str(i), 22, "ExtraBold", "#FFFFFF", "mm")
            yy = c.y + 18
            for line in tl:
                c.text((P + 88, yy), line, 23, "ExtraBold")
                yy += 31
            for line in bl:
                c.text((P + 88, yy + 2), line, 20, "Regular", "#B9C7E8")
                yy += 28
            c.y += h + 12
    c.y += 8
    for line in c.wrap('Stock "main" = chain counter, stock held at the main retailer · d = days of stock · visits as logged in the app · V-Work live data', 17, "Regular", inner):
        c.text((P, c.y), line, 17, "Regular", "#7F93BD")
        c.y += 24
    c.y += P - 10
    out = io.BytesIO()
    c.img.crop((0, 0, W, int(c.y))).save(out, "PNG", optimize=True)
    return out.getvalue()


# ---------------------------------------------------------------- PPTX
def build_pptx(d) -> bytes:
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
    from pptx.util import Inches, Pt

    rgb = lambda h: RGBColor.from_string(h.lstrip("#"))
    S, per = d["summary"], d["period"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(10), Inches(5.625)
    blank = prs.slide_layouts[6]
    prs.core_properties.title = f"{d['name']} {d['role']} review"
    prs.core_properties.author = "Zone A"

    def text(sl, x, y, w, h, runs, size=12, color=NAVY, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
        tb = sl.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = True
        tf.vertical_anchor = anchor
        for m in ("margin_left", "margin_right", "margin_top", "margin_bottom"):
            setattr(tf, m, 0)
        if isinstance(runs, str):
            runs = [(runs, {})]
        p = tf.paragraphs[0]
        p.alignment = align
        for i, (t, o) in enumerate(runs):
            if o.get("newline") and i:
                p = tf.add_paragraph()
                p.alignment = align
            r = p.add_run()
            r.text = t
            r.font.name = "Calibri"
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.color.rgb = rgb(o.get("color", color))
        return tb

    def box(sl, x, y, w, h, fill, line=None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
        s = sl.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
        if line:
            s.line.color.rgb = rgb(line)
        else:
            s.line.fill.background()
        if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
            s.adjustments[0] = 0.08
        s.shadow.inherit = False
        return s

    def body(title, sub=None):
        sl = prs.slides.add_slide(blank)
        box(sl, 0, 0, 10, 0.07, BLUE, shape=MSO_SHAPE.RECTANGLE)
        text(sl, 0.4, 0.25, 9.2, 0.5, title, 24, NAVY, True)
        if sub:
            text(sl, 0.4, 0.74, 9.2, 0.3, sub, 12, MUTED)
        text(sl, 0.4, 5.25, 6, 0.3, f"Zone A · {d['role']} review · {d['name']}", 9, MUTED)
        return sl

    def dark():
        sl = prs.slides.add_slide(blank)
        sl.background.fill.solid()
        sl.background.fill.fore_color.rgb = rgb(NAVY)
        return sl

    def table(sl, x, y, w, colw, head, rows, size=9.5):
        shp = sl.shapes.add_table(len(rows) + 1, len(head), Inches(x), Inches(y), Inches(w), Inches(0.29 * (len(rows) + 1)))
        t = shp.table
        for i, cw in enumerate(colw):
            t.columns[i].width = Inches(cw)
        for r in range(len(rows) + 1):
            t.rows[r].height = Inches(0.29)
        for j, h in enumerate(head):
            cell = t.cell(0, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = rgb(NAVY)
            _cell_text(cell, h, size, "#FFFFFF", True, PP_ALIGN.LEFT if j == 0 else PP_ALIGN.RIGHT)
        for i, row in enumerate(rows, 1):
            for j, v in enumerate(row):
                cell = t.cell(i, j)
                cell.fill.solid()
                cell.fill.fore_color.rgb = rgb("#FFFFFF" if i % 2 else "#F8FAFC")
                v = v if isinstance(v, dict) else {"t": v}
                _cell_text(cell, v["t"], size, v.get("color", NAVY), v.get("bold", j == 0), PP_ALIGN.LEFT if j == 0 else PP_ALIGN.RIGHT)
        return t

    def _cell_text(cell, t, size, color, bold, align):
        cell.margin_left = cell.margin_right = Inches(0.05)
        cell.margin_top = cell.margin_bottom = Inches(0.02)
        cell.vertical_anchor = MSO_ANCHOR.MIDDLE
        tf = cell.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.alignment = align
        r = p.add_run()
        r.text = str(t)
        r.font.name = "Calibri"
        r.font.size = Pt(size)
        r.font.bold = bold
        r.font.color.rgb = rgb(color)

    # 1 title
    sl = dark()
    text(sl, 0.6, 1.3, 8.8, 0.4, f"ZONE A · {d['role']} REVIEW", 14, SKY, True)
    text(sl, 0.6, 1.75, 8.8, 0.9, d["name"], 40, "#FFFFFF", True)
    text(sl, 0.6, 2.75, 8.8, 0.5, _subtitle(d), 15, "#B9C7E8")
    text(sl, 0.6, 4.6, 8.8, 0.35, f"{_day(per.get('end'))} · V-Work live data till {_now_ist()}", 12, "#9FB3DD")

    # 2 scorecard
    sl = body("Month so far", f"{per.get('days_remaining')} days left including today")
    tiles = [("MTD sale", _n(S["sales"]), f"of {_n(S['target'])} target", NAVY),
             ("Achieved", f"{round(S.get('pct') or 0)}%", f"Gap {_n(S['gap'])} units", _col(S.get("pct"))),
             ("Need per day", _n(S["need"]), "units to close the target", NAVY),
             ("Today (FTD)", _n(S["ftd"]), f"{S['ftd_counters']} of {S['counters']} counters sold", NAVY)]
    for i, (a, v, small, colr) in enumerate(tiles):
        x = 0.4 + i * 2.33
        box(sl, x, 1.2, 2.15, 1.55, "#F1F5FB")
        text(sl, x + 0.15, 1.3, 1.9, 0.3, a, 12, MUTED)
        text(sl, x + 0.15, 1.6, 1.9, 0.65, v, 32, colr, True)
        text(sl, x + 0.15, 2.3, 1.95, 0.35, small, 10.5, MUTED)
    y = 3.05
    for f in (d.get("flags") or [])[:3]:
        warn = f.get("kind") == "warn"
        box(sl, 0.4, y, 9.2, 0.55, "#FEF3E2" if warn else "#FDECEA", AMBER if warn else RED)
        text(sl, 0.55, y, 8.95, 0.55, f["text"], 12.5, NAVY, True, anchor=MSO_ANCHOR.MIDDLE)
        y += 0.68

    # 3 TLs
    team = d.get("team") or []
    for i in range(0, len(team), 12):
        part = team[i:i + 12]
        sl = body("TL performance" + (" (cont.)" if i else ""), "Lowest achievement first")
        table(sl, 0.4, 1.15, 5.4, [2.1, 0.65, 0.7, 0.6, 0.55, 0.8], ["TL", "MTD", "Target", "Ach", "FTD", "Need/day"],
              [[t["name"], _n(t["sales"]), _n(t["target"]), {"t": f"{round(t.get('pct') or 0)}%", "color": _col(t.get("pct")), "bold": True},
                _n(t.get("ftd")), _n(t.get("need"))] for t in part])
        cd = CategoryChartData()
        cd.categories = [t["name"].split(" ")[0] for t in part]
        cd.add_series("Achievement %", [round(t.get("pct") or 0) for t in part])
        ch = sl.shapes.add_chart(XL_CHART_TYPE.BAR_CLUSTERED, Inches(6.0), Inches(1.1), Inches(3.6), Inches(3.9), cd).chart
        ch.has_legend = False
        ch.has_title = True
        ch.chart_title.text_frame.text = "Achievement %"
        ch.chart_title.text_frame.paragraphs[0].runs[0].font.size = Pt(11)
        ch.value_axis.visible = False
        ch.value_axis.has_major_gridlines = False
        ch.category_axis.reverse_order = True
        ch.category_axis.tick_labels.font.size = Pt(9)
        pl = ch.plots[0]
        pl.has_data_labels = True
        pl.data_labels.font.size = Pt(9)
        pl.data_labels.position = XL_LABEL_POSITION.OUTSIDE_END
        pl.series[0].format.fill.solid()
        pl.series[0].format.fill.fore_color.rgb = rgb(BLUE)

    # 4 counters
    cs = _counters_for(d, None if d["role"] == "TL" else 24)
    for i in range(0, len(cs), 12):
        part = cs[i:i + 12]
        sl = body(("Counters" if d["role"] == "TL" else "Counters furthest behind") + (" (cont.)" if i else ""),
                  'Biggest sellers first · stock "main" = chain counter, stock held at the main retailer' if d["role"] == "TL" else "Largest unit gap first")
        rows = []
        for cn in part:
            dos = cn.get("dos") or 0
            vhot = cn.get("days_since_visit") is None or cn["days_since_visit"] >= 20
            rows.append([cn["name"] + (f"  ({cn['tl']})" if d["role"] != "TL" and cn.get("tl") else ""), _n(cn["sales"]), _n(cn.get("target")),
                         {"t": "—" if cn.get("pct") is None else f"{round(cn['pct'])}%", "color": _col(cn.get("pct")), "bold": True},
                         _n(cn.get("gap")), _n(cn.get("need")), _n(cn.get("ftd_sales")), _n(cn.get("stock")),
                         {"t": "main" if cn.get("chain") else ("—" if cn.get("dos") is None else str(round(dos))), "color": RED if dos >= 45 else NAVY, "bold": dos >= 45},
                         {"t": _visit(cn.get("days_since_visit")), "color": RED if vhot else NAVY}])
        table(sl, 0.4, 1.15, 9.2, [2.9, 0.6, 0.65, 0.6, 0.6, 0.75, 0.5, 0.6, 0.8, 1.2],
              ["Counter" if d["role"] == "TL" else "Counter · TL", "MTD", "Target", "Ach", "Gap", "Need/day", "FTD", "Stock", "Days stock", "Last visit"], rows)

    # 5 stock & visits
    heavy = sorted([cn for cn in d["counters"] if (cn.get("dos") or 0) >= 45 and (cn.get("stock") or 0) >= 10], key=lambda cn: -cn["dos"])[:10]
    stale = sorted([cn for cn in d["counters"] if cn.get("days_since_visit") is None or cn["days_since_visit"] >= 20], key=lambda cn: -(cn.get("target") or 0))[:10]
    if heavy or stale:
        sl = body("Stock and visits", "Stock not moving (45+ days) and counters not visited in 20+ days, as logged in the app")
        if heavy:
            table(sl, 0.4, 1.15, 4.4, [2.9, 0.75, 0.75], ["Stock not moving", "Stock", "Days"],
                  [[cn["name"], _n(cn["stock"]), {"t": str(round(cn["dos"])), "color": RED, "bold": True}] for cn in heavy], 10)
        if stale:
            table(sl, 5.2, 1.15, 4.4, [2.7, 0.75, 0.95], ["Not visited", "Target", "Last visit"],
                  [[cn["name"], _n(cn.get("target")), {"t": _visit(cn.get("days_since_visit")), "color": RED}] for cn in stale], 10)

    # 6 actions
    acts = d.get("actions") or []
    if acts:
        sl = dark()
        text(sl, 0.4, 0.3, 9.2, 0.55, "Action plan", 26, "#FFFFFF", True)
        h = min(0.82, 4.3 / len(acts))
        for i, a in enumerate(acts):
            yy = 1.0 + i * (h + 0.06)
            box(sl, 0.4, yy, 9.2, h, NAVY2)
            o = box(sl, 0.55, yy + (h - 0.42) / 2, 0.42, 0.42, BLUE, shape=MSO_SHAPE.OVAL)
            text(sl, 0.55, yy + (h - 0.42) / 2, 0.42, 0.42, str(i + 1), 14, "#FFFFFF", True, PP_ALIGN.CENTER, MSO_ANCHOR.MIDDLE)
            text(sl, 1.15, yy, 8.3, h, [(a["title"], {"bold": True, "size": 13.5, "color": "#FFFFFF"}),
                                        (a["text"], {"size": 11, "color": "#B9C7E8", "newline": True})], anchor=MSO_ANCHOR.MIDDLE)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
