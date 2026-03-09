#!/usr/bin/env python3
"""
NYT Mini Solver — Replit web app entry point.

Exposes a simple Flask UI so you can solve the puzzle from any browser
(including iPad) without touching the command line.

Set the ANTHROPIC_API_KEY secret in your Replit project before running.
"""

import importlib.util
import io
import sys
import os
from datetime import date, datetime
from flask import Flask, render_template, request

# ---------------------------------------------------------------------------
# Import solver from nyt-mini-solver.py (hyphenated filename)
# ---------------------------------------------------------------------------

def _load_solver_module():
    path = os.path.join(os.path.dirname(__file__), 'nyt-mini-solver.py')
    spec = importlib.util.spec_from_file_location('nyt_mini_solver', path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_solver_mod  = _load_solver_module()
NYTMiniSolver = _solver_mod.NYTMiniSolver

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route('/', methods=['GET'])
def index():
    today = date.today().strftime('%Y-%m-%d')
    return render_template('index.html', today=today)


@app.route('/solve', methods=['POST'])
def solve():
    today  = date.today().strftime('%Y-%m-%d')
    cookie = request.form.get('cookie', '').strip()
    puzzle_date = request.form.get('date', '').strip() or None

    # Validate date format if provided
    if puzzle_date:
        try:
            datetime.strptime(puzzle_date, '%Y-%m-%d')
        except ValueError:
            return render_template('index.html', today=today,
                                   error='Date must be in YYYY-MM-DD format.')

    # Capture solver's print() output for display in the UI
    buf = io.StringIO()
    old_stdout = sys.stdout
    sys.stdout = buf

    try:
        solver = NYTMiniSolver(verbose=False)
        solver.fetch_nyt_puzzle(cookie=cookie or None, puzzle_date=puzzle_date)
        solver.solve(max_iterations=5)
    except SystemExit as e:
        sys.stdout = old_stdout
        msg = buf.getvalue().strip().replace('ERROR: ', '') or str(e) or 'Network or auth error.'
        return render_template('index.html', today=today, error=msg)
    except Exception as e:
        sys.stdout = old_stdout
        return render_template('index.html', today=today, error=str(e))
    finally:
        sys.stdout = old_stdout

    log_output = buf.getvalue()

    # Build structured results for the template
    across_results = []
    for num in sorted(solver.across, key=lambda x: int(x)):
        key = f'{num}A'
        across_results.append({
            'num':    num,
            'clue':   solver.across[num]['clue'],
            'answer': solver.answers.get(key, '???'),
            'solved': key in solver.answers,
        })

    down_results = []
    for num in sorted(solver.down, key=lambda x: int(x)):
        key = f'{num}D'
        down_results.append({
            'num':    num,
            'clue':   solver.down[num]['clue'],
            'answer': solver.answers.get(key, '???'),
            'solved': key in solver.answers,
        })

    total   = len(across_results) + len(down_results)
    n_solved = sum(1 for r in across_results + down_results if r['solved'])

    return render_template(
        'index.html',
        today        = today,
        cookie       = cookie,
        puzzle_date  = puzzle_date or today,
        grid         = solver.grid.cells,
        across       = across_results,
        down         = down_results,
        log          = log_output,
        total        = total,
        n_solved     = n_solved,
        complete     = solver.grid.is_complete(),
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
