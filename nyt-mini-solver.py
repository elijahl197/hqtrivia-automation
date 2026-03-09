#!/usr/bin/env python3
"""
NYT Mini Crossword Solver

Automates solving the NYT Mini crossword using Claude AI.

Workflow (mirrors the original HQ Trivia automation):
  1. CAPTURE  – fetch today's puzzle from the NYT API  (or load from JSON / interactive input)
  2. PARSE    – turn raw API data into a grid + clue list
  3. LOOKUP   – ask Claude to solve each clue, using crossing letters as hints
  4. DISPLAY  – print the completed grid and every answer

Usage:
    python3 nyt-mini-solver.py --auto-cookie          # browser login, cookie cached automatically
    python3 nyt-mini-solver.py --nyt-cookie <NYT-S>   # supply cookie manually
    python3 nyt-mini-solver.py --json example_puzzle.json
    python3 nyt-mini-solver.py --interactive
"""

import os
import sys
import json
import time
import argparse
import requests
from datetime import date

import anthropic

VERSION = "2024.01.01"


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

class CrosswordGrid:
    """
    Represents the crossword grid.

    Cell values:
        None  – black / blocked square
        ''    – empty white square (not yet filled)
        'A'-'Z' – filled letter
    """

    def __init__(self, width=5, height=5):
        self.width = width
        self.height = height
        self.cells = [['' for _ in range(width)] for _ in range(height)]

    def mark_black(self, row, col):
        self.cells[row][col] = None

    def is_black(self, row, col):
        if row < 0 or row >= self.height or col < 0 or col >= self.width:
            return True
        return self.cells[row][col] is None

    def place_answer(self, answer, row, col, direction):
        """Write an answer string into the grid (overwrites empty/matching cells)."""
        answer = answer.upper().replace(' ', '').replace('-', '')
        for i, letter in enumerate(answer):
            if direction == 'across':
                self.cells[row][col + i] = letter
            else:
                self.cells[row + i][col] = letter

    def get_pattern(self, row, col, direction, length):
        """
        Return the current state of a word slot as a pattern string.
        Known letters are shown; unknown squares are represented by '_'.
        Example: 'C_T' for a 3-letter slot with C and T known.
        """
        chars = []
        for i in range(length):
            r = row + (i if direction == 'down' else 0)
            c = col + (i if direction == 'across' else 0)
            cell = self.cells[r][c]
            chars.append(cell if cell else '_')
        return ''.join(chars)

    def is_complete(self):
        """True when every white square has been filled."""
        for row in self.cells:
            for cell in row:
                if cell == '':
                    return False
        return True

    def display(self):
        """Render the grid to stdout."""
        sep = '+' + ('---+' * self.width)
        print(sep)
        for row in self.cells:
            line = '|'
            for cell in row:
                if cell is None:
                    line += '###|'
                elif cell == '':
                    line += '   |'
                else:
                    line += f' {cell} |'
            print(line)
            print(sep)
        print()


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

class NYTMiniSolver:
    """
    Solves the NYT Mini crossword by combining:
      • NYT puzzle data (API / JSON / interactive)
      • Claude AI for per-clue answer generation
      • Iterative constraint propagation (crossing letters narrow down options)
    """

    def __init__(self, verbose=False):
        self.client = anthropic.Anthropic(timeout=30.0)
        self.grid = CrosswordGrid()

        # clue dicts:  str(number) -> {clue, row, col, length}
        self.across: dict = {}
        self.down: dict = {}

        # solved answers: "1A" / "3D" -> answer string
        self.answers: dict = {}

        self.verbose = verbose

    # ------------------------------------------------------------------ #
    # Logging                                                              #
    # ------------------------------------------------------------------ #

    def log(self, msg):
        if self.verbose:
            sys.stdout.flush()
            print(f"[DEBUG] {msg}")

    # ------------------------------------------------------------------ #
    # Input: NYT API                                                       #
    # ------------------------------------------------------------------ #

    def fetch_nyt_puzzle(self, cookie: str = None, puzzle_date: str = None):
        """
        Fetch a Mini puzzle from the NYT crossword API.

        Args:
            cookie:      The value of the NYT-S session cookie (optional — tried without first).
            puzzle_date: ISO date string (YYYY-MM-DD).  Defaults to today.
        """
        if puzzle_date is None:
            puzzle_date = date.today().strftime('%Y-%m-%d')

        url = f'https://www.nytimes.com/svc/crosswords/v6/puzzle/mini/{puzzle_date}.json'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://www.nytimes.com/crosswords/game/mini',
            'Accept': 'application/json, text/javascript, */*; q=0.01',
            'Accept-Language': 'en-US,en;q=0.9',
            'X-Requested-With': 'XMLHttpRequest',
        }

        # If a cookie was supplied, attach it; otherwise try without auth first
        if cookie:
            # Strip "NYT-S=" prefix in case the user pasted the full cookie string
            if cookie.startswith('NYT-S='):
                cookie = cookie[len('NYT-S='):]
            headers['Cookie'] = f'NYT-S={cookie}'

        print(f"Fetching NYT Mini for {puzzle_date}…")
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code in (401, 403):
            raise RuntimeError(
                f'NYT returned {resp.status_code} — your NYT-S cookie is missing or expired. '
                'Log in at nytimes.com, copy the NYT-S cookie, and paste it above.'
            )
        if resp.status_code == 404:
            raise RuntimeError(f'No Mini puzzle found for {puzzle_date}.')
        resp.raise_for_status()

        try:
            data = resp.json()
        except Exception:
            raise RuntimeError(
                'NYT returned an unexpected response (possibly a login redirect). '
                'Make sure you are logged in and your NYT-S cookie is valid.'
            )
        self._parse_nyt_response(data)

    def _parse_nyt_response(self, data: dict):
        """Translate the raw NYT API JSON into grid + clue structures."""
        body = data.get('body', [{}])[0]
        dimensions = body.get('dimensions', {'width': 5, 'height': 5})
        width = dimensions.get('width', 5)
        height = dimensions.get('height', 5)
        cells_raw = body.get('cells', [])
        clues_raw = body.get('clues', [])

        self.grid = CrosswordGrid(width, height)

        # Map flat cell index -> (row, col)
        cell_pos = {}
        for idx, cell in enumerate(cells_raw):
            row = idx // width
            col = idx % width
            if cell.get('type') == 0:          # 0 = black square
                self.grid.mark_black(row, col)
            cell_pos[idx] = (row, col)

        # Parse clue groups
        for group in clues_raw:
            direction = group.get('direction', '').lower()
            for clue_data in group.get('clues', []):
                num = str(clue_data['label'])

                # Clue text may be a list of dicts or a plain string
                text_field = clue_data.get('text', '')
                if isinstance(text_field, list):
                    text = text_field[0].get('plain', str(text_field[0]))
                else:
                    text = str(text_field)

                cell_indices = clue_data.get('cells', [])
                if not cell_indices:
                    continue

                row, col = cell_pos.get(cell_indices[0], (0, 0))
                length = len(cell_indices)
                entry = {'clue': text, 'row': row, 'col': col, 'length': length}

                if direction == 'across':
                    self.across[num] = entry
                else:
                    self.down[num] = entry

        self.log(f"Parsed {len(self.across)} across + {len(self.down)} down clues")

    # ------------------------------------------------------------------ #
    # Input: JSON file                                                     #
    # ------------------------------------------------------------------ #

    def load_from_json(self, filepath: str):
        """
        Load a puzzle from a JSON file.

        Expected format (see example_puzzle.json):
        {
          "size": 5,
          "black_squares": [[row, col], ...],
          "across": {
            "1": {"clue": "...", "row": 0, "col": 0, "length": 5},
            ...
          },
          "down": { ... }
        }
        """
        with open(filepath) as f:
            data = json.load(f)

        size = data.get('size', 5)
        width = data.get('width', size)
        height = data.get('height', size)
        self.grid = CrosswordGrid(width, height)

        for sq in data.get('black_squares', []):
            self.grid.mark_black(sq[0], sq[1])

        for num, entry in data.get('across', {}).items():
            self.across[str(num)] = entry
        for num, entry in data.get('down', {}).items():
            self.down[str(num)] = entry

        self.log(f"Loaded {len(self.across)} across + {len(self.down)} down from {filepath}")

    # ------------------------------------------------------------------ #
    # Input: Interactive                                                   #
    # ------------------------------------------------------------------ #

    def load_interactive(self):
        """Prompt the user to enter clues via stdin."""
        print("NYT Mini Crossword Solver — Interactive Mode")
        print("=" * 50)

        raw = input("Grid size (default 5): ").strip()
        size = int(raw) if raw else 5
        self.grid = CrosswordGrid(size, size)

        raw = input("Black squares as 'row,col' space-separated (leave blank if none): ").strip()
        if raw:
            for sq in raw.split():
                r, c = sq.split(',')
                self.grid.mark_black(int(r), int(c))

        print("\nAcross clues — format: num,row,col,length,clue text")
        print("  (press Enter on a blank line when done)")
        while True:
            line = input("  ACROSS> ").strip()
            if not line:
                break
            parts = line.split(',', 4)
            if len(parts) < 5:
                print("  Need: num,row,col,length,clue text")
                continue
            num, row, col, length, clue = parts
            self.across[num.strip()] = {
                'clue': clue.strip(),
                'row': int(row), 'col': int(col), 'length': int(length),
            }

        print("\nDown clues — same format")
        print("  (press Enter on a blank line when done)")
        while True:
            line = input("  DOWN>   ").strip()
            if not line:
                break
            parts = line.split(',', 4)
            if len(parts) < 5:
                print("  Need: num,row,col,length,clue text")
                continue
            num, row, col, length, clue = parts
            self.down[num.strip()] = {
                'clue': clue.strip(),
                'row': int(row), 'col': int(col), 'length': int(length),
            }

    # ------------------------------------------------------------------ #
    # Claude — clue solver                                                 #
    # ------------------------------------------------------------------ #

    def solve_clue_with_claude(self, clue: str, length: int, pattern: str) -> str | None:
        """
        Ask Claude to solve a single crossword clue.

        Args:
            clue:    The clue text, e.g. "Edgar Allan Poe bird".
            length:  Exact number of letters required.
            pattern: Current known letters, e.g. "R_VEN" ('_' = unknown).

        Returns:
            The answer string (uppercase, no spaces), or None on failure.
        """
        # Already fully known?
        if '_' not in pattern:
            return pattern

        pattern_info = ''
        if any(c != '_' for c in pattern):
            pattern_info = (
                f'\nKnown letters pattern: {pattern}  '
                f'(underscore = unknown position)'
            )

        prompt = (
            f'Solve this crossword clue.\n'
            f'Return ONLY the answer — no explanation, no punctuation.\n\n'
            f'Clue: {clue}\n'
            f'Answer length: {length} letters'
            f'{pattern_info}\n\n'
            f'Rules:\n'
            f'- Exactly {length} letters\n'
            f'- No spaces or hyphens (compound words run together)\n'
            f'- If a pattern is given, every known letter must match exactly\n'
            f'- Standard crossword conventions apply\n\n'
            f'Answer:'
        )

        self.log(f"Claude ← clue='{clue}', length={length}, pattern={pattern}")

        message = self.client.messages.create(
            model='claude-opus-4-6',
            max_tokens=64,
            messages=[{'role': 'user', 'content': prompt}],
        )

        raw = message.content[0].text.strip().upper()
        # Strip any non-alpha characters the model may have included
        answer = ''.join(c for c in raw if c.isalpha())

        self.log(f"Claude → '{answer}'")

        if len(answer) == length:
            return answer

        # If the model returned multiple words, grab the first right-length one
        words = raw.split()
        for w in words:
            clean = ''.join(c for c in w if c.isalpha())
            if len(clean) == length:
                return clean

        return None

    # ------------------------------------------------------------------ #
    # Constraint check                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def matches_pattern(answer: str, pattern: str) -> bool:
        """Return True if answer is consistent with the known-letter pattern."""
        if len(answer) != len(pattern):
            return False
        return all(p == '_' or a == p for a, p in zip(answer, pattern))

    # ------------------------------------------------------------------ #
    # Main solve loop                                                      #
    # ------------------------------------------------------------------ #

    def solve(self, max_iterations: int = 5):
        """
        Iteratively solve the puzzle.

        Each pass sends unsolved clues to Claude, using any crossing letters
        already placed as pattern hints.  The loop continues until the grid
        is complete or no new progress is made.
        """
        all_clues = (
            [('across', num, entry) for num, entry in self.across.items()] +
            [('down',   num, entry) for num, entry in self.down.items()]
        )

        print(f"\nSolving {len(all_clues)} clues…\n")
        start = time.time()

        for iteration in range(1, max_iterations + 1):
            self.log(f"=== Iteration {iteration} ===")
            progress = False
            unsolved = []

            for direction, num, entry in all_clues:
                key = f"{num}{'A' if direction == 'across' else 'D'}"
                row, col = entry['row'], entry['col']
                length = entry['length']
                pattern = self.grid.get_pattern(row, col, direction, length)

                if '_' not in pattern:
                    continue   # already filled

                answer = self.solve_clue_with_claude(entry['clue'], length, pattern)

                if answer and self.matches_pattern(answer, pattern):
                    self.grid.place_answer(answer, row, col, direction)
                    self.answers[key] = answer
                    print(f"  {key:>3}: {entry['clue'][:45]:<45}  →  {answer}")
                    progress = True
                else:
                    unsolved.append((key, entry['clue'], pattern, answer))

            if self.grid.is_complete():
                elapsed = time.time() - start
                print(f"\nPuzzle solved in {elapsed:.1f}s!")
                break

            if not progress:
                print(f"\nNo progress on iteration {iteration}.")
                if unsolved:
                    print("Remaining unsolved clues:")
                    for key, clue, pattern, attempted in unsolved:
                        note = f"  (tried: {attempted})" if attempted else ""
                        print(f"  {key:>3}: {clue}  [pattern: {pattern}]{note}")
                break

            if iteration < max_iterations:
                print(f"\n  — grid after iteration {iteration} —")
                self.grid.display()

    # ------------------------------------------------------------------ #
    # Output                                                               #
    # ------------------------------------------------------------------ #

    def display_results(self):
        """Print the final grid and a clean answer list."""
        print("\n" + "=" * 50)
        print("FINAL GRID")
        print("=" * 50)
        self.grid.display()

        print("ACROSS")
        print("-" * 30)
        for num in sorted(self.across, key=lambda x: int(x)):
            key = f"{num}A"
            answer = self.answers.get(key, '???')
            print(f"  {num:>2}. {self.across[num]['clue']:<40}  {answer}")

        print("\nDOWN")
        print("-" * 30)
        for num in sorted(self.down, key=lambda x: int(x)):
            key = f"{num}D"
            answer = self.answers.get(key, '???')
            print(f"  {num:>2}. {self.down[num]['clue']:<40}  {answer}")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Automate solving the NYT Mini crossword using Claude AI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 nyt-mini-solver.py --nyt-cookie <NYT-S value>
  python3 nyt-mini-solver.py --json example_puzzle.json
  python3 nyt-mini-solver.py --interactive
        """,
    )

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        '--auto-cookie', action='store_true',
        help=(
            "Auto-extract the NYT-S cookie via a browser window (opens once, "
            "then caches to ~/.nyt_mini_cookie for future runs)"
        ),
    )
    source.add_argument(
        '--nyt-cookie', metavar='COOKIE',
        help="Value of your NYT-S session cookie (log in to nytimes.com and copy it)",
    )
    source.add_argument(
        '--json', metavar='FILE',
        help="JSON file with puzzle grid and clues (see example_puzzle.json)",
    )
    source.add_argument(
        '--interactive', action='store_true',
        help="Enter puzzle clues manually via prompts",
    )

    parser.add_argument(
        '--refresh-cookie', action='store_true',
        help="Force a new browser login even if a cached cookie exists (use with --auto-cookie)",
    )

    parser.add_argument(
        '--date', metavar='YYYY-MM-DD', default=None,
        help="Puzzle date to fetch (default: today, only used with --nyt-cookie)",
    )
    parser.add_argument(
        '--iterations', type=int, default=5,
        help="Maximum solving iterations (default: 5)",
    )
    parser.add_argument(
        '-v', '--verbose', action='store_true',
        help="Print debug output",
    )
    parser.add_argument(
        '-V', '--version', action='store_true',
        help="Show version and exit",
    )

    opts = parser.parse_args()

    if opts.version:
        print(f"nyt-mini-solver {VERSION}")
        sys.exit(0)

    solver = NYTMiniSolver(verbose=opts.verbose)

    if opts.auto_cookie:
        from cookie_manager import get_cookie
        cookie = get_cookie(force_refresh=opts.refresh_cookie)
        solver.fetch_nyt_puzzle(cookie=cookie, puzzle_date=opts.date)
    elif opts.nyt_cookie:
        solver.fetch_nyt_puzzle(cookie=opts.nyt_cookie, puzzle_date=opts.date)
    elif opts.json:
        print(f"Loading puzzle from {opts.json}…")
        solver.load_from_json(opts.json)
    elif opts.interactive:
        solver.load_interactive()

    solver.solve(max_iterations=opts.iterations)
    solver.display_results()
