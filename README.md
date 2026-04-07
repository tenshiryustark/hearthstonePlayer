# hearthstonePlayer

An automated competitive player agent for **Hearthstone** that reads the
game window, decides which cards to play, and learns which cards are most
effective through a persistent inner-value system.

---

## Architecture

```
src/
├── card.py             – Card data model with inner_value field
├── card_value_store.py – JSON-backed persistence of card inner values
├── decision_engine.py  – Turn planning: card-play & attack-target selection
├── screen_reader.py    – Screen capture framework + game-state extraction
└── agent.py            – Main orchestration loop
tests/
├── test_card.py
├── test_card_value_store.py
├── test_decision_engine.py
└── test_agent.py
```

---

## How it works

### Inner value

Every card carries an **inner value** (default `1.0`) that persists across
all game sessions in `card_values.json`.  After each game:

| Outcome | Adjustment |
|---------|-----------|
| Win     | `inner_value += 0.1` for every card played this game |
| Loss    | `inner_value -= 0.05` for every card played this game (min 0) |

This means cards that appear in winning games gain value over time, while
cards associated with losses gradually decline.

### Turn decisions

**Which card to play?**  The engine picks the affordable card (mana cost ≤
available mana) with the highest `inner_value`.

**Who to attack?**  For each friendly minion on the board the engine
computes an *action value* for every possible target:

- **Attack a minion**: `kill_factor × threat_factor`
  - `kill_factor = 1.0` if the attacker can one-shot the target, else `0.5`
  - `threat_factor = target.inner_value × target.attack`
- **Attack the hero**: `attacker.attack / enemy_hero_health`

The target with the highest action value is chosen.

---

## Setup

```bash
pip install -r requirements.txt
```

> **Note:** Screen capture (`mss`, `Pillow`) requires a display.  All core
> logic (card values, decision engine) works headlessly and is fully tested
> without a running Hearthstone instance.

---

## Running the agent

```bash
python -m src.agent
```

The agent will start polling the screen every 2 seconds, log the actions it
would take, and update card values when a game ends.  Press **Ctrl-C** to
stop.

---

## Running the tests

```bash
pytest
```