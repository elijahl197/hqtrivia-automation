# NYT Mini Crossword Solver

Automates solving the NYT Mini crossword using Claude AI.

> **Educational / personal use only.** Solving the puzzle yourself is more fun.

---

## Replit web app (recommended for iPad)

Import this repo into [Replit](https://replit.com), set `ANTHROPIC_API_KEY` as a
Secret, then click **Run**.  A mobile-friendly web UI opens in the Replit browser
pane — paste your NYT-S cookie, pick a date, and hit **Solve**.

### Getting your NYT-S cookie on iPad

1. Open **nytimes.com** in Safari and log in.
2. Create a bookmark, edit its URL, and paste the bookmarklet below as the URL.
3. Run the bookmarklet on any nytimes.com page — it will show your **NYT-S** value.

```
javascript:(function(){var c=document.cookie.match(/NYT-S=([^;]+)/);if(c){prompt('Copy your NYT-S cookie:',c[1]);}else{alert('Cookie not found — make sure you are logged in to nytimes.com');}})();
```

---

## How it works

The design follows the same pipeline as the original HQ Trivia automation:

| Step | HQ Trivia (original) | NYT Mini (this project) |
|------|----------------------|-------------------------|
| **Capture** | Screenshot via QuickTime / webcam + OCR | Fetch puzzle JSON from NYT API *or* load from file |
| **Parse** | Extract question + 3 answer choices from OCR text | Build a 5×5 grid + clue list from puzzle data |
| **Lookup** | Wikipedia / Google / dictionary keyword search | Claude AI solves each clue, using crossing letters as hints |
| **Display** | Print highest-scoring answer | Print completed grid + answer list |

### Constraint propagation

Crossword answers intersect — a letter placed by one answer becomes a hint for the crossing answer. The solver iterates:

1. Send all unsolved clues to Claude, including any letters already placed (e.g. pattern `R_VEN`).
2. Place valid answers and update the grid.
3. Repeat with the newly filled-in crossing letters until the grid is complete or no more progress is made.

---

## Installation

```bash
pip install -r requirements.txt
playwright install chromium   # one-time browser download
```

You also need an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Usage

```
python3 nyt-mini-solver.py [-h] (--auto-cookie | --nyt-cookie COOKIE | --json FILE | --interactive)
                            [--date YYYY-MM-DD] [--refresh-cookie] [--iterations N] [-v] [-V]
```

### Option 1 — Fully automated (requires NYT subscription)

```bash
python3 nyt-mini-solver.py --auto-cookie
```

On first run a Chromium window opens so you can log in to nytimes.com.
The NYT-S cookie is extracted automatically and cached to `~/.nyt_mini_cookie`.
All subsequent runs reuse the cached cookie — no DevTools required.

Optionally specify a date:

```bash
python3 nyt-mini-solver.py --auto-cookie --date 2024-06-15
```

Force a fresh login (e.g. after your session expires):

```bash
python3 nyt-mini-solver.py --auto-cookie --refresh-cookie
```

### Option 2 — Manual cookie (requires NYT subscription)

1. Log in to [nytimes.com](https://www.nytimes.com).
2. Open DevTools → Application → Cookies → copy the value of **NYT-S**.
3. Run:

```bash
python3 nyt-mini-solver.py --nyt-cookie <NYT-S value>
```

### Option 3 — Load from a JSON file

```bash
python3 nyt-mini-solver.py --json example_puzzle.json
```

JSON format:

```json
{
  "size": 5,
  "black_squares": [[0, 3], [1, 3]],
  "across": {
    "1": {"clue": "Clue text", "row": 0, "col": 0, "length": 3}
  },
  "down": {
    "1": {"clue": "Clue text", "row": 0, "col": 0, "length": 5}
  }
}
```

See `example_puzzle.json` for a complete working example.

### Option 4 — Interactive entry

```bash
python3 nyt-mini-solver.py --interactive
```

Follow the prompts to enter the grid size, black squares, and clues.

---

## Options

| Flag | Description |
|------|-------------|
| `--auto-cookie` | Open browser once, extract & cache NYT-S cookie automatically |
| `--nyt-cookie COOKIE` | Supply NYT-S session cookie manually |
| `--json FILE` | Load puzzle from JSON file |
| `--interactive` | Enter clues manually |
| `--date YYYY-MM-DD` | Puzzle date (default: today, used with `--auto-cookie` / `--nyt-cookie`) |
| `--refresh-cookie` | Force a new browser login (use with `--auto-cookie`) |
| `--iterations N` | Max solving iterations (default: 5) |
| `-v` / `--verbose` | Debug output |
| `-V` / `--version` | Print version |
