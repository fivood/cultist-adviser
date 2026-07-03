"""Post-session review: timeline of key events, trend chart, and summary stats.

Standalone:  python -m cultist_adviser.review [session_file]
Also opened from the advisor GUI via the Review button.
"""
import re
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

# Post-mortem lessons: ending id -> (zh cause, zh prevention, en cause, en prevention).
# Turning "died again" into "learnt something" — the run is over, so no spoiler
# gating applies here.
ENDING_LESSONS = {
    "despairending": (
        "绝望吞噬——3 张恐惧被吸满，无人安慰。",
        "常备「安逸」（入梦：恐惧+安逸可消）；恐惧攒到 2 张就要准备对策；穷途末路时入梦 + 1 资金买鸦片酊救急。",
        "Despair devoured three Dread with no comfort in reach.",
        "Keep Contentment handy (Dream: Dread + Contentment clears it); prepare "
        "counters at two Dread; in extremis, Dream with 1 Funds for the opium."),
    "visionsending": (
        "辉光焚身——3 张入迷被吸满，理智燃尽。",
        "备「恐惧」或「一瞬追忆」；入梦把入迷+恐惧换成更安全的一瞬追忆；健康早睡早起也能囤追忆。",
        "Glory burned through three unchecked Fascination.",
        "Hold Dread or a Fleeting Reminiscence; Dream Fascination with Dread into "
        "the safer Reminiscence; early nights with Health stockpile them."),
    "deathofthebody": (
        "肉体消亡——最后一点健康被夺走。",
        "资金别断（断粮直接扣健康）；疾病结算时桌面必须留有健康或疲惫可取；病痛出现立刻入梦 + 资金/活力治疗。",
        "The body failed — the last Health was taken.",
        "Never run out of Funds (starvation eats Health); keep a Health or Fatigue "
        "free on the table when Sickness resolves; treat Afflictions at once."),
    "arrest": (
        "隔槛望日——确凿证据把你送上了法庭。",
        "邪名/秘氛别攒着过疑心时节；证据一出现就派蛾系手下销毁；常备一张「当局欠下的人情」保命。",
        "Bars across the sun — damning evidence made the trial.",
        "Never carry reputation into a Suspicion season; destroy evidence with a "
        "Moth follower the moment it appears; keep a Favour in reserve."),
    "wintersacrifice": (
        "静静离去——波比想要的灵魂没有给她。",
        "波比的倒计时内投入一名手下满足她；提前养一个可以割舍的信徒。",
        "Going quietly — Poppy's price went unpaid.",
        "Feed her a follower before the countdown ends; keep an expendable "
        "believer for exactly this day."),
    "longnightmareending": (
        "梦魇撕碎——与长生者的梦境对决中败北。",
        "梦境对决会吸走理性/激情，别在属性耗尽时应战；先用手下侦查、拖延他的谋划。",
        "Nightmares tore you apart in the dream duel with the Long.",
        "The duel devours Reason/Passion — never fight it drained; spy on and "
        "delay their schemes with followers first."),
    "rivalascension": (
        "对手先行——长生者候补抢先完成了飞升。",
        "对手出现就要处理：刃系手下暗杀（等级 10+ 必成），或全力加速自己的野心进度。",
        "The rival ascended first.",
        "Deal with rivals when they surface: an Edge-10 follower's knife is "
        "certain, or simply outpace them."),
    "rivalascensionapostle": (
        "长生过甚——使徒之世，仍有对手先你一步登顶。",
        "使徒线的对手更不容拖延：早侦查、早暗杀，或全速推进伟业。",
        "Too many Longs — even in the Apostle's era, a rival topped the peak first.",
        "Apostle-run rivals brook no delay: scout early, strike early, or race "
        "the Great Work flat out."),
    "foecaughtup": (
        "仇敌追上——痕迹引来了最后的清算。",
        "痕迹是流亡者的命门：控制积累，热度高了立刻换城市。",
        "The foe caught up — the trace led them straight to you.",
        "Trace is the Exile's lifeline: keep it low, and move city the moment "
        "the heat rises."),
}


# Every named NPC has a marry-them ending of their own (21 in total).
MARRIAGE_ENDINGS = frozenset(
    f"{name}victory" for name in
    ("tristan", "valciane", "laidlaw", "elridge", "rose", "victor", "saliba",
     "renira", "violet", "auclair", "enid", "neville", "cat", "clifton",
     "slee", "porter", "ysabet", "sylvia", "clovette", "dorothy", "leo"))

# One-line route recaps for the named victories: (zh, en).
VICTORY_NOTES = {
    "workvictory": (
        "在格洛弗与格洛弗干到了头，安稳退休。凡人的胜利也是胜利——下一世要不要试试更危险的路？",
        "Retired at the top of Glover & Glover. A mortal's victory still counts — "
        "dare a stranger road next life?"),
    "workvictoryb": (
        "野心止步于世俗的顶点，潮水退去。",
        "Ambition crested at a worldly summit, and the tide went out."),
    "turnasidevictory": (
        "主动放下了诱惑，全身而退，永享幸福——少有人选的那扇门。",
        "You set the temptation aside and walked away happy — the door few choose."),
    "workvictorymarriage": (
        "嫁入了新的生活（舞者线）。舞台谢幕，帷幕后另有人间。",
        "Married into a new life (the Dancer's road). The stage went dark; "
        "life went on behind the curtain."),
    "minorpalestvictory": (
        "直至严冬降临——无面者之路的胜利（食尸鬼线）。",
        "Until the winter comes — the Pale road's victory (the Ghoul's line)."),
    "minorcrownedgrowthvictory": (
        "硕果累累——加冕生长之路的胜利（食尸鬼线）。",
        "Fruit upon fruit — the Crowned Growth's victory (the Ghoul's line)."),
    "minorknockvictory": (
        "母亲的臂弯——启之路的胜利（教士线）。",
        "The Mother's arms — the Knock road's victory (the Priest's line)."),
    "minormarevictory": (
        "我们去往何处——梦魇之路的胜利（教士线）。",
        "Where do we go — the Mare's victory (the Priest's line)."),
    "victoryvelvet": (
        "血裔——天鹅绒的隐秘胜利（流亡者线）。",
        "Velvet's hidden victory — the bloodline endures (the Exile's line)."),
}
for _m in ("majorforgevictory", "majorgrailvictory", "majorlanternvictory"):
    VICTORY_NOTES[_m] = (
        "使徒大胜——把前世飞升的伟业推至极致。这是系列真正的终点之一。",
        "An Apostle's major victory — the ascended work carried to its zenith. "
        "One of the true endings.")
for _m in ("ascensioncolonel", "ascensionlionsmith", "ascensionwolf"):
    VICTORY_NOTES[_m] = (
        "将自己献给无尽仇怨，成为战争三相的器皿——流亡者的飞升。",
        "Given over to endless enmity, a vessel of the war-gods three — "
        "the Exile's ascension.")

_MINOR_RE = re.compile(r"^minor(forge|grail|lantern|heart|moth|meniscate)"
                       r"victory(withrisen)?$")


def ending_lesson(ending_id: str) -> tuple[str, bool]:
    """(post-mortem text, is_victory) for a recorded ending. Losses come with
    prevention; victories with a one-line recap of the road taken."""
    zh = lexicon.get_language() == "zh"
    lesson = ENDING_LESSONS.get(ending_id)
    if lesson:
        cause, fix = (lesson[0], lesson[1]) if zh else (lesson[2], lesson[3])
        return (f"死因：{cause}  下局预防：{fix}" if zh
                else f"Cause: {cause}  Next run: {fix}"), False
    if ending_id in MARRIAGE_ENDINGS:
        return (("与挚爱共度余生。放下奥秘、选择人间，也是一条完整的路。"
                 "（路线：探索结识 → 谈话加深 → 恋人 → 情愫时节回应）" if zh else
                 "A life shared with the one you love. Setting the Mysteries "
                 "aside is a whole road of its own. (Route: explore to meet, "
                 "talk to deepen, a lover, answer the Season of Ardours.)"), True)
    m = _MINOR_RE.match(ending_id)
    if m:
        text = ("标准飞升达成。路线回顾：野心升到 6 级 → 主系秘传合计 36+ → 高级影响 + 仪式。" if zh else
                "A standard ascension. The road: ambition to 6, 36+ prime lore, "
                "a high influence and the rite.")
        if m.group(2):
            text += ("而且有复生者随行——完全形态的飞升。" if zh else
                     " And with a Risen at your side — the fuller form.")
        return text, True
    if ending_id.startswith("obscurityvictory"):
        tier = {"a": "宁静", "b": "安适", "c": "罕见的快乐"}.get(
            ending_id.replace("obscurityvictory", "")[:1], "")
        text = (f"隐姓埋名，换来{tier}的生活（流亡者线）。" if zh else
                "Vanished into obscurity, and bought a quiet life (the Exile's road).")
        if "foeslain" in ending_id:
            text += ("而且仇敌已被手刃。" if zh else " And the foe lies slain.")
        return text, True
    note = VICTORY_NOTES.get(ending_id)
    if note:
        return (note[0] if zh else note[1]), True
    if "victory" in ending_id:
        return ("这局赢了——回看事件史，记住这条路。" if zh
                else "A victory — walk the event history and remember the road."), True
    return ("结局已至。回看事件史，看看最后一段发生了什么。" if zh
            else "The run has ended. Walk the event history to see the final stretch."), False

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
        self.analysis_var = tk.StringVar()
        self.analysis_label = tk.Label(self.win, textvariable=self.analysis_var,
                                       justify="left", anchor="w", wraplength=496,
                                       padx=8, fg="#8c1f1f",
                                       font=("Microsoft YaHei UI", 9))
        self.analysis_label.pack(fill="x")

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
            self.analysis_var.set("")
            self.events = []
            self.canvas.delete("all")
            self._render_events()
            self._render_stats()
            return
        self.events = extract_events(self.snaps)
        self.stats_var.set(summarize(self.snaps, self.events))
        ending = next((sn["ending"] for sn in reversed(self.snaps)
                       if sn.get("ending")), "")
        if ending:
            text, is_win = ending_lesson(ending)
            self.analysis_var.set(("🏆 " if is_win else "💀 ") + text)
            self.analysis_label.configure(fg="#2e7d32" if is_win else "#8c1f1f")
        else:
            self.analysis_var.set("")
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
