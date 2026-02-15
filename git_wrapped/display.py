"""Beautiful terminal display for git-wrapped using Rich."""

import time
from typing import Dict, List, Tuple, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich.align import Align
from rich import box
from rich.style import Style
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from git_wrapped.analyzer import WrappedStats, MONTH_NAMES

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

ACCENT = "bright_green"
ACCENT2 = "bright_cyan"
ACCENT3 = "bright_magenta"
DIM = "dim"
BOLD = "bold"
TITLE_STYLE = "bold bright_white on rgb(30,60,30)"

# Heatmap color gradient (low → high activity)
HEATMAP_COLORS = [
    "rgb(22,27,34)",     # 0 — no activity (dark)
    "rgb(14,68,41)",     # 1
    "rgb(0,109,50)",     # 2
    "rgb(38,166,65)",    # 3
    "rgb(57,211,83)",    # 4 — high activity
]

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
HOUR_LABELS = [
    "12am", " 1am", " 2am", " 3am", " 4am", " 5am",
    " 6am", " 7am", " 8am", " 9am", "10am", "11am",
    "12pm", " 1pm", " 2pm", " 3pm", " 4pm", " 5pm",
    " 6pm", " 7pm", " 8pm", " 9pm", "10pm", "11pm",
]

MONTH_SHORT = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(value: int, max_value: int, width: int = 30, color: str = ACCENT) -> Text:
    """Render a horizontal bar chart segment."""
    if max_value == 0:
        filled = 0
    else:
        filled = round(value / max_value * width)
    bar_text = Text()
    bar_text.append("█" * filled, style=color)
    bar_text.append("░" * (width - filled), style=DIM)
    return bar_text


def _compact_number(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n:,}"


def _section_pause(animate: bool) -> None:
    if animate:
        time.sleep(0.4)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def _render_header(console: Console, stats: WrappedStats) -> None:
    year_str = str(stats.year) if stats.year else "All Time"
    title_text = Text()
    title_text.append("  G I T   W R A P P E D  ", style="bold bright_white")

    subtitle = Text()
    subtitle.append(f"  {stats.repo_name}  ", style=f"italic {ACCENT2}")
    subtitle.append(f"  {year_str}  ", style=f"bold {ACCENT}")

    panel = Panel(
        Align.center(Text.assemble(title_text, "\n", subtitle)),
        box=box.DOUBLE_EDGE,
        style="bright_green",
        padding=(1, 4),
    )
    console.print()
    console.print(panel)


def _render_overview(console: Console, stats: WrappedStats) -> None:
    net = stats.total_insertions - stats.total_deletions
    net_str = f"+{net:,}" if net >= 0 else f"{net:,}"
    net_color = "green" if net >= 0 else "red"

    days_span = ""
    if stats.first_commit and stats.last_commit:
        span = (stats.last_commit - stats.first_commit).days
        days_span = f"  ({span} days)"

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style=DIM, width=20)
    table.add_column(style=f"bold {ACCENT}", justify="right", width=16)

    table.add_row("Total Commits", f"{stats.total_commits:,}")
    table.add_row("Files Changed", f"{stats.total_files_changed:,}")
    table.add_row("Lines Added", f"[green]+{stats.total_insertions:,}[/green]")
    table.add_row("Lines Deleted", f"[red]-{stats.total_deletions:,}[/red]")
    table.add_row("Net Impact", f"[{net_color}]{net_str} lines[/{net_color}]")
    table.add_row("Active Days", f"{stats.active_days:,}{days_span}")

    console.print(Panel(
        table,
        title="[bold]The Numbers[/bold]",
        title_align="left",
        border_style=ACCENT,
        padding=(1, 2),
    ))


def _render_heatmap(console: Console, stats: WrappedStats) -> None:
    """Render a GitHub-style contribution heatmap (max 52 weeks)."""
    if not stats.daily_counts:
        return

    from datetime import datetime, timedelta

    # Determine available width and max weeks
    term_width = console.width or 80
    # Account for panel border (2), padding (4), day label (4)
    usable = term_width - 10
    MAX_WEEKS = min(52, usable)  # 1 char per week cell

    # Determine date range
    if stats.year:
        start = datetime(stats.year, 1, 1)
        end = datetime(stats.year, 12, 31)
    else:
        all_dates = sorted(stats.daily_counts.keys())
        end = datetime.strptime(all_dates[-1], "%Y-%m-%d")
        start = end - timedelta(weeks=MAX_WEEKS)

    # Align start to Monday
    while start.weekday() != 0:
        start -= timedelta(days=1)
    # Align end to Sunday
    while end.weekday() != 6:
        end += timedelta(days=1)

    # Build grid: rows=7 (Mon-Sun), cols=weeks
    max_count = max(stats.daily_counts.values()) if stats.daily_counts else 1
    thresholds = [0, max_count * 0.25, max_count * 0.50, max_count * 0.75]

    weeks: List[List[Tuple[int, str]]] = []
    current_week: List[Tuple[int, str]] = []
    d = start

    month_markers: List[Tuple[int, str]] = []
    prev_month = -1

    while d <= end:
        ds = d.strftime("%Y-%m-%d")
        count = stats.daily_counts.get(ds, 0)
        current_week.append((count, ds))

        if d.weekday() == 0 and d.month != prev_month:
            month_markers.append((len(weeks), MONTH_SHORT[d.month]))
            prev_month = d.month

        if d.weekday() == 6:
            weeks.append(current_week)
            current_week = []
        d += timedelta(days=1)

    if current_week:
        # Pad to full week
        while len(current_week) < 7:
            current_week.append((0, ""))
        weeks.append(current_week)

    # Color mapping
    def _color_for(count: int) -> str:
        if count == 0:
            return HEATMAP_COLORS[0]
        if count <= thresholds[1]:
            return HEATMAP_COLORS[1]
        if count <= thresholds[2]:
            return HEATMAP_COLORS[2]
        if count <= thresholds[3]:
            return HEATMAP_COLORS[3]
        return HEATMAP_COLORS[4]

    # Month label row — place abbreviated month at the week it starts
    month_row = Text()
    month_row.append("    ")  # padding for day labels
    marker_dict = dict(month_markers)
    col = 0
    for wi in range(len(weeks)):
        if wi in marker_dict and col <= wi:
            label = marker_dict[wi][:3]
            month_row.append(label, style="dim white")
            col = wi + len(label)
        elif col <= wi:
            month_row.append(" ")
            col = wi + 1

    lines = [month_row]

    for row_idx in range(7):
        line = Text()
        label = WEEKDAY_LABELS[row_idx]
        if row_idx % 2 == 0:
            line.append(f"{label} ", style=DIM)
        else:
            line.append("    ")

        for week in weeks:
            if row_idx < len(week):
                count = week[row_idx][0]
                color = _color_for(count)
                line.append("\u2588", style=color)
            else:
                line.append(" ")
        lines.append(line)

    # Legend
    legend = Text()
    legend.append("    Less ", style=DIM)
    for c in HEATMAP_COLORS:
        legend.append("\u2588", style=c)
    legend.append(" More", style=DIM)
    lines.append(Text())
    lines.append(legend)

    content = Text("\n").join(lines)

    console.print(Panel(
        content,
        title="[bold]Activity Heatmap[/bold]",
        title_align="left",
        border_style=ACCENT2,
        padding=(1, 2),
    ))


def _render_time_analysis(console: Console, stats: WrappedStats) -> None:
    """Bar charts for hour-of-day and day-of-week activity."""
    max_hour = max(stats.commits_by_hour.values()) if stats.commits_by_hour else 1
    max_day = max(stats.commits_by_weekday.values()) if stats.commits_by_weekday else 1

    # Hour chart (group into 3-hour blocks for compactness)
    hour_blocks = [
        ("12-3am", sum(stats.commits_by_hour.get(h, 0) for h in range(0, 3))),
        (" 3-6am", sum(stats.commits_by_hour.get(h, 0) for h in range(3, 6))),
        (" 6-9am", sum(stats.commits_by_hour.get(h, 0) for h in range(6, 9))),
        ("9-12pm", sum(stats.commits_by_hour.get(h, 0) for h in range(9, 12))),
        ("12-3pm", sum(stats.commits_by_hour.get(h, 0) for h in range(12, 15))),
        (" 3-6pm", sum(stats.commits_by_hour.get(h, 0) for h in range(15, 18))),
        (" 6-9pm", sum(stats.commits_by_hour.get(h, 0) for h in range(18, 21))),
        ("9-12am", sum(stats.commits_by_hour.get(h, 0) for h in range(21, 24))),
    ]
    max_block = max(v for _, v in hour_blocks) or 1

    lines = []
    header = Text("  Hour of Day\n", style=f"bold {ACCENT2}")
    lines.append(header)

    for label, count in hour_blocks:
        line = Text()
        line.append(f"  {label}  ", style=DIM)
        line.append_text(_bar(count, max_block, width=25, color="bright_cyan"))
        line.append(f"  {count}", style=DIM)
        lines.append(line)

    lines.append(Text())
    lines.append(Text("  Day of Week\n", style=f"bold {ACCENT3}"))

    for day_idx in range(7):
        count = stats.commits_by_weekday.get(day_idx, 0)
        line = Text()
        line.append(f"  {WEEKDAY_LABELS[day_idx]}     ", style=DIM)
        line.append_text(_bar(count, max_day, width=25, color="bright_magenta"))
        line.append(f"  {count}", style=DIM)
        lines.append(line)

    content = Text("\n").join(lines)

    console.print(Panel(
        content,
        title="[bold]When You Code[/bold]",
        title_align="left",
        border_style=ACCENT3,
        padding=(1, 1),
    ))


def _render_top_files(console: Console, stats: WrappedStats) -> None:
    if not stats.top_files:
        return

    table = Table(show_header=True, header_style=f"bold {ACCENT}", box=box.SIMPLE_HEAVY, padding=(0, 1))
    table.add_column("#", style=DIM, width=3)
    table.add_column("File", style="bright_white", max_width=50)
    table.add_column("Changes", justify="right", style=ACCENT)

    medals = ["1st", "2nd", "3rd"]
    for i, (fname, count) in enumerate(stats.top_files[:8]):
        rank = medals[i] if i < 3 else f"{i+1}th"
        table.add_row(rank, fname, str(count))

    console.print(Panel(
        table,
        title="[bold]Your Top Files[/bold]",
        title_align="left",
        border_style="bright_yellow",
        padding=(1, 1),
    ))


def _render_languages(console: Console, stats: WrappedStats) -> None:
    if not stats.languages:
        return

    total = sum(stats.languages.values()) or 1
    max_val = max(stats.languages.values()) or 1

    colors = [
        "bright_cyan", "bright_green", "bright_magenta", "bright_yellow",
        "bright_red", "bright_blue", "cyan", "green", "magenta", "yellow",
    ]

    lines = []
    for i, (lang, count) in enumerate(stats.languages.items()):
        pct = count / total * 100
        color = colors[i % len(colors)]
        line = Text()
        line.append(f"  {lang:<14}", style=f"bold {color}")
        line.append_text(_bar(count, max_val, width=22, color=color))
        line.append(f"  {pct:5.1f}%", style=DIM)
        lines.append(line)

    content = Text("\n").join(lines)

    console.print(Panel(
        content,
        title="[bold]Languages[/bold]",
        title_align="left",
        border_style="bright_blue",
        padding=(1, 1),
    ))


def _render_streaks(console: Console, stats: WrappedStats) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column(style=DIM, width=22)
    table.add_column(style=f"bold {ACCENT}", width=30)

    table.add_row("Longest Streak", f"{stats.longest_streak} days")
    table.add_row("Current Streak", f"{stats.current_streak} days")

    if stats.busiest_day[0]:
        date_str, count = stats.busiest_day
        table.add_row("Busiest Day", f"{date_str}  ({count} commits)")

    if stats.most_productive_month:
        table.add_row("Best Month", stats.most_productive_month)

    console.print(Panel(
        table,
        title="[bold]Streaks & Records[/bold]",
        title_align="left",
        border_style="bright_red",
        padding=(1, 2),
    ))


def _render_personality(console: Console, stats: WrappedStats) -> None:
    lines = []

    # Big personality reveal
    you_are = Text()
    you_are.append("  You are a... ", style=DIM)
    lines.append(you_are)
    lines.append(Text())

    big_name = Text()
    big_name.append(f"    {stats.personality.upper()}", style=f"bold bright_white")
    big_name.append(f"  {stats.personality_emoji}", style="")
    lines.append(big_name)
    lines.append(Text())

    desc = Text()
    desc.append(f'  "{stats.personality_description}"', style="italic bright_white")
    lines.append(desc)

    if stats.traits:
        lines.append(Text())
        lines.append(Text("  Traits:", style=f"bold {ACCENT2}"))
        for emoji, trait in stats.traits:
            t = Text()
            t.append(f"    {emoji} {trait}", style="bright_white")
            lines.append(t)

    content = Text("\n").join(lines)

    console.print(Panel(
        content,
        title="[bold]Your Coder DNA[/bold]",
        title_align="left",
        border_style=ACCENT3,
        padding=(1, 1),
    ))


def _render_fun_facts(console: Console, stats: WrappedStats) -> None:
    facts = []

    if stats.longest_message:
        msg_preview = stats.longest_message[:60]
        if len(stats.longest_message) > 60:
            msg_preview += "..."
        facts.append(f'  Longest commit message: {len(stats.longest_message)} chars — "{msg_preview}"')

    if stats.shortest_message:
        facts.append(f'  Shortest commit message: "{stats.shortest_message}"')

    if stats.holiday_commits:
        for holiday in stats.holiday_commits[:3]:
            facts.append(f"  You committed on {holiday}!")

    if stats.most_productive_month:
        facts.append(f"  Most productive month: {stats.most_productive_month}")

    if stats.active_days and stats.total_commits:
        avg = stats.total_commits / stats.active_days
        facts.append(f"  Avg {avg:.1f} commits per active day")

    if len(stats.authors) > 1:
        facts.append(f"  {len(stats.authors)} contributors to this repo")

    if not facts:
        return

    lines = [Text(f, style="bright_white") for f in facts]
    content = Text("\n").join(lines)

    console.print(Panel(
        content,
        title="[bold]Fun Facts[/bold]",
        title_align="left",
        border_style="bright_yellow",
        padding=(1, 1),
    ))


def _render_footer(console: Console, stats: WrappedStats) -> None:
    year_str = str(stats.year) if stats.year else "all time"
    text = Text()
    text.append(f"\n  Thanks for an amazing {year_str} of coding!", style="bold bright_white")
    text.append(f"\n  {stats.total_commits:,} commits", style=ACCENT)
    text.append(" | ", style=DIM)
    text.append(f"{stats.active_days} active days", style=ACCENT2)
    text.append(" | ", style=DIM)
    text.append(f"+{stats.total_insertions:,}/-{stats.total_deletions:,} lines", style=ACCENT3)
    text.append("\n")
    console.print(text)

    share = Text()
    share.append("  Share your #GitWrapped → ", style=DIM)
    share.append("git-wrapped --json > my-wrapped.json", style="italic bright_cyan")
    share.append("\n", style="")
    console.print(share)


# ---------------------------------------------------------------------------
# Loading animation
# ---------------------------------------------------------------------------

def _show_loading(console: Console) -> None:
    console.print()
    with Progress(
        SpinnerColumn(style=ACCENT),
        TextColumn("[bold bright_white]Analyzing your git history..."),
        BarColumn(bar_width=30, style=ACCENT, complete_style="bright_green"),
        transient=True,
        console=console,
    ) as progress:
        task = progress.add_task("loading", total=100)
        for i in range(100):
            time.sleep(0.008)
            progress.update(task, advance=1)


# ---------------------------------------------------------------------------
# Main display
# ---------------------------------------------------------------------------

def display_wrapped(stats: WrappedStats, animate: bool = True) -> None:
    """Render the full Git Wrapped experience to the terminal."""
    console = Console()

    if animate:
        _show_loading(console)

    _render_header(console, stats)
    _section_pause(animate)

    _render_overview(console, stats)
    _section_pause(animate)

    _render_heatmap(console, stats)
    _section_pause(animate)

    _render_time_analysis(console, stats)
    _section_pause(animate)

    _render_top_files(console, stats)
    _section_pause(animate)

    _render_languages(console, stats)
    _section_pause(animate)

    _render_streaks(console, stats)
    _section_pause(animate)

    _render_personality(console, stats)
    _section_pause(animate)

    _render_fun_facts(console, stats)
    _section_pause(animate)

    _render_footer(console, stats)
