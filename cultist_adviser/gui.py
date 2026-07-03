"""Floating advisor window: watches the save file and shows prioritized suggestions.

Run with:  python -m cultist_adviser
Read-only — never touches the game window; you play, it advises.
Card/verb names come from the game's own localization (中文/English toggle).
"""
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from .config import SAVE_PATH, SAVE_POLL_INTERVAL
from .save_parser import parse_save
from . import lexicon
from .advisor import advise, Advice, ALERT_VERBS
from .knowledge import obtain_ways
from .recorder import SessionRecorder
from .review import ReviewWindow

POLL_MS = int(SAVE_POLL_INTERVAL * 1000)
REDRAW_MS = 1000  # countdown re-render

# The save file is our only game-time signal: a running verb writes a save when
# it completes, so the smallest verb timer is a deadline for the next save
# (the time verb keeps it <= 60s). If that deadline passes with no new save,
# the game must be paused — freeze countdowns at the save's own values.
PAUSE_SLACK = 5.0  # seconds past the deadline before we assume a pause

UI = {
    "title": ("密教军师", "Cultist Advisor"),
    "topmost": ("置顶", "On top"),
    "waiting": ("等待存档…", "Waiting for save…"),
    "no_save": ("找不到存档：", "Save not found: "),
    "parse_fail": ("存档解析失败：", "Failed to parse save: "),
    "updated": ("更新于", "updated"),
    "suggestions": ("操作建议", "Suggestions"),
    "none": ("暂无建议。", "Nothing to suggest."),
    "verbs": ("进行中的行动", "Actions in progress"),
    "verb": ("行动", "Action"),
    "recipe": ("配方", "Recipe"),
    "left": ("剩余", "Left"),
    "resources": ("场上资源（多张同名卡可展开看各自倒计时）",
                  "Table resources (expand rows for per-card timers)"),
    "card": ("卡牌", "Card"),
    "qty": ("数量", "Qty"),
    "expiry": ("最快过期", "Expires"),
    "permanent": ("永久", "—"),
    "nth": ("第 {} 张", "#{}"),
    "review": ("复盘", "Review"),
    "resources_hint": ("场上资源（双击卡牌查看获得方式）",
                       "Table resources (double-click a card for how to obtain it)"),
    "obtain_title": ("获得方式：{}", "How to obtain: {}"),
    "obtain_none": ("没有已知配方直接产出这张卡。", "No known recipe produces this card."),
    "paused": ("已暂停？计时已冻结", "Paused? timers frozen"),
}


def _t(key: str) -> str:
    zh, en = UI[key]
    return zh if lexicon.get_language() == "zh" else en


def _fmt_secs(secs: float) -> str:
    if secs <= 0:
        return "—"
    m, s = divmod(int(secs), 60)
    return f"{m}:{s:02d}" if m else f"{s}s"


class AdvisorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.state = None
        self.advice: Advice | None = None
        self.save_mtime = 0.0
        self.parsed_at = 0.0
        self.parsed_at_str = ""
        self.save_deadline = 0.0  # next guaranteed save, seconds after parsed_at
        self.was_paused = False
        self.recorder = SessionRecorder()

        root.geometry("470x660")
        root.attributes("-topmost", True)

        top = ttk.Frame(root, padding=(8, 6))
        top.pack(fill="x")
        self.status_var = tk.StringVar()
        ttk.Label(top, textvariable=self.status_var).pack(side="left")

        self.topmost_var = tk.BooleanVar(value=True)
        self.topmost_btn = ttk.Checkbutton(
            top, variable=self.topmost_var,
            command=lambda: root.attributes("-topmost", self.topmost_var.get()))
        self.topmost_btn.pack(side="right")
        self.review_btn = ttk.Button(top, command=self._open_review)
        self.review_btn.pack(side="right", padx=(0, 8))
        self.lang_var = tk.StringVar(value="中文")
        lang_box = ttk.Combobox(top, textvariable=self.lang_var, width=8,
                                state="readonly", values=("中文", "English"))
        lang_box.pack(side="right", padx=(0, 8))
        lang_box.bind("<<ComboboxSelected>>", self._switch_language)

        nb = ttk.Panedwindow(root, orient="vertical")
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.sug_frame = ttk.Labelframe(nb, padding=4)
        self.sug_text = tk.Text(self.sug_frame, wrap="word", height=10, state="disabled",
                                font=("Microsoft YaHei UI", 10), relief="flat")
        self.sug_text.tag_configure("urgent", foreground="#c62828",
                                    font=("Microsoft YaHei UI", 10, "bold"))
        self.sug_text.tag_configure("title", font=("Microsoft YaHei UI", 10, "bold"))
        self.sug_text.tag_configure("detail", foreground="#666666",
                                    font=("Microsoft YaHei UI", 9))
        self.sug_text.pack(fill="both", expand=True)
        nb.add(self.sug_frame, weight=3)

        self.verb_frame = ttk.Labelframe(nb, padding=4)
        self.verb_tree = ttk.Treeview(self.verb_frame, columns=("verb", "recipe", "left"),
                                      show="headings", height=4)
        self.verb_tree.column("verb", width=120)
        self.verb_tree.column("recipe", width=220)
        self.verb_tree.column("left", width=60, anchor="e")
        self.verb_tree.tag_configure("danger", foreground="#c62828")
        self.verb_tree.pack(fill="both", expand=True)
        nb.add(self.verb_frame, weight=2)

        self.res_frame = ttk.Labelframe(nb, padding=4)
        self.res_tree = ttk.Treeview(self.res_frame, columns=("qty", "life"),
                                     show="tree headings", height=8)
        self.res_tree.column("#0", width=240)
        self.res_tree.column("qty", width=50, anchor="e")
        self.res_tree.column("life", width=80, anchor="e")
        self.res_tree.tag_configure("expiring", foreground="#c62828")
        self.res_tree.pack(fill="both", expand=True)
        self.res_tree.bind("<Double-1>", self._show_obtain_ways)
        self._res_items: dict[str, str] = {}  # tree item id -> entity id
        nb.add(self.res_frame, weight=3)

        self._apply_language_chrome()
        self.status_var.set(_t("waiting"))
        self._poll()
        self._redraw_timers()

    # --- language ---

    def _switch_language(self, _event=None):
        lexicon.set_language("zh" if self.lang_var.get() == "中文" else "en")
        self._apply_language_chrome()
        if self.state is not None:
            self.advice = advise(self.state)  # re-run rules so suggestion text switches too
            self._set_status()
            self._render()

    def _open_review(self):
        ReviewWindow(self.root, self.recorder.path)

    def _show_obtain_ways(self, event):
        item = self.res_tree.identify_row(event.y)
        eid = self._res_items.get(item) or self._res_items.get(self.res_tree.parent(item))
        if not eid:
            return
        available = {r.entity_id for r in self.advice.resources} if self.advice else None
        ways = obtain_ways(eid, limit=8, available=available)
        win = tk.Toplevel(self.root)
        win.title(_t("obtain_title").format(lexicon.display_name(eid)))
        win.geometry("560x260")
        win.attributes("-topmost", self.topmost_var.get())
        text = tk.Text(win, wrap="word", font=("Microsoft YaHei UI", 10), relief="flat")
        if ways:
            for w in ways:
                text.insert("end", f"• {w}\n")
        else:
            text.insert("end", _t("obtain_none"))
        text.configure(state="disabled")
        text.pack(fill="both", expand=True, padx=8, pady=8)

    def _apply_language_chrome(self):
        self.root.title(_t("title"))
        self.topmost_btn.configure(text=_t("topmost"))
        self.review_btn.configure(text=_t("review"))
        self.sug_frame.configure(text=_t("suggestions"))
        self.verb_frame.configure(text=_t("verbs"))
        self.res_frame.configure(text=_t("resources_hint"))
        self.verb_tree.heading("verb", text=_t("verb"))
        self.verb_tree.heading("recipe", text=_t("recipe"))
        self.verb_tree.heading("left", text=_t("left"))
        self.res_tree.heading("#0", text=_t("card"))
        self.res_tree.heading("qty", text=_t("qty"))
        self.res_tree.heading("life", text=_t("expiry"))

    def _set_status(self):
        if self.advice:
            text = (f"{self.advice.character or '?'} · {lexicon.display_name(self.advice.legacy)}"
                    f" · {_t('updated')} {self.parsed_at_str}")
            if self._likely_paused():
                text += f" · {_t('paused')}"
            self.status_var.set(text)

    # --- data ---

    def _poll(self):
        try:
            mtime = Path(SAVE_PATH).stat().st_mtime
        except FileNotFoundError:
            self.status_var.set(_t("no_save") + str(SAVE_PATH))
            self.root.after(POLL_MS, self._poll)
            return
        if mtime != self.save_mtime:
            self.save_mtime = mtime
            try:
                self.state = parse_save(str(SAVE_PATH))
                self.advice = advise(self.state)
                self.parsed_at = time.time()
                self.parsed_at_str = time.strftime("%H:%M:%S")
                running = [v.time_remaining for v in self.advice.verbs
                           if v.time_remaining > 0]
                self.save_deadline = min(running) if running else 0.0
                self.was_paused = False
                try:
                    self.recorder.record(self.advice)
                except OSError:
                    pass  # recording must never break the advisor
                self._set_status()
                self._render()
            except Exception as e:
                self.status_var.set(_t("parse_fail") + str(e))
        self.root.after(POLL_MS, self._poll)

    def _likely_paused(self) -> bool:
        """A running verb should have completed and written a save by now, but
        none arrived — the game is paused (or closed). Detection lags by up to
        the deadline (<=60s thanks to the time verb) plus slack."""
        return bool(self.save_deadline) and self.parsed_at > 0 \
            and time.time() - self.parsed_at > self.save_deadline + PAUSE_SLACK

    def _elapsed(self) -> float:
        # Wall-clock drift since the save was written. While paused the drift
        # is fiction, so fall back to the save's own values (drift 0).
        if not self.parsed_at or self._likely_paused():
            return 0.0
        return time.time() - self.parsed_at

    # --- rendering ---

    def _render(self):
        if not self.advice:
            return
        self.sug_text.configure(state="normal")
        self.sug_text.delete("1.0", "end")
        if not self.advice.suggestions:
            self.sug_text.insert("end", _t("none") + "\n", "detail")
        for i, s in enumerate(self.advice.suggestions, 1):
            tag = "urgent" if s.urgent else "title"
            self.sug_text.insert("end", f"{i}. {s.title}\n", tag)
            if s.detail:
                self.sug_text.insert("end", f"    {s.detail}\n", "detail")
        self.sug_text.configure(state="disabled")
        self._redraw_timers(reschedule=False)

    def _redraw_timers(self, reschedule: bool = True):
        if self.advice:
            paused = self._likely_paused()
            if paused != self.was_paused:
                self.was_paused = paused
                self._set_status()
            drift = self._elapsed()

            self.verb_tree.delete(*self.verb_tree.get_children())
            for v in self.advice.verbs:
                left = max(0.0, v.time_remaining - drift) if v.time_remaining > 0 else 0.0
                tags = ("danger",) if v.verb_id in ALERT_VERBS else ()
                name = lexicon.display_name(v.verb_id)
                if name == v.verb_id and v.recipe_id:  # season verbs have no label of their own
                    name = lexicon.recipe_name(v.recipe_id)
                self.verb_tree.insert("", "end", tags=tags, values=(
                    name,
                    lexicon.recipe_name(v.recipe_id) if v.recipe_id else "—",
                    _fmt_secs(left)))

            self.res_tree.delete(*self.res_tree.get_children())
            self._res_items.clear()
            for r in self.advice.resources:
                lives = [max(0.0, lv - drift) for lv in r.lifetimes]
                soonest = lives[0] if lives else 0.0
                tags = ("expiring",) if lives and soonest <= 30 else ()
                parent = self.res_tree.insert(
                    "", "end", tags=tags, open=bool(lives) and soonest <= 60,
                    text=lexicon.display_name(r.entity_id),
                    values=(r.quantity, _fmt_secs(soonest) if lives else _t("permanent")))
                self._res_items[parent] = r.entity_id
                if len(lives) > 1:
                    for i, lv in enumerate(lives, 1):
                        child_tags = ("expiring",) if lv <= 30 else ()
                        self.res_tree.insert(parent, "end", tags=child_tags,
                                             text="  " + _t("nth").format(i),
                                             values=("", _fmt_secs(lv)))
        if reschedule:
            self.root.after(REDRAW_MS, self._redraw_timers)


def main():
    root = tk.Tk()
    AdvisorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
