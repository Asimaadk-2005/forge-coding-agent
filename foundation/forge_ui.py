"""Forge reviewed UI components v1. Business logic is generated separately.

This is a reusable scene/widget library, not the Space Fractions game controller.
"""
import math
import os
import re
import time
import tkinter as tk
from fractions import Fraction
from pathlib import Path

BG = "#080e20"
PANEL = "#101d36"
INK = "#edf5ff"
MUTED = "#9eb2cf"
CYAN = "#67e8f9"
VIOLET = "#9b8afb"


class GameShell:
    def __init__(self, root, data_dir=None):
        self.root = root
        self.root.forge_app = self
        self.root.title("Space Fractions · Mission Control")
        w, h = min(1080, root.winfo_screenwidth()-80), min(680, root.winfo_screenheight()-100)
        self.root.geometry(f"{w}x{h}")
        self.root.minsize(min(w, 860), min(h, 540))
        self.root.configure(bg=BG)
        # Each generated project receives a unique namespace from Forge.
        namespace = "__FORGE_PROJECT_NAMESPACE__"
        self.data_dir = Path(data_dir) if data_dir else Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "SpaceFractions" / namespace
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.canvas = tk.Canvas(root, bg=BG, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.panel = tk.Frame(root, bg=PANEL, padx=22, pady=18)
        self.frame = self.panel
        self.widgets = {}
        self._overlays = []
        self._page_jobs = []
        self.screen = ""
        self._title, self._subtitle, self._prompt = "", "", ""
        self._index, self._total, self._correct = 0, 10, 0
        self._effect = None
        self._started = time.monotonic()
        self._after = None
        self.canvas.bind("<Configure>", lambda e: self._paint())
        root.bind("<Return>", lambda e: self._invoke("check"))
        root.bind("<Escape>", lambda e: self._invoke("menu"))
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._animate()

    def _invoke(self, role):
        control = self.widgets.get(role)
        if isinstance(control, tk.Button) and str(control.cget("state")) != "disabled":
            control.invoke()

    def close(self):
        for job in self._page_jobs:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._page_jobs.clear()
        if self._after:
            try:
                self.root.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        self.root.destroy()

    def page(self, name, title, subtitle=""):
        for job in self._page_jobs:
            try:
                self.root.after_cancel(job)
            except tk.TclError:
                pass
        self._page_jobs.clear()
        for widget in self._overlays:
            widget.destroy()
        self._overlays.clear()
        for widget in self.panel.winfo_children():
            widget.destroy()
        self.widgets.clear()
        self.screen, self._title, self._subtitle = name, title, subtitle
        self._prompt = ""
        self.panel.place(relx=.655, rely=.15, relwidth=.32, relheight=.79)
        tk.Label(self.panel, text="FLIGHT CONSOLE" if name == "play" else "MISSION CONTROL",
                 fg=CYAN, bg=PANEL, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 14))
        self._paint()

    def later(self, milliseconds, callback):
        """Page-owned scheduling; navigation cancels obsolete callbacks."""
        job = self.root.after(milliseconds, callback)
        self._page_jobs.append(job)
        return job

    def label(self, role, text):
        if role == "instructions":
            widget = tk.Label(self.root, text=text, bg=PANEL, fg=INK, font=("Segoe UI", 11),
                justify="left", anchor="nw", padx=18, pady=14, wraplength=480)
            widget.place(relx=.045, rely=.27, relwidth=.565, relheight=.50)
            self._overlays.append(widget)
            self.widgets[role] = widget
            return widget
        widget = tk.Label(self.panel, text=text, bg=PANEL, fg=INK,
            font=("Segoe UI", 12, "bold" if role in {"score", "summary", "feedback"} else "normal"),
            justify="left", anchor="w", wraplength=255)
        widget.pack(fill="x", pady=5)
        self.widgets[role] = widget
        if role == 'question':
            children = self.panel.winfo_children()
            if len(children) > 1 and children[1] is not widget:
                widget.pack(before=children[1], fill='x', pady=5)
            self._prompt = str(text)
            self._paint()
            def sync_question(event=None):
                if self.screen == 'play' and widget.winfo_exists():
                    prompt = widget.cget('text')
                    if prompt != self._prompt:
                        self._prompt = prompt
                        self._paint()
            widget.bind('<Configure>', sync_question, add='+')
        return widget

    def entry(self, role):
        captions = {"answer": "ANSWER · e.g. 3/4, 1/2 or 1", "prompt": "QUESTION", "correct_answer": "CORRECT ANSWER", "explanation": "EXPLANATION"}
        tk.Label(self.panel, text=captions.get(role, role.upper()), bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(7, 3))
        widget = tk.Entry(self.panel, bg="#192b49", fg=INK, insertbackground=CYAN,
            relief="flat", font=("Segoe UI", 16 if role == "answer" else 13),
            justify="center" if role == "answer" else "left", highlightthickness=1, highlightbackground="#355174")
        widget.pack(fill="x", ipady=6, pady=(0, 5))
        self.widgets[role] = widget
        return widget

    def button(self, role, text, command, primary=False):
        widget = tk.Button(self.panel, text=text, command=command, bg=CYAN if primary else "#223654",
            fg=BG if primary else INK, activebackground="#8da8ff", activeforeground=BG,
            font=("Segoe UI", 11, "bold"), relief="flat", bd=0, cursor="hand2", pady=7)
        widget.pack(fill="x", pady=4)
        self.widgets[role] = widget
        return widget

    def listing(self, role):
        widget = tk.Listbox(self.root, bg="#101d36", fg=INK, selectbackground="#375a80",
            font=("Segoe UI", 12), relief="flat", activestyle="none", exportselection=False)
        widget.place(relx=.045, rely=.27, relwidth=.565, relheight=.50)
        # List belongs to the current page, even though placed over the scene.
        self._overlays.append(widget)
        self.widgets[role] = widget
        return widget

    def draw_question(self, prompt):
        self._prompt = str(prompt)
        widget = self.widgets.get('question')
        if widget is None or not widget.winfo_exists():
            self.label('question', str(prompt))
        else:
            widget.configure(text=str(prompt))
        self._paint()

    def mission(self, index, total, correct):
        self._index, self._total, self._correct = index, max(1, total), correct
        self._paint()

    def feedback_effect(self, correct):
        self._effect = (time.monotonic(), correct)

    def _animate(self):
        try:
            self._paint()
            self._after = self.root.after(50, self._animate)
        except tk.TclError:
            self._after = None

    def _paint(self):
        c = self.canvas
        question = self.widgets.get('question')
        if self.screen == 'play' and question is not None and question.winfo_exists():
            self._prompt = str(question.cget('text'))
        w, h = c.winfo_width(), c.winfo_height()
        if w < 10 or h < 10:
            return
        c.delete("scene")
        def oval(*args, **kw):
            return c.create_oval(*args, tags="scene", **kw)
        def text(*args, **kw):
            return c.create_text(*args, tags="scene", **kw)
        t = time.monotonic()-self._started
        for i in range(74):
            x, y = (i*131.7-t*(3+i%3)) % w, (i*71.3) % h
            r = 1 if i % 5 else 1.8
            oval(x, y, x+r, y+r, fill="#506d96" if i%3 else "#bedcf4", outline="")
        # Layered planet and orbit. Palette is shared across every screen.
        px, py, radius = .46*w, .32*h, .13*h
        oval(px-radius-18, py-radius+18, px+radius+18, py+radius-18, outline="#355578", width=2)
        oval(px-radius, py-radius, px+radius, py+radius, fill="#273a72", outline="#526dac", width=2)
        oval(px-radius*.7, py-radius*.8, px+radius*.35, py+radius*.3, fill="#354f8c", outline="")
        text(.045*w, .055*h, text="ORBIT ACADEMY  /  FRACTIONS", fill=CYAN, anchor="w", font=("Segoe UI", 10, "bold"))
        text(.045*w, .13*h, text=self._title or "Space Fractions", fill=INK, anchor="w", font=("Segoe UI", 27, "bold"), width=.59*w)
        text(.045*w, .205*h, text=self._subtitle, fill=MUTED, anchor="w", font=("Segoe UI", 11), width=.55*w)
        if self.screen == "play":
            text(.07*w, .32*h, text="DECODE THE FLIGHT PATH", fill=CYAN, anchor="w", font=("Segoe UI", 10, "bold"))
            text(.07*w, .42*h, text=self._prompt, fill=INK, anchor="w", font=("Segoe UI", 25, "bold"), width=.51*w)
            values = re.findall(r"(?<![\d/])-?\d+/\d+", self._prompt)[:2]
            for row, value in enumerate(values):
                try:
                    fraction = abs(Fraction(value))
                    denom = min(fraction.denominator, 16)
                    whole, remainder = divmod(fraction.numerator, fraction.denominator)
                    x, y, width = .07*w, (.53+row*.085)*h, .47*w
                    for n in range(denom):
                        c.create_rectangle(x+n*width/denom, y, x+(n+1)*width/denom-3, y+24,
                            fill=CYAN if n/denom < remainder/fraction.denominator else "#1b2c48", outline="", tags="scene")
                    caption = f"{value} = {whole} whole + {remainder}/{fraction.denominator}" if whole else value+"  •  fraction segment"
                    text(x, y+35, text=caption, fill=MUTED, anchor="w", font=("Segoe UI", 9))
                except (ValueError, ZeroDivisionError):
                    pass
        else:
            text(.07*w, .48*h, text="Explore. Solve.\nPower your next orbit.", fill=INK,
                anchor="w", font=("Segoe UI", 23, "bold"), width=.48*w)
        y = .84*h
        c.create_line(.07*w, y, .58*w, y, fill="#2d4263", width=2, tags="scene")
        for n in range(10):
            x = .07*w+n*.51*w/9
            oval(x-5, y-5, x+5, y+5, fill=CYAN if self.screen=="play" and n < self._index else "#334b6c", outline="")
        rx = (.07+.51*min(1, self._index/self._total))*w if self.screen=="play" else .23*w
        ry = y-22+math.sin(t*2)*3
        c.create_polygon(rx-18, ry+10, rx-5, ry-22, rx+9, ry+10, fill=INK, outline=CYAN, tags="scene")
        c.create_polygon(rx-10, ry+12, rx-3, ry+26+math.sin(t*13)*4, rx+4, ry+12, fill="#ffb86c", tags="scene")
        text(.07*w, .94*h, text="ESC · Mission menu     ENTER · Check answer", fill=MUTED, anchor="w", font=("Segoe UI", 9))
        if self._effect and time.monotonic()-self._effect[0] < 1:
            age = time.monotonic()-self._effect[0]
            for n in range(12):
                a = n*math.pi/6
                x, yy = rx+math.cos(a)*age*130, ry+math.sin(a)*age*100
                oval(x-3, yy-3, x+3, yy+3, fill=CYAN if self._effect[1] else "#ff8b9a", outline="")
