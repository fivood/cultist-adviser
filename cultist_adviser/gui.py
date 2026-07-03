"""Floating advisor window: watches the save file and shows prioritized suggestions.

Run with:  python -m cultist_adviser
Read-only — never touches the game window; you play, it advises.
Card/verb names come from the game's own localization (中文/English toggle).
"""
import json
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from .config import SAVE_PATH, SAVE_POLL_INTERVAL, PROJECT_DIR
from .save_parser import parse_save
from . import lexicon
from .advisor import advise, Advice, ALERT_VERBS, SPOILER_GUIDE
from .knowledge import obtain_ways, element_aspects

SETTINGS_PATH = PROJECT_DIR / "settings.json"


def _load_settings() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_settings(settings: dict):
    try:
        SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False),
                                 encoding="utf-8")
    except Exception:
        pass  # settings must never break the advisor
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
    "sec_urgent": ("⚠ 紧急", "⚠ URGENT"),
    "sec_advice": ("● 建议", "● Advice"),
    "sec_info": ("○ 情报", "○ Info"),
    "filter": ("筛选", "Filter"),
    "timed_only": ("只看倒计时", "Timed only"),
    "spoiler_names": (("守密人", "顾问", "全知"), ("Keeper", "Adviser", "Omniscient")),
    "grp_threats": ("威胁", "Threats"),
    "grp_core": ("资源与属性", "Resources & abilities"),
    "grp_advancement": ("碎片与课程", "Fragments & lessons"),
    "grp_lore": ("秘传", "Lore"),
    "grp_influence": ("影响", "Influences"),
    "grp_books": ("书籍", "Books"),
    "grp_people": ("人员", "People"),
    "grp_places": ("地点", "Places"),
    "grp_misc": ("其他", "Other"),
}

# Suggestions below this priority are background information, not calls to act.
INFO_PRIORITY = 40

# ------------------------------------------------- resource categorization ---
# Late-game tables hold dozens of cards; group them into collapsible sections.
THREAT_IDS = {"dread", "fascination", "restlessness", "affliction", "hunger",
              "decrepitude", "injury", "notoriety", "mystique",
              "evidence", "evidenceb"}
GROUP_ORDER = ("threats", "core", "advancement", "lore", "influence",
               "books", "people", "places", "misc")
GROUP_DEFAULT_OPEN = {"threats", "core", "advancement"}


def _categorize(entity_id: str) -> str:
    asp = element_aspects(entity_id)
    if entity_id in THREAT_IDS or asp.get("reputation") \
            or asp.get("evidencelevel") or asp.get("hunter"):
        return "threats"
    if asp.get("ability") or entity_id in ("funds", "fatigue"):
        return "core"
    if asp.get("advancement") or entity_id.startswith("lesson"):
        return "advancement"
    if asp.get("lore"):
        return "lore"
    if asp.get("text"):
        return "books"
    if any(asp.get(a) for a in ("follower", "acquaintance", "hireling",
                                "prisoner", "mortal")):
        return "people"
    if asp.get("location") or asp.get("vault") or asp.get("way"):
        return "places"
    if asp.get("influence"):
        return "influence"
    return "misc"


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
        self.settings = _load_settings()
        lexicon.set_language(self.settings.get("language", "zh"))
        self.spoiler_level = int(self.settings.get("spoiler", SPOILER_GUIDE))

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
        self.lang_var = tk.StringVar(
            value="中文" if lexicon.get_language() == "zh" else "English")
        lang_box = ttk.Combobox(top, textvariable=self.lang_var, width=8,
                                state="readonly", values=("中文", "English"))
        lang_box.pack(side="right", padx=(0, 8))
        lang_box.bind("<<ComboboxSelected>>", self._switch_language)
        self.spoiler_var = tk.StringVar()
        self.spoiler_box = ttk.Combobox(top, textvariable=self.spoiler_var, width=7,
                                        state="readonly")
        self.spoiler_box.pack(side="right", padx=(0, 8))
        self.spoiler_box.bind("<<ComboboxSelected>>", self._switch_spoiler)

        nb = ttk.Panedwindow(root, orient="vertical")
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.sug_frame = ttk.Labelframe(nb, padding=4)
        self.sug_text = tk.Text(self.sug_frame, wrap="word", height=10, state="disabled",
                                font=("Microsoft YaHei UI", 10), relief="flat")
        self.sug_text.tag_configure("header", foreground="#888888",
                                    font=("Microsoft YaHei UI", 8, "bold"),
                                    spacing1=6, spacing3=2)
        self.sug_text.tag_configure("urgent", foreground="#c62828",
                                    background="#fdecea",
                                    font=("Microsoft YaHei UI", 10, "bold"))
        self.sug_text.tag_configure("urgent_detail", foreground="#8c4a42",
                                    background="#fdecea",
                                    font=("Microsoft YaHei UI", 9))
        self.sug_text.tag_configure("title", font=("Microsoft YaHei UI", 10, "bold"))
        self.sug_text.tag_configure("detail", foreground="#666666",
                                    font=("Microsoft YaHei UI", 9))
        self.sug_text.tag_configure("info", foreground="#999999",
                                    font=("Microsoft YaHei UI", 9))
        self.sug_text.tag_configure("info_detail", foreground="#aaaaaa",
                                    font=("Microsoft YaHei UI", 8))
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
        bar = ttk.Frame(self.res_frame)
        bar.pack(fill="x", pady=(0, 3))
        self.filter_label = ttk.Label(bar)
        self.filter_label.pack(side="left")
        self.filter_var = tk.StringVar()
        ttk.Entry(bar, textvariable=self.filter_var, width=16).pack(side="left", padx=4)
        self.timed_only = tk.BooleanVar(value=False)
        self.timed_btn = ttk.Checkbutton(bar, variable=self.timed_only)
        self.timed_btn.pack(side="right")
        self.res_tree = ttk.Treeview(self.res_frame, columns=("qty", "life"),
                                     show="tree headings", height=8)
        self.res_tree.column("#0", width=240)
        self.res_tree.column("qty", width=50, anchor="e")
        self.res_tree.column("life", width=80, anchor="e")
        self.res_tree.tag_configure("expiring", foreground="#c62828")
        self.res_tree.tag_configure("group", font=("Microsoft YaHei UI", 9, "bold"))
        self.res_tree.pack(fill="both", expand=True)
        self.res_tree.bind("<Double-1>", self._show_obtain_ways)
        self._res_items: dict[str, str] = {}  # tree item id -> entity id
        self._group_keys: dict[str, str] = {}  # tree item id -> group key
        self._grp_open: dict[str, bool] = {}   # group key -> user's open state
        nb.add(self.res_frame, weight=3)

        self._apply_language_chrome()
        self.status_var.set(_t("waiting"))
        self._poll()
        self._redraw_timers()

    # --- language ---

    def _switch_language(self, _event=None):
        lexicon.set_language("zh" if self.lang_var.get() == "中文" else "en")
        self.settings["language"] = lexicon.get_language()
        _save_settings(self.settings)
        self._apply_language_chrome()
        self._re_advise()

    def _switch_spoiler(self, _event=None):
        names = _t("spoiler_names")
        if self.spoiler_var.get() in names:
            self.spoiler_level = names.index(self.spoiler_var.get())
            self.settings["spoiler"] = self.spoiler_level
            _save_settings(self.settings)
            self._re_advise()

    def _re_advise(self):
        if self.state is not None:
            self.advice = advise(self.state, self.spoiler_level)
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
        self.filter_label.configure(text=_t("filter"))
        self.timed_btn.configure(text=_t("timed_only"))
        names = _t("spoiler_names")
        self.spoiler_box.configure(values=names)
        self.spoiler_var.set(names[self.spoiler_level])
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
                self.advice = advise(self.state, self.spoiler_level)
                self.parsed_at = time.time()
                self.parsed_at_str = time.strftime("%H:%M:%S")
                running = [v.time_remaining for v in self.advice.verbs
                           if v.time_remaining > 0]
                self.save_deadline = min(running) if running else 0.0
                self.was_paused = False
                try:
                    self.recorder.record(self.advice, self.state)
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
        urgent = [s for s in self.advice.suggestions if s.urgent]
        advice = [s for s in self.advice.suggestions
                  if not s.urgent and s.priority >= INFO_PRIORITY]
        info = [s for s in self.advice.suggestions
                if not s.urgent and s.priority < INFO_PRIORITY]
        for header, title_tag, detail_tag, items in (
                ("sec_urgent", "urgent", "urgent_detail", urgent),
                ("sec_advice", "title", "detail", advice),
                ("sec_info", "info", "info_detail", info)):
            if not items:
                continue
            self.sug_text.insert("end", _t(header) + "\n", "header")
            for s in items:
                self.sug_text.insert("end", f"{s.title}\n", title_tag)
                if s.detail:
                    self.sug_text.insert("end", f"    {s.detail}\n", detail_tag)
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

            self._render_resources(drift)
        if reschedule:
            self.root.after(REDRAW_MS, self._redraw_timers)

    def _render_resources(self, drift: float):
        # Remember the user's group folding before the rebuild wipes it.
        for item in self.res_tree.get_children():
            key = self._group_keys.get(item)
            if key:
                self._grp_open[key] = bool(self.res_tree.item(item, "open"))
        self.res_tree.delete(*self.res_tree.get_children())
        self._res_items.clear()
        self._group_keys.clear()

        query = self.filter_var.get().strip().lower()
        groups: dict[str, list] = {}
        for r in self.advice.resources:
            lives = [max(0.0, lv - drift) for lv in r.lifetimes]
            if self.timed_only.get() and not lives:
                continue
            name = lexicon.display_name(r.entity_id)
            if query and query not in name.lower() and query not in r.entity_id.lower():
                continue
            groups.setdefault(_categorize(r.entity_id), []).append((r, name, lives))

        for key in GROUP_ORDER:
            rows = groups.get(key)
            if not rows:
                continue
            rows.sort(key=lambda x: (min(x[2]) if x[2] else float("inf"), x[1]))
            total = sum(r.quantity for r, _, _ in rows)
            grp_soonest = min((min(l) for _, _, l in rows if l), default=0.0)
            gtags = ("group", "expiring") if 0 < grp_soonest <= 30 else ("group",)
            gitem = self.res_tree.insert(
                "", "end", tags=gtags,
                open=self._grp_open.get(key, key in GROUP_DEFAULT_OPEN),
                text=_t("grp_" + key),
                values=(total, _fmt_secs(grp_soonest) if grp_soonest else ""))
            self._group_keys[gitem] = key
            for r, name, lives in rows:
                soonest = min(lives) if lives else 0.0
                tags = ("expiring",) if lives and soonest <= 30 else ()
                parent = self.res_tree.insert(
                    gitem, "end", tags=tags, open=bool(lives) and soonest <= 60,
                    text=name,
                    values=(r.quantity, _fmt_secs(soonest) if lives else _t("permanent")))
                self._res_items[parent] = r.entity_id
                if len(lives) > 1:
                    for i, lv in enumerate(lives, 1):
                        child_tags = ("expiring",) if lv <= 30 else ()
                        self.res_tree.insert(parent, "end", tags=child_tags,
                                             text="  " + _t("nth").format(i),
                                             values=("", _fmt_secs(lv)))


def main():
    root = tk.Tk()
    AdvisorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
