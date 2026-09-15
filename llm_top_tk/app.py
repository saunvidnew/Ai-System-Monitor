from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from collections import deque
from tkinter import ttk

from .analyzer import Analyzer
from .collectors import Snapshot, SystemCollector, human_bytes, system_info

BG, PANEL, PANEL2 = "#080d18", "#111a2a", "#172337"
TEXT, MUTED, CYAN, GREEN, AMBER = "#edf4ff", "#8697b2", "#40d9ef", "#42db83", "#f5bd58"


class Sparkline(tk.Canvas):
    def __init__(self, master, color):
        super().__init__(master, height=44, bg=PANEL, highlightthickness=0)
        self.color, self.values = color, deque(maxlen=60)
        self.bind("<Configure>", lambda _: self.draw())

    def add(self, value):
        self.values.append(max(0, min(100, value)))
        self.draw()

    def draw(self):
        self.delete("all")
        if len(self.values) < 2:
            return
        width, height = self.winfo_width(), self.winfo_height()
        points = []
        for i, value in enumerate(self.values):
            points += [i * width / (len(self.values) - 1), height - 3 - value * (height - 6) / 100]
        self.create_line(*points, fill=self.color, width=2, smooth=True)


class MetricCard(tk.Frame):
    def __init__(self, master, title, color):
        super().__init__(master, bg=PANEL, highlightbackground="#23334d", highlightthickness=1)
        tk.Label(self, text=title.upper(), bg=PANEL, fg=MUTED,
                 font=("TkDefaultFont", 9, "bold")).pack(anchor="w", padx=12, pady=(9, 0))
        self.value = tk.Label(self, text="—", bg=PANEL, fg=color,
                              font=("TkDefaultFont", 20, "bold"))
        self.value.pack(anchor="w", padx=12)
        self.detail = tk.Label(self, text="Waiting for data", bg=PANEL, fg=MUTED)
        self.detail.pack(anchor="w", padx=12)
        self.chart = Sparkline(self, color)
        self.chart.pack(fill="x", padx=8, pady=(1, 7))

    def update_metric(self, value, detail, chart_value):
        self.value.configure(text=value)
        self.detail.configure(text=detail)
        self.chart.add(chart_value)


class LLMTopApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LLMTop — AI System Monitor")
        self.geometry("1240x820")
        self.minsize(980, 680)
        self.configure(bg=BG)
        self.collector = SystemCollector()
        self.results = queue.Queue()
        self.interval = tk.IntVar(value=5)
        self.provider = tk.StringVar(value="Local")
        self.model = tk.StringVar(value="llama3.2:3b")
        self.running, self.collecting = True, False
        self.last_analysis = 0.0
        self.alert_history, self.analysis_history = deque(maxlen=30), deque(maxlen=20)
        self._configure_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(100, self._tick)

    def _configure_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, foreground=TEXT,
                        fieldbackground=PANEL, rowheight=27, borderwidth=0)
        style.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, relief="flat")
        style.map("Treeview", background=[("selected", "#23415b")])
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(15, 8))
        style.map("TNotebook.Tab", background=[("selected", PANEL2)], foreground=[("selected", CYAN)])

    def _build(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x", padx=20, pady=(16, 10))
        tk.Label(header, text="LLMTOP", bg=BG, fg=TEXT,
                 font=("TkDefaultFont", 22, "bold")).pack(side="left")
        tk.Label(header, text="  AI SYSTEM MONITOR", bg=BG, fg=CYAN,
                 font=("TkDefaultFont", 11, "bold")).pack(side="left", pady=(7, 0))
        controls = tk.Frame(header, bg=BG)
        controls.pack(side="right")
        tk.Label(controls, text="Analysis", bg=BG, fg=MUTED).pack(side="left", padx=(0, 4))
        provider = ttk.Combobox(controls, textvariable=self.provider,
                                values=("Local", "Ollama", "OpenAI"), width=8, state="readonly")
        provider.pack(side="left", padx=3)
        provider.bind("<<ComboboxSelected>>", self._provider_changed)
        self.model_box = ttk.Combobox(controls, textvariable=self.model, width=17)
        self.model_box.pack(side="left", padx=3)
        tk.Label(controls, text="Refresh", bg=BG, fg=MUTED).pack(side="left", padx=(10, 4))
        ttk.Combobox(controls, textvariable=self.interval, values=(1, 2, 5, 10),
                     width=3, state="readonly").pack(side="left")
        self.pause_button = tk.Button(controls, text="Pause", command=self._toggle,
                                      bg=PANEL2, fg=TEXT, relief="flat", padx=12, pady=5)
        self.pause_button.pack(side="left", padx=(8, 0))

        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=16)
        specs = (("cpu", "CPU", CYAN), ("memory", "Memory", GREEN),
                 ("disk", "Disk", AMBER), ("network", "Network", CYAN))
        self.cards = {key: MetricCard(cards, title, color) for key, title, color in specs}
        for i, card in enumerate(self.cards.values()):
            card.grid(row=0, column=i, sticky="nsew", padx=4)
            cards.grid_columnconfigure(i, weight=1)

        body = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=5, bd=0)
        body.pack(fill="both", expand=True, padx=20, pady=12)
        left, right = tk.Frame(body, bg=BG), tk.Frame(body, bg=BG, width=350)
        body.add(left, stretch="always")
        body.add(right, minsize=320)
        self.tabs = ttk.Notebook(left)
        self.tabs.pack(fill="both", expand=True)
        self.process_tree = self._tree_tab("Processes", ("pid", "name", "user", "cpu", "memory", "status"),
                                           (65, 220, 135, 70, 75, 80))
        self.cpu_tree = self._tree_tab("CPU cores", ("core", "usage"), (100, 180))
        self.disk_tree = self._tree_tab("Disks", ("device", "mount", "used", "free", "total", "percent"),
                                        (150, 150, 100, 100, 100, 80))
        self.gpu_tree = self._tree_tab("GPUs", ("id", "name", "load", "memory", "temperature", "type"),
                                       (50, 220, 85, 170, 100, 80))
        self._panel(right, "SYSTEM", "\n".join(f"{k}: {v}" for k, v in system_info().items()), 6)
        self.analysis_text = self._panel(right, "AI INSIGHTS", "Waiting for enough data…", 9)
        self.alert_text = self._panel(right, "ALERTS", "No active alerts", 8)
        self.status = tk.StringVar(value="Starting…")
        tk.Label(self, textvariable=self.status, bg=BG, fg=MUTED, anchor="w").pack(
            fill="x", padx=22, pady=(0, 10))

    def _tree_tab(self, title, columns, widths):
        frame = tk.Frame(self.tabs, bg=PANEL)
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        scroll = ttk.Scrollbar(frame, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        for column, width in zip(columns, widths):
            tree.heading(column, text=column.replace("_", " ").title(),
                         command=lambda c=column: self._sort(tree, c, False))
            tree.column(column, width=width)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tabs.add(frame, text=title)
        return tree

    @staticmethod
    def _panel(master, title, content, height):
        frame = tk.Frame(master, bg=PANEL, highlightbackground="#23334d", highlightthickness=1)
        frame.pack(fill="both", expand=True, pady=(0, 8))
        tk.Label(frame, text=title, bg=PANEL2, fg=CYAN, anchor="w", padx=10,
                 pady=6, font=("TkDefaultFont", 9, "bold")).pack(fill="x")
        box = tk.Text(frame, height=height, bg=PANEL, fg=TEXT, relief="flat",
                      wrap="word", padx=10, pady=8)
        box.insert("1.0", content)
        box.configure(state="disabled")
        box.pack(fill="both", expand=True)
        return box

    def _tick(self):
        try:
            while True:
                self._render(self.results.get_nowait())
                self.collecting = False
        except queue.Empty:
            pass
        if self.running and not self.collecting:
            self.collecting = True
            threading.Thread(target=self._collect, daemon=True).start()
        self.after(max(500, self.interval.get() * 1000), self._tick)

    def _collect(self):
        try:
            self.results.put(self.collector.collect())
        except Exception as exc:
            self.results.put(Snapshot(time.time(), error=str(exc)))

    def _render(self, snap):
        detail = f"{len(snap.per_cpu)} cores"
        if snap.cpu_freq:
            detail += f" • {snap.cpu_freq:.0f} MHz"
        self.cards["cpu"].update_metric(f"{snap.cpu:.0f}%", detail, snap.cpu)
        self.cards["memory"].update_metric(
            f"{snap.memory:.0f}%",
            f"{human_bytes(snap.memory_used)} / {human_bytes(snap.memory_total)} • swap {snap.swap:.0f}%",
            snap.memory)
        self.cards["disk"].update_metric(f"{snap.disk:.0f}%", f"{len(snap.disks)} mounted volumes", snap.disk)
        self.cards["network"].update_metric(
            f"↓ {human_bytes(snap.rx_rate)}/s", f"↑ {human_bytes(snap.tx_rate)}/s",
            min(100, max(snap.rx_rate, snap.tx_rate) / 1024 / 1024 * 10))
        self._rows(self.process_tree, [
            {**p, "cpu": f"{p['cpu']:.1f}%", "memory": f"{p['memory']:.1f}%"} for p in snap.processes])
        self._rows(self.cpu_tree, [{"core": i, "usage": f"{value:.1f}%"}
                                   for i, value in enumerate(snap.per_cpu)])
        self._rows(self.disk_tree, [
            {**d, "used": human_bytes(d["used"]), "free": human_bytes(d["free"]),
             "total": human_bytes(d["total"]), "percent": f"{d['percent']:.0f}%"} for d in snap.disks])
        self._rows(self.gpu_tree, [
            {**g, "load": f"{g['load']:.0f}%" if g["load"] is not None else "N/A",
             "temperature": f"{g['temperature']:.0f}°C" if g["temperature"] is not None else "N/A"}
            for g in snap.gpus])
        for alert in snap.alerts:
            message = f"{time.strftime('%H:%M:%S')}  {alert['component']}: {alert['message']}"
            if not self.alert_history or self.alert_history[-1] != message:
                self.alert_history.append(message)
        self._set_text(self.alert_text, "\n".join(reversed(self.alert_history))
                       if self.alert_history else "No active alerts")
        if time.monotonic() - self.last_analysis >= max(5, self.interval.get() * 2):
            self.last_analysis = time.monotonic()
            threading.Thread(target=self._analyze, args=(snap,), daemon=True).start()
        self.status.set(time.strftime("Updated %H:%M:%S") + (f" • {snap.error}" if snap.error else ""))

    def _analyze(self, snap):
        result = Analyzer(self.provider.get(), self.model.get()).analyze(snap)
        self.analysis_history.append(f"{time.strftime('%H:%M:%S')}  {result}")
        self.after(0, lambda: self._set_text(
            self.analysis_text, "\n\n".join(reversed(self.analysis_history))))

    @staticmethod
    def _rows(tree, rows):
        tree.delete(*tree.get_children())
        for row in rows:
            tree.insert("", "end", values=[row.get(column, "—") for column in tree["columns"]])

    @staticmethod
    def _set_text(box, text):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    @staticmethod
    def _sort(tree, column, reverse):
        def key(item):
            value = tree.set(item, column).replace("%", "")
            try:
                return 0, float(value)
            except ValueError:
                return 1, value.lower()
        for position, item in enumerate(sorted(tree.get_children(), key=key, reverse=reverse)):
            tree.move(item, "", position)
        tree.heading(column, command=lambda: LLMTopApp._sort(tree, column, not reverse))

    def _provider_changed(self, _event=None):
        if self.provider.get() == "Ollama":
            models = Analyzer.ollama_models()
            self.model_box["values"] = models
            if models:
                self.model.set(models[0])
        elif self.provider.get() == "OpenAI":
            self.model.set("gpt-4o-mini")

    def _toggle(self):
        self.running = not self.running
        self.pause_button.configure(text="Pause" if self.running else "Resume")
        if not self.running:
            self.status.set("Paused")

    def _close(self):
        self.running = False
        self.destroy()


def main():
    LLMTopApp().mainloop()
