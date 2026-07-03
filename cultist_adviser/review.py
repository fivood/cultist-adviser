"""Post-session review: timeline of key events, trend chart, and summary stats.

Standalone:  python -m cultist_adviser.review [session_file]
Also opened from the advisor GUI via the Review button.
"""
import sys
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from . import lexicon
from .lexicon import display_name, tr
from .advisor import DANGER_VERBS
from .recorder import list_sessions, load_session

# Cards whose gains/losses matter for the default "key events" view.
KEY_CARDS = {"funds", "health", "reason", "passion", "dread", "fascination",
             "contentment", "fleeting", "sickness", "restlessness", "hunger",
             "decrepitude", "notoriety", "mystique"}

UI = {
    "title": ("密教复盘", "Cultist Review"),
    "session": ("会话", "Session"),
    "key_only": ("只看关键事件", "Key events only"),
    "time": ("时间", "Time"),
    "event": ("事件", "Event"),
    "no_data": ("该会话没有快照数据。", "No snapshots in this session."),
    "stats": ("时长 {dur} · 快照 {n} · 资金 {fmin}~{fmax} · 危机 {danger} 次 · 紧急警报 {urgent} 次",
              "Duration {dur} · {n} snapshots · Funds {fmin}~{fmax} · {danger} crises · {urgent} urgent alerts"),
    "danger_start": ("⚠ 危机出现：「{}」开始倒计时", "⚠ Crisis: {} countdown started"),
    "danger_end": ("✔ 危机解除：「{}」", "✔ Crisis resolved: {}"),
    "gain": ("+{n} {name}", "+{n} {name}"),
    "lose": ("-{n} {name}", "-{n} {name}"),
    "urgent_new": ("！警报：{}", "! Alert: {}"),
    "start": ("记录开始（{who} · {legacy}）", "Recording starts ({who} · {legacy})"),
    "verb_start": ("▶ {verb}：{recipe}", "▶ {verb}: {recipe}"),
    "ending": ("🏁 本局结束：{}", "🏁 Run over: {}"),
    "ended_stat": (" · 结局：{}", " · ending: {}"),
    "legend": ("资金=蓝 恐惧=红 入迷=紫", "Funds=blue Dread=red Fascination=purple"),
    "tab_events": ("事件史", "Events"),
    "tab_stats": ("行为统计", "Actions"),
    "col_recipe": ("做了什么", "What was done"),
    "col_count": ("次数", "Times"),
    "no_stats": ("该记录没有行为统计（旧版本记录或局刚开始）。",
                 "No action stats in this recording (old file, or the run just began)."),
}

# The time verb restarts every 60s; logging each cycle would drown the history.
UNLOGGED_VERBS = {"time", "time.exile"}

# Engine housekeeping recipes to hide from the action-stats view. Everything
# without a localized label is dropped anyway; "needs" (时间流逝) has one.
STAT_NOISE = {"needs"}


def _t(key: str) -> str:
    zh, en = UI[key]
    return zh if lexicon.get_language() == "zh" else en


def extract_events(snaps: list[dict]) -> list[dict]:
    """Diff consecutive snapshots into (t, kind, payload) events."""
    events = []
    prev = None
    for s in snaps:
        if prev is None:
            events.append({"t": s["t"], "kind": "start",
                           "who": s.get("character", "?"), "legacy": s.get("legacy", "")})
        else:
            prev_danger = {v[0]: v[1] for v in prev["verbs"] if v[0] in DANGER_VERBS}
            cur_danger = {v[0]: v[1] for v in s["verbs"] if v[0] in DANGER_VERBS}
            for verb in sorted(cur_danger.keys() - prev_danger.keys()):
                events.append({"t": s["t"], "kind": "danger_start", "id": verb,
                               "recipe": cur_danger[verb]})
            for verb in sorted(prev_danger.keys() - cur_danger.keys()):
                events.append({"t": s["t"], "kind": "danger_end", "id": verb,
                               "recipe": prev_danger[verb]})

            # The player's choices: a verb starting (or switching to) a recipe.
            prev_recipes = {v[0]: v[1] for v in prev["verbs"] if v[2] > 0}
            for verb, recipe, left in s["verbs"]:
                if left <= 0 or verb in UNLOGGED_VERBS or verb in DANGER_VERBS:
                    continue
                if prev_recipes.get(verb) != recipe:
                    events.append({"t": s["t"], "kind": "verb_start",
                                   "id": verb, "recipe": recipe})

            if s.get("ending") and not prev.get("ending"):
                events.append({"t": s["t"], "kind": "ending", "id": s["ending"]})

            keys = set(prev["resources"]) | set(s["resources"])
            for k in sorted(keys):
                delta = s["resources"].get(k, 0) - prev["resources"].get(k, 0)
                if delta:
                    events.append({"t": s["t"], "kind": "gain" if delta > 0 else "lose",
                                   "id": k, "n": abs(delta)})

            for title in s.get("urgent", []):
                if title not in prev.get("urgent", []):
                    events.append({"t": s["t"], "kind": "urgent", "text": title})
        prev = s
    return events


def _danger_name(ev: dict) -> str:
    name = display_name(ev["id"])
    if name == ev["id"] and ev.get("recipe"):  # season verbs have no label of their own
        name = lexicon.recipe_name(ev["recipe"])
    return name


def event_text(ev: dict) -> str:
    kind = ev["kind"]
    if kind == "start":
        return _t("start").format(who=ev["who"], legacy=display_name(ev["legacy"]))
    if kind == "danger_start":
        return _t("danger_start").format(_danger_name(ev))
    if kind == "danger_end":
        return _t("danger_end").format(_danger_name(ev))
    if kind == "urgent":
        return _t("urgent_new").format(ev["text"])
    if kind == "verb_start":
        return _t("verb_start").format(verb=display_name(ev["id"]),
                                       recipe=lexicon.recipe_name(ev["recipe"]))
    if kind == "ending":
        return _t("ending").format(display_name(ev["id"]))
    return _t(kind).format(n=ev["n"], name=display_name(ev["id"]))


def latest_recipe_counts(snaps: list[dict]) -> dict[str, int]:
    """Most recent cumulative RecipeExecutions in the recording (recorder only
    writes the dict when it changes, so scan backwards)."""
    for sn in reversed(snaps):
        if sn.get("recipes"):
            return sn["recipes"]
    return {}


def is_key_event(ev: dict) -> bool:
    if ev["kind"] in ("start", "danger_start", "danger_end", "urgent",
                      "verb_start", "ending"):
        return True
    return ev.get("id") in KEY_CARDS


def summarize(snaps: list[dict], events: list[dict]) -> str:
    t0, t1 = snaps[0]["t"], snaps[-1]["t"]
    m, s = divmod(int(t1 - t0), 60)
    funds = [sn["resources"].get("funds", 0) for sn in snaps]
    text = _t("stats").format(
        dur=f"{m}:{s:02d}", n=len(snaps),
        fmin=min(funds), fmax=max(funds),
        danger=sum(1 for e in events if e["kind"] == "danger_start"),
        urgent=sum(1 for e in events if e["kind"] == "urgent"),
    )
    ending = next((sn["ending"] for sn in reversed(snaps) if sn.get("ending")), "")
    if ending:
        text += _t("ended_stat").format(display_name(ending))
    return text


SERIES = (("funds", "#1565c0"), ("dread", "#c62828"), ("fascination", "#6a1b9a"))


def draw_chart(canvas: tk.Canvas, snaps: list[dict]):
    canvas.delete("all")
    w = int(canvas.winfo_width()) or 440
    h = int(canvas.winfo_height()) or 150
    ml, mr, mt, mb = 28, 8, 8, 16
    t0, t1 = snaps[0]["t"], snaps[-1]["t"]
    span = max(t1 - t0, 1.0)
    peak = max(1, *(sn["resources"].get(key, 0) for sn in snaps for key, _ in SERIES))

    canvas.create_line(ml, h - mb, w - mr, h - mb, fill="#999999")
    canvas.create_line(ml, mt, ml, h - mb, fill="#999999")
    canvas.create_text(ml - 4, mt, text=str(peak), anchor="e", fill="#666666", font=("", 8))
    canvas.create_text(ml - 4, h - mb, text="0", anchor="e", fill="#666666", font=("", 8))
    m, s = divmod(int(span), 60)
    canvas.create_text(w - mr, h - mb + 2, text=f"{m}:{s:02d}", anchor="ne",
                       fill="#666666", font=("", 8))

    for key, color in SERIES:
        points = []
        for sn in snaps:
            x = ml + (sn["t"] - t0) / span * (w - ml - mr)
            y = (h - mb) - sn["resources"].get(key, 0) / peak * (h - mt - mb)
            points.extend((x, y))
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=2)
    canvas.create_text(ml + 4, mt, text=_t("legend"), anchor="nw",
                       fill="#666666", font=("", 8))


class ReviewWindow:
    def __init__(self, master, session: Path | None = None):
        self.win = tk.Toplevel(master) if master else tk.Tk()
        self.win.title(_t("title"))
        self.win.geometry("520x620")

        self.sessions = list_sessions()
        top = ttk.Frame(self.win, padding=(8, 6))
        top.pack(fill="x")
        ttk.Label(top, text=_t("session")).pack(side="left")
        self.session_var = tk.StringVar()
        self.session_box = ttk.Combobox(top, textvariable=self.session_var, state="readonly",
                                        width=28, values=[p.name for p in self.sessions])
        self.session_box.pack(side="left", padx=6)
        self.session_box.bind("<<ComboboxSelected>>", lambda e: self._load())
        self.key_only = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text=_t("key_only"), variable=self.key_only,
                        command=self._render_events).pack(side="right")

        self.stats_var = tk.StringVar()
        ttk.Label(self.win, textvariable=self.stats_var, padding=(8, 0)).pack(fill="x")

        self.canvas = tk.Canvas(self.win, height=150, bg="white", highlightthickness=0)
        self.canvas.pack(fill="x", padx=8, pady=6)
        self.canvas.bind("<Configure>", lambda e: self._redraw_chart())

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        frame = ttk.Frame(nb)
        nb.add(frame, text=_t("tab_events"))
        self.tree = ttk.Treeview(frame, columns=("time", "event"), show="headings")
        self.tree.heading("time", text=_t("time"))
        self.tree.heading("event", text=_t("event"))
        self.tree.column("time", width=70, anchor="e", stretch=False)
        self.tree.column("event", width=400)
        self.tree.tag_configure("danger", foreground="#c62828")
        self.tree.tag_configure("good", foreground="#2e7d32")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)

        stats_frame = ttk.Frame(nb)
        nb.add(stats_frame, text=_t("tab_stats"))
        self.stats_tree = ttk.Treeview(stats_frame, columns=("recipe", "count"),
                                       show="headings")
        self.stats_tree.heading("recipe", text=_t("col_recipe"))
        self.stats_tree.heading("count", text=_t("col_count"))
        self.stats_tree.column("recipe", width=380)
        self.stats_tree.column("count", width=60, anchor="e", stretch=False)
        stats_scroll = ttk.Scrollbar(stats_frame, orient="vertical",
                                     command=self.stats_tree.yview)
        self.stats_tree.configure(yscrollcommand=stats_scroll.set)
        stats_scroll.pack(side="right", fill="y")
        self.stats_tree.pack(side="left", fill="both", expand=True)

        self.snaps: list[dict] = []
        self.events: list[dict] = []
        if session and session.exists():
            self.session_var.set(session.name)
        elif self.sessions:
            self.session_var.set(self.sessions[0].name)
        self._load()

    def _session_path(self) -> Path | None:
        name = self.session_var.get()
        for p in self.sessions:
            if p.name == name:
                return p
        return Path(name) if name else None

    def _load(self):
        path = self._session_path()
        self.snaps = load_session(path) if path and path.exists() else []
        if not self.snaps:
            self.stats_var.set(_t("no_data"))
            self.events = []
            self.canvas.delete("all")
            self._render_events()
            self._render_stats()
            return
        self.events = extract_events(self.snaps)
        self.stats_var.set(summarize(self.snaps, self.events))
        self._redraw_chart()
        self._render_events()
        self._render_stats()

    def _redraw_chart(self):
        if self.snaps:
            draw_chart(self.canvas, self.snaps)

    def _render_stats(self):
        self.stats_tree.delete(*self.stats_tree.get_children())
        recipes = latest_recipe_counts(self.snaps)
        rows = []
        for rid, count in recipes.items():
            if rid in STAT_NOISE:
                continue
            name = lexicon.recipe_name(rid)
            if name == rid:  # no localized label — engine housekeeping recipe
                continue
            rows.append((name, count))
        if not rows:
            self.stats_tree.insert("", "end", values=(_t("no_stats"), ""))
            return
        for name, count in sorted(rows, key=lambda kv: -kv[1]):
            self.stats_tree.insert("", "end", values=(name, count))

    def _render_events(self):
        self.tree.delete(*self.tree.get_children())
        if not self.snaps:
            return
        t0 = self.snaps[0]["t"]
        for ev in self.events:
            if self.key_only.get() and not is_key_event(ev):
                continue
            m, s = divmod(int(ev["t"] - t0), 60)
            tags = ()
            if ev["kind"] in ("danger_start", "urgent"):
                tags = ("danger",)
            elif ev["kind"] in ("danger_end", "ending"):
                tags = ("good",)
            self.tree.insert("", "end", tags=tags,
                             values=(f"{m}:{s:02d}", event_text(ev)))


def main():
    session = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    win = ReviewWindow(None, session)
    win.win.mainloop()


if __name__ == "__main__":
    main()
