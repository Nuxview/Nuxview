#!/usr/bin/env python3
"""
GitHub Profile Stats & Dev Quote SVG Updater
=============================================
Fetches live data from the GitHub API and regenerates:
  - github-stats.svg   (streak, contributions, repos, followers, languages)
  - dev-quote.svg      (random developer quote)

Usage
-----
  export GITHUB_TOKEN=ghp_...   # optional but required for streak/contributions
  python update.py

Environment variables
---------------------
  GITHUB_USERNAME   GitHub username            (default: Nuxview)
  GITHUB_TOKEN      PAT with read:user scope   (optional; enables GraphQL)

Notes
-----
  - No third-party dependencies: only Python standard library.
  - Requires Python 3.9+.
  - Avatar is embedded as base64 in the SVG.  GitHub's README renderer
    may strip <image> elements; the monogram placeholder will show instead.
    The SVG looks correct when opened locally or served via GitHub Pages.
"""

import base64
import json
import os
import random
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
USERNAME = os.environ.get("GITHUB_USERNAME", "Nuxview")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
SCRIPT_DIR = Path(__file__).parent

# ── Colour palette (all cards share this scheme) ───────────────────────────────
C = {
    "bg": "#0f172a",
    "border": "#1e293b",
    "text_pri": "#e2e8f0",
    "text_mut": "#64748b",
    "text_dim": "#334155",
    "cyan": "#0ea5e9",
    "teal": "#06b6d4",
    "violet": "#a5b4fc",
    "indigo": "#6366f1",
    "mid": "#94a3b8",
    "circle_fill": "#051e2c",
    "avatar_fill": "#0c1a2e",
}

LANG_COLORS = {
    "Python": "#3b82f6",
    "TypeScript": "#06b6d4",
    "JavaScript": "#f59e0b",
    "HTML": "#f97316",
    "CSS": "#a78bfa",
    "Shell": "#10b981",
    "Bash": "#10b981",
    "Rust": "#fb923c",
    "Go": "#0ea5e9",
    "C": "#64748b",
    "C++": "#ef4444",
    "Java": "#f97316",
    "Ruby": "#e11d48",
    "Lua": "#818cf8",
    "Swift": "#f97316",
    "Kotlin": "#a78bfa",
    "Nix": "#818cf8",
    "Makefile": "#475569",
    "Dockerfile": "#0ea5e9",
}
FALLBACK_COLORS = ["#3b82f6", "#475569", "#334155"]

FONT = "JetBrainsMono, 'JetBrains Mono', monospace"

# ── Developer quotes ───────────────────────────────────────────────────────────
QUOTES = [
    (
        "From an artistic standpoint, the best software comes from the realm of intuition.",
        "Bob Carr",
    ),
    (
        "Any fool can write code that a computer can understand. Good programmers write code that humans can understand.",
        "Martin Fowler",
    ),
    ("First, solve the problem. Then, write the code.", "John Johnson"),
    (
        "Perfection is achieved not when there is nothing more to add, but rather when there is nothing more to take away.",
        "Antoine de Saint-Exupéry",
    ),
    (
        "If debugging is the process of removing software bugs, then programming must be the process of putting them in.",
        "Edsger W. Dijkstra",
    ),
    (
        "The most disastrous thing that you can ever learn is your first programming language.",
        "Alan Kay",
    ),
    (
        "The function of good software is to make the complex appear to be simple.",
        "Grady Booch",
    ),
    ("Code is like humor. When you have to explain it, it's bad.", "Cory House"),
    ("Fix the cause, not the symptom.", "Steve Maguire"),
    ("Simplicity is the soul of efficiency.", "Austin Freeman"),
    ("Before software can be reusable it first has to be usable.", "Ralph Johnson"),
    ("Make it work, make it right, make it fast.", "Kent Beck"),
    ("The best error message is the one that never shows up.", "Thomas Fuchs"),
    (
        "Walking on water and developing software from a specification are easy if both are frozen.",
        "Edward V. Berard",
    ),
    (
        "Programs must be written for people to read, and only incidentally for machines to execute.",
        "Harold Abelson",
    ),
    ("The only way to go fast is to go well.", "Robert C. Martin"),
    ("Good code is its own best documentation.", "Steve McConnell"),
    (
        "Always code as if the guy who ends up maintaining your code will be a violent psychopath who knows where you live.",
        "John F. Woods",
    ),
    (
        "Measuring programming progress by lines of code is like measuring aircraft building progress by weight.",
        "Bill Gates",
    ),
    (
        "The most dangerous phrase in the language is 'We've always done it this way.'",
        "Grace Hopper",
    ),
    (
        "One of my most productive days was throwing away 1,000 lines of code.",
        "Ken Thompson",
    ),
    (
        "Debugging is twice as hard as writing the code in the first place.",
        "Brian W. Kernighan",
    ),
    (
        "There are only two kinds of programming languages: those people always bitch about and those nobody uses.",
        "Bjarne Stroustrup",
    ),
    ("The best way to predict the future is to invent it.", "Alan Kay"),
    ("Talk is cheap. Show me the code.", "Linus Torvalds"),
    (
        "Give a man a program, frustrate him for a day. Teach a man to program, frustrate him for a lifetime.",
        "Muhammad Waseem",
    ),
    ("An idiot admires complexity, a genius admires simplicity.", "Terry A. Davis"),
    ("Software is a gas; it expands to fill its container.", "Nathan Myhrvold"),
    (
        "You can't have great software without a great team, and most software teams behave like dysfunctional families.",
        "Jim McCarthy",
    ),
    ("Premature optimisation is the root of all evil.", "Donald Knuth"),
    (
        "It always takes longer than you expect, even when you take into account Hofstadter's Law.",
        "Douglas Hofstadter",
    ),
    (
        "The most important skill in software is the ability to say no when appropriate.",
        "Anonymous",
    ),
    (
        "A language that doesn't affect the way you think about programming is not worth knowing.",
        "Alan Perlis",
    ),
]

# ── Helpers ────────────────────────────────────────────────────────────────────


def xml_esc(text):
    """Escape XML special characters for safe use in SVG text content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def wrap_text(text, max_chars=68):
    """Word-wrap *text* into lines of at most *max_chars* characters."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _http(url, data=None, extra_headers=None):
    """Minimal HTTP helper — returns parsed JSON."""
    headers = {"User-Agent": "nuxview-svg-updater/1.0"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


# ── GitHub data fetchers ───────────────────────────────────────────────────────


def get_user_info():
    """Fetch basic user info from the REST API (no token required)."""
    try:
        d = _http(f"https://api.github.com/users/{USERNAME}")
        return {
            "followers": d.get("followers", 0),
            "public_repos": d.get("public_repos", 0),
            "avatar_url": d.get("avatar_url", ""),
            "since": d.get("created_at", "2023")[:4],
        }
    except Exception as exc:
        print(f"[warn] user info: {exc}")
        return {"followers": 0, "public_repos": 0, "avatar_url": "", "since": "2023"}


def get_contributions_and_streak():
    """
    Return (total_contributions, current_streak, longest_streak) via GraphQL.
    Requires GITHUB_TOKEN.  Returns (0, 0, 0) when no token is set.
    """
    if not TOKEN:
        print("[info] No GITHUB_TOKEN — skipping contribution/streak data.")
        return 0, 0, 0

    query = f"""{{
      user(login: "{USERNAME}") {{
        contributionsCollection {{
          contributionCalendar {{
            totalContributions
            weeks {{
              contributionDays {{
                contributionCount
                date
              }}
            }}
          }}
        }}
      }}
    }}"""

    try:
        result = _http(
            "https://api.github.com/graphql",
            data=json.dumps({"query": query}).encode(),
            extra_headers={"Content-Type": "application/json"},
        )
        cal = result["data"]["user"]["contributionsCollection"]["contributionCalendar"]
        total = cal["totalContributions"]
        days = sorted(
            (d for week in cal["weeks"] for d in week["contributionDays"]),
            key=lambda d: d["date"],
        )

        # Longest streak
        longest = run = 0
        for d in days:
            if d["contributionCount"] > 0:
                run += 1
                longest = max(longest, run)
            else:
                run = 0

        # Current streak (walk backwards from today / yesterday)
        active = {d["date"] for d in days if d["contributionCount"] > 0}
        check = date.today()
        if check.isoformat() not in active:
            check -= timedelta(days=1)
        current = 0
        while check.isoformat() in active:
            current += 1
            check -= timedelta(days=1)

        return total, current, longest

    except Exception as exc:
        print(f"[warn] contributions: {exc}")
        return 0, 0, 0


def get_top_languages(n=5):
    """
    Return [(language, fraction), ...] derived from repo primary languages.
    Uses the REST API — no token required for public repos.
    """
    try:
        repos = _http(
            f"https://api.github.com/users/{USERNAME}/repos?per_page=100&type=owner"
        )
        counts = {}
        for repo in repos:
            lang = repo.get("language")
            if lang:
                counts[lang] = counts.get(lang, 0) + 1
        total = sum(counts.values()) or 1
        top = sorted(counts.items(), key=lambda x: -x[1])[:n]
        return [(lang, cnt / total) for lang, cnt in top]
    except Exception as exc:
        print(f"[warn] languages: {exc}")
        return [("Python", 0.55), ("TypeScript", 0.30)]


def get_avatar_b64(url):
    """Download avatar image and return a base64 data-URI, or None on failure."""
    if not url:
        return None
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "nuxview-svg-updater/1.0"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            ct = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
        b64 = base64.b64encode(raw).decode()
        return f"data:{ct};base64,{b64}"
    except Exception as exc:
        print(f"[warn] avatar download: {exc}")
        return None


# ── SVG builders ───────────────────────────────────────────────────────────────


def make_stats_svg(
    user_info, total, current_streak, longest_streak, top_langs, avatar_b64
):
    """Generate and return the github-stats SVG as a string."""

    today = date.today()
    date_str = f"{today.month}/{today.day}/{today.year}"
    since = user_info["since"]
    repos = str(user_info["public_repos"])
    followers = str(user_info["followers"])

    def fmt(n, suffix=""):
        return f"{n:,}{suffix}" if n else "\u2014"  # em-dash when zero/unknown

    total_str = fmt(total)
    longest_str = fmt(longest_streak, " days")
    streak_num = str(current_streak) if current_streak else "\u2014"

    # Avatar element
    if avatar_b64:
        avatar_el = (
            f'<image href="{avatar_b64}" x="35" y="37" width="86" height="86" '
            f'clip-path="url(#avatarClip)" preserveAspectRatio="xMidYMid slice"/>'
        )
        avatar_label = "Embedded"
    else:
        initial = xml_esc(USERNAME[0].upper())
        avatar_el = (
            f'<circle cx="78" cy="80" r="43" fill="{C["avatar_fill"]}"/>'
            f'<text x="78" y="89" text-anchor="middle" fill="{C["cyan"]}" '
            f'font-family="{FONT}" font-size="28" font-weight="700">{initial}</text>'
        )
        avatar_label = "Placeholder"

    # Language bar  (x 367–838 = 471 px)
    BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 367, 471, 162, 7, 2
    avail = BAR_W - (len(top_langs) - 1) * GAP
    bars = []
    cursor = BAR_X
    for i, (lang, frac) in enumerate(top_langs):
        w = max(int(frac * avail), 4)
        color = LANG_COLORS.get(lang, FALLBACK_COLORS[i % len(FALLBACK_COLORS)])
        bars.append(
            f'<rect x="{cursor}" y="{BAR_Y}" width="{w}" height="{BAR_H}" rx="3" fill="{color}"/>'
        )
        cursor += w + GAP
    lang_bar = "\n  ".join(bars)
    lang_names = xml_esc(" \u2022 ".join(l[0] for l in top_langs[:3]))

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="860" height="195" viewBox="0 0 860 195">
  <defs>
    <style>@font-face {{ src: local('JetBrains Mono'); font-family: JetBrainsMono; font-display: swap; }}</style>
    <clipPath id="avatarClip"><circle cx="78" cy="80" r="43"/></clipPath>
  </defs>

  <!-- Background -->
  <rect width="860" height="195" rx="14" fill="{C["bg"]}"/>
  <rect width="860" height="195" rx="14" fill="none" stroke="{C["border"]}" stroke-width="1.5"/>

  <!-- Fire -->
  <text x="836" y="38" text-anchor="middle" font-family="serif" font-size="20">&#x1F525;</text>

  <!-- Avatar rings -->
  <circle cx="78" cy="80" r="50" fill="none" stroke="{C["cyan"]}" stroke-width="1.5" opacity="0.3"/>
  <circle cx="78" cy="80" r="46" fill="none" stroke="{C["cyan"]}" stroke-width="2.5"/>
  {avatar_el}

  <!-- Username / Since -->
  <text x="78" y="149" text-anchor="middle" fill="{C["text_pri"]}"
        font-family="{FONT}" font-size="14" font-weight="700">{xml_esc(USERNAME)}</text>
  <text x="78" y="166" text-anchor="middle" fill="{C["text_mut"]}"
        font-family="{FONT}" font-size="11">Since {since}</text>

  <!-- Divider 1 -->
  <line x1="165" y1="20" x2="165" y2="175" stroke="{C["border"]}" stroke-width="1.5"/>

  <!-- Streak circle -->
  <circle cx="252" cy="82" r="58" fill="{C["cyan"]}" fill-opacity="0.05"/>
  <circle cx="252" cy="82" r="52" fill="{C["circle_fill"]}" stroke="{C["cyan"]}" stroke-width="2.5"/>
  <text x="252" y="76" text-anchor="middle" fill="{C["cyan"]}"
        font-family="{FONT}" font-size="30" font-weight="700">{xml_esc(streak_num)}</text>
  <text x="252" y="97" text-anchor="middle" fill="{C["mid"]}"
        font-family="{FONT}" font-size="12">days</text>
  <text x="252" y="152" text-anchor="middle" fill="{C["cyan"]}"
        font-family="{FONT}" font-size="12" font-weight="600">Current Streak</text>

  <!-- Divider 2 -->
  <line x1="340" y1="20" x2="340" y2="175" stroke="{C["border"]}" stroke-width="1.5"/>

  <!-- Total Contributions -->
  <text x="367" y="48" fill="{C["text_mut"]}" font-family="{FONT}" font-size="11">Total Contributions</text>
  <text x="367" y="72" fill="{C["cyan"]}"     font-family="{FONT}" font-size="22" font-weight="700">{xml_esc(total_str)}</text>

  <!-- Longest Streak -->
  <text x="620" y="48" fill="{C["text_mut"]}" font-family="{FONT}" font-size="11">Longest Streak</text>
  <text x="620" y="72" fill="{C["teal"]}"     font-family="{FONT}" font-size="22" font-weight="700">{xml_esc(longest_str)}</text>

  <!-- Repositories -->
  <text x="367" y="104" fill="{C["text_mut"]}"  font-family="{FONT}" font-size="11">Repositories</text>
  <text x="367" y="128" fill="{C["text_pri"]}"  font-family="{FONT}" font-size="22" font-weight="700">{repos}</text>

  <!-- Followers -->
  <text x="620" y="104" fill="{C["text_mut"]}"  font-family="{FONT}" font-size="11">Followers</text>
  <text x="620" y="128" fill="{C["text_pri"]}"  font-family="{FONT}" font-size="22" font-weight="700">{followers}</text>

  <!-- Top Languages label + names -->
  <text x="367" y="153" fill="{C["text_mut"]}" font-family="{FONT}" font-size="11">Top Languages</text>
  <text x="838" y="153" text-anchor="end" fill="{C["text_pri"]}"
        font-family="{FONT}" font-size="11" font-weight="600">{lang_names}</text>

  <!-- Language bar -->
  {lang_bar}

  <!-- Footer -->
  <text x="18" y="188" fill="{C["text_dim"]}" font-family="{FONT}" font-size="10">Updated: {date_str} &#x2022; Avatar: {avatar_label}</text>
</svg>'''


def make_quote_svg(quote, author):
    """Generate and return the dev-quote SVG as a string."""

    W = 860
    FONT_SIZE = 14
    LINE_H = 26
    FIRST_Y = 62  # baseline of first text line
    AUTHOR_GAP = 42  # px below last text line to author baseline
    BOTTOM_PAD = 20
    TEXT_X = 52  # left edge of quote text (indent past the big " mark)
    MAX_CHARS = 68

    lines = wrap_text(quote, MAX_CHARS)
    last_y = FIRST_Y + (len(lines) - 1) * LINE_H
    auth_y = last_y + AUTHOR_GAP
    H = auth_y + BOTTOM_PAD

    tspans = ""
    for i, line in enumerate(lines):
        y = FIRST_Y + i * LINE_H
        tspans += f'\n    <tspan x="{TEXT_X}" y="{y}">{xml_esc(line)}</tspan>'

    # Closing " appended to final tspan
    tspans = tspans.rstrip()
    # add closing quote entity to last tspan inline
    last_open = tspans.rfind("<tspan")
    last_close = tspans.rfind("</tspan>")
    tspans = tspans[:last_close] + "&#x201D;" + tspans[last_close:]

    quote_mark_y = FIRST_Y + 16  # sits just above the text block

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     width="{W}" height="{H}" viewBox="0 0 {W} {H}">
  <defs>
    <style>@font-face {{ src: local('JetBrains Mono'); font-family: JetBrainsMono; font-display: swap; }}</style>
  </defs>

  <!-- Background -->
  <rect width="{W}" height="{H}" rx="12" fill="{C["bg"]}"/>
  <rect width="{W}" height="{H}" rx="12" fill="none" stroke="{C["border"]}" stroke-width="1.5"/>

  <!-- Decorative opening quote mark -->
  <text x="24" y="{quote_mark_y}" font-family="Georgia, 'Times New Roman', serif"
        font-size="54" fill="{C["indigo"]}" opacity="0.85">&#x201C;</text>

  <!-- Quote text (italic) -->
  <text font-family="{FONT}" font-size="{FONT_SIZE}" font-style="italic" fill="{C["violet"]}">{tspans}
  </text>

  <!-- Author -->
  <text x="{W - 24}" y="{auth_y}" text-anchor="end"
        font-family="{FONT}" font-size="12" fill="{C["text_mut"]}">- {xml_esc(author)}</text>
</svg>'''


# ── Main ───────────────────────────────────────────────────────────────────────


def main():
    print(f"Fetching data for @{USERNAME} …")

    user_info = get_user_info()
    total, current, longest = get_contributions_and_streak()
    top_langs = get_top_languages()
    avatar_b64 = get_avatar_b64(user_info["avatar_url"])
    quote_text, author = random.choice(QUOTES)

    stats_svg = make_stats_svg(
        user_info, total, current, longest, top_langs, avatar_b64
    )
    quote_svg = make_quote_svg(quote_text, author)

    (SCRIPT_DIR / "github-stats.svg").write_text(stats_svg, encoding="utf-8")
    (SCRIPT_DIR / "dev-quote.svg").write_text(quote_svg, encoding="utf-8")

    print(
        f"  ✓ github-stats.svg  — streak={current}, total={total}, repos={user_info['public_repos']}"
    )
    print(f'  ✓ dev-quote.svg     — "{quote_text[:55]}…"')
    print(f"    — {author}")


if __name__ == "__main__":
    main()
