"""Merge the contribution calendars of several GitHub accounts and render SVGs.

Only per-day counts are used (the same anonymous numbers shown on each public profile).
Standard library only. Usage:
    GITHUB_TOKEN=... python3 render_graph.py OUT_DIR USER1 [USER2 ...]
Writes heatmap-{dark,light}.svg and snake-{dark,light}.svg into OUT_DIR.
"""
import datetime as dt
import json
import os
import sys
import urllib.request

QUERY = """
query($u:String!,$from:DateTime!,$to:DateTime!){
  user(login:$u){contributionsCollection(from:$from,to:$to){
    contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}
"""

CELL, GAP, PAD_L, PAD_T = 11, 3, 34, 22
STEP = CELL + GAP

THEMES = {
    "dark": {"bg": "#0d1117", "text": "#8b949e", "levels": ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"], "snake": "#a371f7", "head": "#d2a8ff"},
    "light": {"bg": "#ffffff", "text": "#57606a", "levels": ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"], "snake": "#8250df", "head": "#6639ba"},
}


def fetch(user, start, end, token):
    body = json.dumps({"query": QUERY, "variables": {"u": user, "from": start.isoformat() + "T00:00:00Z", "to": end.isoformat() + "T23:59:59Z"}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql", data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": "profile-graph"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "errors" in data:
        sys.exit(f"GraphQL error for {user}: {data['errors']}")
    out = {}
    for w in data["data"]["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
        for d in w["contributionDays"]:
            out[d["date"]] = d["contributionCount"]
    return out


def level_fn(counts):
    nz = sorted(c for c in counts if c > 0)
    if not nz:
        return lambda c: 0
    q = [nz[int(len(nz) * p)] for p in (0.25, 0.5, 0.75)]
    return lambda c: 0 if c == 0 else 1 + sum(c > t for t in q) if c > q[0] else 1


def grid(merged, end):
    # 53 week columns, Sunday-first rows, ending with the week containing `end`.
    end_week_start = end - dt.timedelta(days=(end.weekday() + 1) % 7)
    first = end_week_start - dt.timedelta(weeks=52)
    cells = []
    for col in range(53):
        for row in range(7):
            day = first + dt.timedelta(weeks=col, days=row)
            if day > end:
                continue
            cells.append((col, row, day, merged.get(day.isoformat(), 0)))
    return cells


def header(width, height, th):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
            f'<rect width="{width}" height="{height}" rx="10" fill="{th["bg"]}"/>')


def month_labels(cells, th):
    out, seen = [], None
    for col, row, day, _ in cells:
        if row == 0 and day.month != seen:
            seen = day.month
            out.append(f'<text x="{PAD_L + col * STEP}" y="14" font-size="10" fill="{th["text"]}" font-family="sans-serif">{day.strftime("%b")}</text>')
    return "".join(out)


def heatmap(cells, th, lvl):
    w, h = PAD_L + 53 * STEP + 12, PAD_T + 7 * STEP + 14
    parts = [header(w, h, th), month_labels(cells, th)]
    for col, row, day, c in cells:
        parts.append(f'<rect x="{PAD_L + col * STEP}" y="{PAD_T + row * STEP}" width="{CELL}" height="{CELL}" rx="2" fill="{th["levels"][lvl(c)]}"/>')
    parts.append("</svg>")
    return "".join(parts)


def snake(cells, th, lvl, seconds_per_cell=0.06, length=5):
    # Zigzag path through the grid column by column; cells vanish as the snake passes.
    by_pos = {(c, r): (d, n) for c, r, d, n in cells}
    path = []
    for col in range(53):
        rows = range(7) if col % 2 == 0 else range(6, -1, -1)
        path += [(col, r) for r in rows if (col, r) in by_pos]
    n = len(path)
    total = n * seconds_per_cell
    idx = {p: i for i, p in enumerate(path)}
    w, h = PAD_L + 53 * STEP + 12, PAD_T + 7 * STEP + 14
    css = [f".s{{animation:run {total:.2f}s linear infinite}}"]
    parts = [header(w, h, th), month_labels(cells, th)]
    for (col, row), (day, c) in by_pos.items():
        x, y = PAD_L + col * STEP, PAD_T + row * STEP
        base, l = th["levels"][0], lvl(c)
        if l == 0:
            parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{base}"/>')
            continue
        pct = idx[(col, row)] / n * 100
        css.append(f"@keyframes e{idx[(col, row)]}{{0%,{pct:.2f}%{{fill:{th['levels'][l]}}}{pct + 0.01:.2f}%,100%{{fill:{base}}}}}")
        parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="2" fill="{th["levels"][l]}" style="animation:e{idx[(col, row)]} {total:.2f}s linear infinite"/>')
    # one keyframe track for the head; body segments follow with negative delays
    kf = ["@keyframes run{"]
    for i, (col, row) in enumerate(path):
        kf.append(f"{i / n * 100:.3f}%{{transform:translate({PAD_L + col * STEP}px,{PAD_T + row * STEP}px)}}")
    kf.append(f"100%{{transform:translate({PAD_L + path[-1][0] * STEP}px,{PAD_T + path[-1][1] * STEP}px)}}}}")
    css += kf
    for k in range(length):
        colr = th["head"] if k == 0 else th["snake"]
        size = CELL if k == 0 else CELL - 2
        off = (CELL - size) / 2
        parts.append(f'<rect class="s" x="{off}" y="{off}" width="{size}" height="{size}" rx="3" fill="{colr}" style="animation-delay:-{(total - k * seconds_per_cell * 1.0) % total:.2f}s"/>')
    parts.insert(1, "<style>" + "".join(css) + "</style>")
    parts.append("</svg>")
    return "".join(parts)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out_dir, users = sys.argv[1], sys.argv[2:]
    token = os.environ.get("GITHUB_TOKEN") or sys.exit("GITHUB_TOKEN required")
    end = dt.date.today()
    start = end - dt.timedelta(days=364)
    merged = {}
    for u in users:
        for day, c in fetch(u, start, end, token).items():
            merged[day] = merged.get(day, 0) + c
    cells = grid(merged, end)
    lvl = level_fn([c for _, _, _, c in cells])
    os.makedirs(out_dir, exist_ok=True)
    for name, th in THEMES.items():
        for kind, fn in (("heatmap", heatmap), ("snake", snake)):
            with open(os.path.join(out_dir, f"{kind}-{name}.svg"), "w", encoding="utf-8") as f:
                f.write(fn(cells, th, lvl))
    print(f"total merged contributions: {sum(c for _, _, _, c in cells)}; wrote SVGs to {out_dir}")


if __name__ == "__main__":
    main()
