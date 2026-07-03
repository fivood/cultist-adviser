# 密教军师 · Cultist Adviser

《密教模拟器》(Cultist Simulator) 的只读建议悬浮窗。它监视游戏存档
`save.json`，解析当前局面后给出按优先级排序的操作建议——**只出主意，
不碰游戏**：不读屏、不模拟鼠标键盘，游戏窗口完全不受影响。

A read-only floating adviser for Cultist Simulator. It watches the save
file, never the game window: no screen capture, no input simulation.

## 功能

- **危险警报**：绝望/幻象死亡倒计时、证据/猎人、病痛/躁动/饥饿、资金水位
- **时节预报**：读取时光 verb 里已抽出的下一时节，未备好对策时提前警告
  （含野心时节的贡品检查）
- **新手开局引导**：本体 4 职业——有志青年 (The Aspirant)、警探
  (The Detective)、富家子弟 (The Bright Young Thing)、医师 (The Physician)；
  DLC 4 职业——舞者 (The Dancer)、教士 (The Priest)、食尸鬼 (The Medium?)、
  流亡者 (The Exile)。按各职业剧情卡逐步提示，数值取自游戏配方
- **中后期推进**：建团时机、野心 1→6 各阶段的条件核对、牡鹿之门谜语、
  远征侦察与善后、对手（长生者候补）警报
- **空闲行动建议**：每个空闲 verb 给出当前最优用法及理由
- **场上资源表**：多张同名卡展开看各自倒计时；双击卡牌查"获得方式"
  （从游戏配方 JSON 反查）
- **暂停感知**：存档超过应到时间未更新即判定游戏暂停，读秒冻结
- **复盘**：每局自动记录快照，可回看资源曲线与警报时间线
- **双语**：卡牌/行动名取自游戏自带的中英文本地化，界面可切换

## 运行

要求：Windows、Python 3.10+（仅标准库，含 tkinter）、已安装游戏本体
（军师从游戏内容文件读取本地化名称与配方知识）。

```
python -m cultist_adviser
```

路径自动探测不中时用环境变量指定：

| 变量 | 含义 | 默认 |
|---|---|---|
| `CULTIST_GAME_DIR` | 游戏安装目录 | 常见 Steam 库位置逐个探测 |
| `CULTIST_SAVE_DIR` | 存档目录 | `%USERPROFILE%\AppData\LocalLow\Weather Factory\Cultist Simulator` |

首次启动会在包目录生成 `lexicon_cache.json` / `knowledge_cache.json`
两个缓存；游戏更新后删掉它们即可重建。

## 致谢

- 部分规则移植自 [autoccultist](https://github.com/SunsetFi/autoccultist)
  的 brain-config（MIT License, Copyright 2020 RoboPhredDev）
- 策略知识整理见 [docs/strategy_knowledge.md](docs/strategy_knowledge.md)，
  来源包括 Steam 社区攻略与 Fandom Wiki
- 《密教模拟器》© Weather Factory。本项目与 Weather Factory 无关，
  不包含任何游戏资源，运行时读取的是玩家本地已安装的游戏内容
