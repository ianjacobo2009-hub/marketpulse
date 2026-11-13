"""Market Pulse desktop app (PySide6 / Qt)."""
from __future__ import annotations

import os
import sys
import webbrowser
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from . import __version__
from .engine import Pulse, get_pulse
from .summary import ai_summary, get_key, local_summary, set_key

ASSETS = (Path(getattr(sys, "_MEIPASS", "")) / "assets") if getattr(sys, "frozen", False) \
    else Path(__file__).resolve().parent.parent / "assets"
BG, CARD, LINE, TEXT, MUTED = "#f6f8fc", "#ffffff", "#e3e8f2", "#0f172a", "#64748b"
BLUE, GREEN, RED, AMBER = "#2563eb", "#16a34a", "#dc2626", "#d97706"

QSS = f"""
* {{ font-family: 'Helvetica Neue', 'Segoe UI', Arial, sans-serif; color: {TEXT}; }}
QMainWindow, QWidget#root, QScrollArea, QWidget#scroll {{ background: {BG}; border: none; }}
QFrame#card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 14px; }}
QLabel#muted {{ color: {MUTED}; font-size: 12px; }}
QLabel#h1 {{ font-size: 26px; font-weight: 700; }}
QLabel#h2 {{ font-size: 15px; font-weight: 700; }}
QLabel#big {{ font-size: 44px; font-weight: 800; }}
QPushButton {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 9px; padding: 7px 12px; }}
QPushButton:hover {{ border-color: {BLUE}; }}
QPushButton:checked {{ background: {BLUE}; color: white; border-color: {BLUE}; }}
QPushButton#primary {{ background: {BLUE}; color: white; border: none; font-weight: 600; padding: 13px 22px; font-size: 15px; }}
QPushButton#link {{ border: none; background: transparent; text-align: left; padding: 0; font-weight: 600; }}
QPushButton#link:hover {{ color: {BLUE}; }}
QLineEdit {{ border: 1px solid {LINE}; border-radius: 8px; padding: 8px; background: white; }}
"""

T = {
    "en": {"title": "What's happening in the markets today?", "sub": "Live prices, top news and a clear summary in seconds",
           "go": "Get today's market pulse", "loading": "Reading 20 markets and a year of history…", "refresh": "↻ Refresh",
           "present": "Presentation mode", "settings": "⚙ Settings", "gainers": "gainers", "losers": "losers",
           "unchanged": "unchanged", "avg": "Average move", "signals": "Quantitative signals", "summary": "Market summary",
           "news": "Top news", "copy": "Copy summary", "export": "Export report…", "asof": "Prices as of",
           "by_claude": "Written by Claude from today's data", "by_local": "Built from today's data · add a Claude key in Settings for a written analysis",
           "bullish": "BULLISH", "bearish": "BEARISH", "neutral": "NEUTRAL", "why": "What makes up the score",
           "disclaimer": "Data from Yahoo Finance. Statistical signals, not financial advice."},
    "es": {"title": "¿Qué está pasando hoy en los mercados?", "sub": "Precios en vivo, noticias clave y un resumen claro en segundos",
           "go": "Ver el pulso del mercado", "loading": "Leyendo 20 mercados y un año de historia…", "refresh": "↻ Actualizar",
           "present": "Modo presentación", "settings": "⚙ Ajustes", "gainers": "suben", "losers": "bajan",
           "unchanged": "sin cambio", "avg": "Movimiento promedio", "signals": "Señales cuantitativas", "summary": "Resumen del mercado",
           "news": "Noticias principales", "copy": "Copiar resumen", "export": "Exportar informe…", "asof": "Precios al",
           "by_claude": "Escrito por Claude con los datos de hoy", "by_local": "Hecho con los datos de hoy · agrega una clave de Claude en Ajustes para un análisis escrito",
           "bullish": "ALCISTA", "bearish": "BAJISTA", "neutral": "NEUTRAL", "why": "Qué compone el puntaje",
           "disclaimer": "Datos de Yahoo Finance. Señales estadísticas, no asesoría financiera."},
}
LABELS_ES = {"Extreme fear": "Miedo extremo", "Fear": "Miedo", "Neutral": "Neutral", "Greed": "Codicia",
             "Extreme greed": "Codicia extrema", "NET BULLISH": "BALANCE ALCISTA", "NET BEARISH": "BALANCE BAJISTA",
             "MIXED": "MIXTO", "Risk appetite": "Apetito de riesgo", "Dispersion": "Dispersión", "Volatility": "Volatilidad",
             "Unusual moves": "Movimientos inusuales", "Tech leadership": "Liderazgo tecnológico", "Crypto": "Cripto",
             "Trend": "Tendencia"}


class Worker(QObject):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *a):
        super().__init__(); self.fn, self.a = fn, a

    def run(self):
        try:
            self.done.emit(self.fn(*self.a))
        except Exception as e:
            self.failed.emit(str(e))


# ------------------------------------------------------------------ custom painted widgets
class Gauge(QWidget):
    """Horizontal fear-greed bar with a marker."""
    def __init__(self):
        super().__init__(); self.value = 50; self.setMinimumHeight(26)

    def set(self, v):
        self.value = v; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 8, self.width() - 8, 10)
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, QColor(RED)); g.setColorAt(0.5, QColor("#cbd5e1")); g.setColorAt(1, QColor(GREEN))
        path = QPainterPath(); path.addRoundedRect(r, 5, 5); p.fillPath(path, g)
        x = r.left() + r.width() * self.value / 100
        p.setPen(QPen(QColor(TEXT), 3)); p.drawLine(QPointF(x, 2), QPointF(x, 24))


class Spark(QWidget):
    def __init__(self, data, up):
        super().__init__(); self.data, self.up = data, up; self.setFixedHeight(34)

    def paintEvent(self, _):
        if len(self.data) < 2:
            return
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        lo, hi = min(self.data), max(self.data); span = (hi - lo) or 1
        w, h = self.width() - 2, self.height() - 4
        pts = [QPointF(1 + w * i / (len(self.data) - 1), 2 + h * (1 - (v - lo) / span)) for i, v in enumerate(self.data)]
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        p.setPen(QPen(QColor(GREEN if self.up else RED), 1.8)); p.drawPath(path)


def card():
    f = QFrame(objectName="card")
    return f


def fmt_price(q):
    if q.price >= 1000:
        return f"${q.price:,.0f}"
    return f"${q.price:,.2f}"


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("Settings"); self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("<b>Claude API key</b> (optional)"))
        info = QLabel("With a key, Market Pulse asks Claude to write the daily summary. Without one, it writes a "
                      "summary from the numbers. The key is kept in your system keychain, never in a file.",
                      objectName="muted"); info.setWordWrap(True); v.addWidget(info)
        self.key = QLineEdit(); self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("sk-ant-…  (saved)" if get_key() else "sk-ant-…")
        v.addWidget(self.key)
        row = QHBoxLayout()
        clear = QPushButton("Remove saved key"); clear.clicked.connect(self.remove); row.addWidget(clear); row.addStretch()
        v.addLayout(row)
        b = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        b.accepted.connect(self.save); b.rejected.connect(self.reject); v.addWidget(b)

    def save(self):
        if self.key.text().strip():
            set_key(self.key.text())
        self.accept()

    def remove(self):
        set_key(None); self.key.setPlaceholderText("sk-ant-…"); QMessageBox.information(self, "Settings", "Key removed.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Market Pulse")
        self.resize(1280, 900)
        self.lang = "en"
        self.pulse: Pulse | None = None
        self.summary_text, self.summary_src = "", "local"
        self._threads = []

        root = QWidget(objectName="root"); self.setCentralWidget(root)
        self.outer = QVBoxLayout(root); self.outer.setContentsMargins(24, 16, 24, 16)
        self.outer.addLayout(self._header())
        self.body = QScrollArea(); self.body.setWidgetResizable(True)
        self.outer.addWidget(self.body, 1)
        self._menu()
        self.show_home()

    # ---------- chrome
    def _header(self):
        h = QHBoxLayout()
        logo = QLabel()
        if (ASSETS / "icon.png").exists():
            logo.setPixmap(QPixmap(str(ASSETS / "icon.png")).scaled(34, 34, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        name = QLabel("Market Pulse"); name.setStyleSheet(f"font-size: 18px; font-weight: 700; color: {BLUE};")
        h.addWidget(logo); h.addWidget(name); h.addStretch()
        self.btn_refresh = QPushButton(); self.btn_refresh.clicked.connect(self.load); self.btn_refresh.hide()
        self.btn_present = QPushButton(); self.btn_present.setCheckable(True); self.btn_present.toggled.connect(self.present)
        self.btn_settings = QPushButton(); self.btn_settings.clicked.connect(self.open_settings)
        self.btn_es = QPushButton("ES"); self.btn_en = QPushButton("EN")
        for b, l in ((self.btn_es, "es"), (self.btn_en, "en")):
            b.setCheckable(True); b.setFixedWidth(44); b.clicked.connect(lambda _=False, l=l: self.set_lang(l))
        self.btn_en.setChecked(True)
        for w in (self.btn_refresh, self.btn_present, self.btn_settings, self.btn_es, self.btn_en):
            h.addWidget(w)
        self._retext()
        return h

    def _menu(self):
        m = self.menuBar().addMenu("File")
        a = QAction("Export report…", self); a.setShortcut("Ctrl+E"); a.triggered.connect(self.export); m.addAction(a)
        a = QAction("Refresh", self); a.setShortcut("Ctrl+R"); a.triggered.connect(self.load); m.addAction(a)
        h = self.menuBar().addMenu("Help")
        a = QAction("About Market Pulse", self); a.triggered.connect(self.about); h.addAction(a)

    def t(self, k):
        return T[self.lang][k]

    def tr(self, s):
        return LABELS_ES.get(s, s) if self.lang == "es" else s

    def _retext(self):
        self.btn_refresh.setText(self.t("refresh")); self.btn_present.setText(self.t("present"))
        self.btn_settings.setText(self.t("settings"))

    def set_lang(self, l):
        self.lang = l; self.btn_es.setChecked(l == "es"); self.btn_en.setChecked(l == "en"); self._retext()
        if self.pulse:
            if self.summary_src == "local":
                self.summary_text = local_summary(self.pulse, l)
            self.render(self.pulse)
            if self.summary_src == "claude":
                self.start_summary()
        else:
            self.show_home()

    # ---------- screens
    def show_home(self):
        w = QWidget(objectName="scroll"); v = QVBoxLayout(w); v.addStretch()
        icon = QLabel(); icon.setAlignment(Qt.AlignCenter)
        if (ASSETS / "icon.png").exists():
            icon.setPixmap(QPixmap(str(ASSETS / "icon.png")).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        t = QLabel(self.t("title"), objectName="h1"); t.setAlignment(Qt.AlignCenter)
        s = QLabel(self.t("sub"), objectName="muted"); s.setAlignment(Qt.AlignCenter); s.setStyleSheet("font-size: 15px;")
        self.go = QPushButton(self.t("go"), objectName="primary"); self.go.clicked.connect(self.load)
        self.go.setFixedWidth(340)
        row = QHBoxLayout(); row.addStretch(); row.addWidget(self.go); row.addStretch()
        d = QLabel(self.t("disclaimer"), objectName="muted"); d.setAlignment(Qt.AlignCenter)
        for x in (icon, t, s):
            v.addWidget(x)
        v.addSpacing(18); v.addLayout(row); v.addSpacing(8); v.addWidget(d); v.addStretch()
        self.body.setWidget(w)

    def load(self):
        if hasattr(self, "go") and self.go is not None:
            try:
                self.go.setEnabled(False); self.go.setText(self.t("loading"))
            except RuntimeError:
                pass
        self.btn_refresh.setEnabled(False)
        self._run(get_pulse, self.on_pulse)

    def _run(self, fn, ok, *a):
        th = QThread(self); w = Worker(fn, *a); w.moveToThread(th)
        th.started.connect(w.run); w.done.connect(ok); w.failed.connect(self.on_fail)
        w.done.connect(th.quit); w.failed.connect(th.quit)
        self._threads = [(x, y) for x, y in self._threads if not x.isFinished()]
        self._threads.append((th, w)); th.start()

    def on_fail(self, msg):
        self.btn_refresh.setEnabled(True)
        QMessageBox.warning(self, "Market Pulse", msg)
        if not self.pulse:
            self.show_home()

    def on_pulse(self, p: Pulse):
        self.pulse = p
        self.btn_refresh.show(); self.btn_refresh.setEnabled(True)
        self.summary_text, self.summary_src = local_summary(p, self.lang), "local"
        self.render(p)
        if get_key():
            self.start_summary()

    def start_summary(self):
        self._run(ai_summary, self.on_summary, self.pulse, self.lang)

    def on_summary(self, res):
        self.summary_text, self.summary_src = res
        self.summary_label.setText(self.summary_text)
        self.summary_src_label.setText(self.t("by_claude") if self.summary_src == "claude" else self.t("by_local"))

    # ---------- dashboard
    def render(self, p: Pulse):
        w = QWidget(objectName="scroll"); v = QVBoxLayout(w); v.setSpacing(14)
        date = QLabel(p.asof.strftime("%A, %B %-d, %Y") if self.lang == "en" else p.asof.strftime("%d/%m/%Y"), objectName="h1")
        v.addWidget(date)
        v.addWidget(QLabel(f"{self.t('asof')} {p.asof:%Y-%m-%d} · {len(p.quotes)} assets", objectName="muted"))

        top = QHBoxLayout(); top.setSpacing(14)
        # sentiment card
        sc = card(); sv = QVBoxLayout(sc); sv.setContentsMargins(20, 16, 20, 16)
        col = RED if p.sentiment < 40 else GREEN if p.sentiment > 60 else MUTED
        n = QLabel(f"{p.sentiment}<span style='font-size:20px;color:{MUTED}'> / 100</span>", objectName="big")
        n.setStyleSheet(f"color: {col};"); n.setAlignment(Qt.AlignCenter)
        lab = QLabel(self.tr(p.sentiment_label), objectName="h2"); lab.setAlignment(Qt.AlignCenter)
        g = Gauge(); g.set(p.sentiment)
        br = QLabel(f"<span style='color:{GREEN}'>▲ {p.gainers} {self.t('gainers')}</span> &nbsp; "
                    f"— {p.unchanged} {self.t('unchanged')} &nbsp; <span style='color:{RED}'>▼ {p.losers} {self.t('losers')}</span>")
        br.setAlignment(Qt.AlignCenter)
        avg = QLabel(f"{self.t('avg')}: {p.avg_change:+.2%}", objectName="muted"); avg.setAlignment(Qt.AlignCenter)
        parts = QLabel(self.t("why") + ": " + " · ".join(f"{self.tr(k)} {v:.0f}" for k, v in p.sentiment_parts.items()),
                       objectName="muted"); parts.setWordWrap(True); parts.setAlignment(Qt.AlignCenter)
        for x in (n, lab, g, br, avg, parts):
            sv.addWidget(x)
        top.addWidget(sc, 2)
        # summary card
        su = card(); suv = QVBoxLayout(su); suv.setContentsMargins(20, 16, 20, 16)
        suv.addWidget(QLabel(self.t("summary"), objectName="h2"))
        self.summary_label = QLabel(self.summary_text); self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-size: 14px; line-height: 150%;")
        self.summary_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.summary_src_label = QLabel(self.t("by_claude") if self.summary_src == "claude" else self.t("by_local"), objectName="muted")
        self.summary_src_label.setWordWrap(True)
        suv.addWidget(self.summary_label); suv.addStretch(); suv.addWidget(self.summary_src_label)
        bt = QHBoxLayout(); c = QPushButton(self.t("copy")); c.clicked.connect(self.copy)
        e = QPushButton(self.t("export")); e.clicked.connect(self.export); bt.addWidget(c); bt.addWidget(e); bt.addStretch()
        suv.addLayout(bt)
        top.addWidget(su, 3)
        v.addLayout(top)

        # tiles: indexes first, then everything else by size of move
        idx = [q for q in p.quotes if q.group == "index"]
        rest = sorted([q for q in p.quotes if q.group != "index"], key=lambda q: -abs(q.change))
        ir = QHBoxLayout(); ir.setSpacing(12)
        for q in idx:
            ir.addWidget(self._tile(q, True))
        v.addLayout(ir)
        grid = QGridLayout(); grid.setSpacing(12)
        for i, q in enumerate(rest):
            grid.addWidget(self._tile(q, False), i // 4, i % 4)
        v.addLayout(grid)

        # signals
        head = QHBoxLayout(); head.addWidget(QLabel(self.t("signals"), objectName="h2")); head.addStretch()
        net = QLabel(self.tr(p.net)); net.setStyleSheet(
            f"font-weight: 700; color: {GREEN if p.net == 'NET BULLISH' else RED if p.net == 'NET BEARISH' else MUTED};")
        head.addWidget(net); v.addLayout(head)
        sg = QGridLayout(); sg.setSpacing(12)
        for i, s in enumerate(p.signals):
            f = card(); fv = QVBoxLayout(f); fv.setContentsMargins(14, 12, 14, 12)
            row = QHBoxLayout(); row.addWidget(QLabel(self.tr(s.title), objectName="h2")); row.addStretch()
            stc = {"bullish": GREEN, "bearish": RED}.get(s.stance, MUTED)
            st = QLabel(self.t(s.stance)); st.setStyleSheet(f"color: {stc}; font-weight: 700; font-size: 11px;")
            row.addWidget(st); fv.addLayout(row)
            d = QLabel(s.detail, objectName="muted"); d.setWordWrap(True); d.setStyleSheet("font-size: 13px;"); fv.addWidget(d)
            sg.addWidget(f, i // 2, i % 2)
        v.addLayout(sg)

        # news
        if p.news:
            v.addWidget(QLabel(self.t("news"), objectName="h2"))
            ng = QGridLayout(); ng.setSpacing(12)
            for i, item in enumerate(p.news[:8]):
                f = card(); fv = QVBoxLayout(f); fv.setContentsMargins(14, 12, 14, 12)
                fv.addWidget(QLabel(item["source"].upper(), objectName="muted"))
                lab = QLabel(item["title"]); lab.setWordWrap(True); lab.setStyleSheet("font-weight: 600; font-size: 14px;")
                lab.setCursor(Qt.PointingHandCursor)
                url = item["url"]
                lab.mousePressEvent = (lambda _e, u=url: webbrowser.open(u)) if url else (lambda _e: None)
                fv.addWidget(lab)
                if item["summary"]:
                    s = QLabel(item["summary"], objectName="muted"); s.setWordWrap(True); fv.addWidget(s)
                fv.addStretch()
                ng.addWidget(f, i // 2, i % 2)
            v.addLayout(ng)
        v.addWidget(QLabel(self.t("disclaimer"), objectName="muted"))
        self.body.setWidget(w)

    def _tile(self, q, big):
        f = card(); v = QVBoxLayout(f); v.setContentsMargins(14, 10, 14, 10); v.setSpacing(2)
        dot = {"index": BLUE, "crypto": AMBER, "tech": "#7c3aed", "financials": "#0891b2", "energy": "#65a30d",
               "consumer": "#db2777", "defensive": "#0d9488"}[q.group]
        v.addWidget(QLabel(f"<span style='color:{dot}'>●</span> {q.name} <span style='color:{MUTED}'>{q.ticker}</span>"))
        pr = QLabel(fmt_price(q)); pr.setStyleSheet(f"font-size: {22 if big else 18}px; font-weight: 700;")
        v.addWidget(pr)
        up = q.change >= 0
        ch = QLabel(f"{'▲' if up else '▼'} {q.change:+.2%} <span style='color:{MUTED}'>· 5d {q.change_5d:+.1%} · 1m {q.change_1m:+.1%}</span>")
        ch.setStyleSheet(f"color: {GREEN if up else RED}; font-weight: 600;")
        v.addWidget(ch); v.addWidget(Spark(q.spark, q.spark[-1] >= q.spark[0]))
        if abs(q.z) >= 2:
            f.setStyleSheet(f"QFrame#card {{ border: 2px solid {GREEN if up else RED}; }}")
            f.setToolTip(f"Unusual move: {q.z:+.1f} standard deviations")
        return f

    # ---------- actions
    def report(self):
        p = self.pulse
        lines = [f"# Market Pulse · {p.asof:%Y-%m-%d}", "",
                 f"**Sentiment:** {p.sentiment}/100 ({p.sentiment_label}) · ▲ {p.gainers} ▼ {p.losers} — {p.unchanged} · "
                 f"average {p.avg_change:+.2%}", "", "## Summary", self.summary_text, "", "## Prices",
                 "| Asset | Price | Day | 5 days | 1 month |", "|---|---|---|---|---|",
                 *[f"| {q.name} ({q.ticker}) | {fmt_price(q)} | {q.change:+.2%} | {q.change_5d:+.1%} | {q.change_1m:+.1%} |"
                   for q in p.quotes],
                 "", f"## Signals: {p.net}", *[f"- **{s.title}** ({s.stance}): {s.detail}" for s in p.signals],
                 "", "## News", *[f"- {n['source']}: [{n['title']}]({n['url']})" for n in p.news],
                 "", "_Data from Yahoo Finance. Not financial advice._"]
        return "\n".join(lines)

    def copy(self):
        if self.pulse:
            QGuiApplication.clipboard().setText(self.report())

    def export(self):
        if not self.pulse:
            return
        path, _ = QFileDialog.getSaveFileName(self, self.t("export"), str(Path.home() / f"Market Pulse {self.pulse.asof:%Y-%m-%d}.md"),
                                              "Markdown (*.md)")
        if path:
            Path(path).write_text(self.report(), encoding="utf-8")

    def present(self, on):
        if on:
            self.showFullScreen(); QApplication.instance().setStyleSheet(QSS + "* { font-size: 16px; }")
        else:
            self.showNormal(); QApplication.instance().setStyleSheet(QSS)
        if self.pulse:
            self.render(self.pulse)

    def open_settings(self):
        if SettingsDialog(self).exec() and self.pulse and get_key():
            self.start_summary()

    def about(self):
        QMessageBox.about(self, "About Market Pulse",
                          f"<b>Market Pulse {__version__}</b><br>by Blue Peak AI &amp; Finance Solutions.<br><br>"
                          "20 markets, a fear–greed score, 7 quantitative signals and a daily summary.<br>"
                          "Data from Yahoo Finance. Not financial advice.")


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Market Pulse"); app.setStyleSheet(QSS)
    if (ASSETS / "icon.png").exists():
        app.setWindowIcon(QIcon(str(ASSETS / "icon.png")))
    w = MainWindow(); w.show()
    snap = os.environ.get("MARKETPULSE_SNAPSHOT")       # used to make the README screenshots
    if snap:
        def shoot():
            if w.pulse is None:
                return QTimer.singleShot(1000, shoot)
            QApplication.processEvents()
            w.body.widget().grab().save(f"{snap}-full.png"); w.grab().save(f"{snap}-window.png"); app.quit()
        QTimer.singleShot(300, w.load); QTimer.singleShot(1500, shoot)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
