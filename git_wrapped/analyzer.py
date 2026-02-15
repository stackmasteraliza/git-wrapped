"""Git history analyzer — parses git log and computes wrapped statistics."""

import subprocess
import re
from datetime import datetime, timedelta, date as date_type
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set

# ---------------------------------------------------------------------------
# Language detection by file extension
# ---------------------------------------------------------------------------

EXTENSION_LANGUAGES: Dict[str, str] = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".mts": "TypeScript",
    ".jsx": "React JSX", ".tsx": "React TSX",
    ".java": "Java",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".c": "C", ".h": "C/C++",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++",
    ".cs": "C#",
    ".swift": "Swift",
    ".kt": "Kotlin", ".kts": "Kotlin",
    ".scala": "Scala",
    ".r": "R", ".R": "R",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell",
    ".html": "HTML", ".htm": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".sass": "Sass", ".less": "Less",
    ".sql": "SQL",
    ".yaml": "YAML", ".yml": "YAML",
    ".json": "JSON",
    ".xml": "XML",
    ".md": "Markdown", ".mdx": "Markdown",
    ".toml": "TOML",
    ".lua": "Lua",
    ".dart": "Dart",
    ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".ml": "OCaml",
    ".clj": "Clojure",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".tf": "Terraform",
    ".proto": "Protobuf",
    ".graphql": "GraphQL", ".gql": "GraphQL",
    ".dockerfile": "Docker",
}

# Files that imply a language regardless of extension
SPECIAL_FILES: Dict[str, str] = {
    "Dockerfile": "Docker",
    "Makefile": "Make",
    "CMakeLists.txt": "CMake",
    "Vagrantfile": "Ruby",
    "Gemfile": "Ruby",
    "Rakefile": "Ruby",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Commit:
    hash: str
    author: str
    email: str
    date: datetime
    message: str
    files: List[Tuple[int, int, str]] = field(default_factory=list)


@dataclass
class WrappedStats:
    # Core numbers
    total_commits: int = 0
    total_files_changed: int = 0
    total_insertions: int = 0
    total_deletions: int = 0

    # Date range
    first_commit: Optional[datetime] = None
    last_commit: Optional[datetime] = None
    active_days: int = 0

    # Time patterns  (hour 0‑23, weekday 0=Mon, month 1‑12)
    commits_by_hour: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    commits_by_weekday: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    commits_by_month: Dict[int, int] = field(default_factory=lambda: defaultdict(int))
    daily_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # Top items
    top_files: List[Tuple[str, int]] = field(default_factory=list)
    languages: Dict[str, int] = field(default_factory=dict)

    # Streaks
    longest_streak: int = 0
    current_streak: int = 0
    busiest_day: Tuple[str, int] = ("", 0)

    # Fun stats
    longest_message: str = ""
    shortest_message: str = ""
    avg_message_length: float = 0.0
    holiday_commits: List[str] = field(default_factory=list)
    most_productive_month: str = ""

    # Personality
    personality: str = ""
    personality_emoji: str = ""
    personality_description: str = ""
    traits: List[Tuple[str, str]] = field(default_factory=list)

    # Authors
    authors: Dict[str, int] = field(default_factory=dict)

    # Meta
    year: Optional[int] = None
    repo_name: str = ""


# ---------------------------------------------------------------------------
# Notable dates (for fun‑fact detection)
# ---------------------------------------------------------------------------

HOLIDAYS: Dict[str, str] = {
    "01-01": "New Year's Day",
    "02-14": "Valentine's Day",
    "03-17": "St. Patrick's Day",
    "04-01": "April Fools' Day",
    "07-04": "Independence Day",
    "10-31": "Halloween",
    "12-25": "Christmas",
    "12-31": "New Year's Eve",
}

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


# ---------------------------------------------------------------------------
# Git log parsing
# ---------------------------------------------------------------------------

_COMMIT_PREFIX = ">>>GW:"

def _run_git(args: List[str], cwd: str) -> str:
    """Run a git command and return stdout."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "git is not installed or not in your PATH. "
            "Install git and try again."
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("git command timed out — is the repository very large?")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "not a git repository" in stderr:
            raise RuntimeError(
                f"'{cwd}' is not a git repository. "
                "Run git-wrapped inside a repo or use --path."
            )
        raise RuntimeError(f"git error: {stderr}")
    return result.stdout


def parse_git_log(
    repo_path: str = ".",
    year: Optional[int] = None,
    author: Optional[str] = None,
) -> List[Commit]:
    """Parse git log and return a list of Commit objects."""

    fmt = f"{_COMMIT_PREFIX}%H%x00%an%x00%ae%x00%aI%x00%s"
    cmd = ["log", f"--format={fmt}", "--numstat", "--no-merges"]

    if year:
        cmd += [f"--after={year}-01-01", f"--before={year + 1}-01-01"]
    if author:
        cmd += ["--author", author]

    raw = _run_git(cmd, cwd=repo_path)
    if not raw.strip():
        return []

    commits: List[Commit] = []
    current: Optional[Commit] = None

    for line in raw.splitlines():
        if line.startswith(_COMMIT_PREFIX):
            if current is not None:
                commits.append(current)

            payload = line[len(_COMMIT_PREFIX):]
            parts = payload.split("\x00", 4)
            if len(parts) < 5:
                current = None
                continue

            sha, name, email, datestr, message = parts
            try:
                dt = datetime.fromisoformat(datestr)
            except ValueError:
                current = None
                continue

            current = Commit(
                hash=sha, author=name, email=email, date=dt, message=message
            )
            continue

        # numstat line: "10\t5\tfilename"
        if current is not None and "\t" in line:
            parts = line.split("\t", 2)
            if len(parts) == 3:
                try:
                    adds = int(parts[0]) if parts[0] != "-" else 0
                    dels = int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    continue
                current.files.append((adds, dels, parts[2]))

    if current is not None:
        commits.append(current)

    return commits


def _detect_language(filename: str) -> Optional[str]:
    """Detect programming language from filename."""
    basename = Path(filename).name
    if basename in SPECIAL_FILES:
        return SPECIAL_FILES[basename]
    ext = Path(filename).suffix.lower()
    return EXTENSION_LANGUAGES.get(ext)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _calculate_streaks(stats: WrappedStats, all_dates: Set[str]) -> None:
    if not all_dates:
        return

    date_objects = sorted(
        datetime.strptime(d, "%Y-%m-%d").date() for d in all_dates
    )

    # Longest streak
    longest = current = 1
    for i in range(1, len(date_objects)):
        if (date_objects[i] - date_objects[i - 1]).days == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    stats.longest_streak = longest

    # Current streak (from today backwards)
    today = date_type.today()
    streak = 0
    check = today
    # Allow a 1‑day gap (today might not have commits yet)
    if check.strftime("%Y-%m-%d") not in all_dates:
        check -= timedelta(days=1)
    while check.strftime("%Y-%m-%d") in all_dates:
        streak += 1
        check -= timedelta(days=1)
    stats.current_streak = streak


def _detect_holidays(daily_counts: Dict[str, int]) -> List[str]:
    found = []
    for date_str in daily_counts:
        md = date_str[5:]  # "MM-DD"
        if md in HOLIDAYS:
            found.append(HOLIDAYS[md])
    return found


def _determine_personality(stats: WrappedStats, commits: List[Commit]) -> None:
    total = stats.total_commits or 1

    # Time buckets
    night = sum(stats.commits_by_hour.get(h, 0) for h in list(range(22, 24)) + list(range(0, 5)))
    morning = sum(stats.commits_by_hour.get(h, 0) for h in range(5, 12))
    evening = sum(stats.commits_by_hour.get(h, 0) for h in range(17, 22))

    night_pct = night / total
    morning_pct = morning / total

    weekend = stats.commits_by_weekday.get(5, 0) + stats.commits_by_weekday.get(6, 0)
    weekend_pct = weekend / total

    # Primary personality
    if night_pct > 0.30:
        stats.personality = "Night Owl"
        stats.personality_emoji = "\U0001f989"
        peak = max(range(20, 24), key=lambda h: stats.commits_by_hour.get(h, 0))
        stats.personality_description = (
            f"While others sleep, you ship code. "
            f"{night_pct:.0%} of your commits land after 10 PM. "
            f"Peak hour: {peak}:00."
        )
    elif morning_pct > 0.45:
        stats.personality = "Early Bird"
        stats.personality_emoji = "\U0001f426"
        stats.personality_description = (
            f"You catch the worm! {morning_pct:.0%} of your commits "
            f"are shipped before noon."
        )
    elif weekend_pct > 0.30:
        stats.personality = "Weekend Warrior"
        stats.personality_emoji = "\u2694\ufe0f"
        stats.personality_description = (
            f"Weekends are for coding! {weekend_pct:.0%} of your "
            f"commits happen on Saturday & Sunday."
        )
    elif stats.longest_streak >= 14:
        stats.personality = "Streak Master"
        stats.personality_emoji = "\U0001f525"
        stats.personality_description = (
            f"Your incredible {stats.longest_streak}-day commit streak "
            f"shows legendary dedication."
        )
    elif stats.total_insertions > stats.total_deletions * 3:
        stats.personality = "Feature Machine"
        stats.personality_emoji = "\U0001f680"
        stats.personality_description = (
            f"You're a builder! {stats.total_insertions:,} lines added "
            f"vs {stats.total_deletions:,} deleted."
        )
    elif stats.total_deletions > stats.total_insertions * 0.7:
        stats.personality = "Code Surgeon"
        stats.personality_emoji = "\u2702\ufe0f"
        stats.personality_description = (
            f"Less is more. You removed {stats.total_deletions:,} lines — "
            f"cleaning up the codebase one commit at a time."
        )
    else:
        stats.personality = "Balanced Builder"
        stats.personality_emoji = "\u2696\ufe0f"
        stats.personality_description = (
            "You strike the perfect balance between building new features "
            "and keeping the codebase clean."
        )

    # Traits
    traits: List[Tuple[str, str]] = []

    avg_files = stats.total_files_changed / total
    if avg_files > 5:
        traits.append(("\U0001f3d7\ufe0f", f"Big Changer — avg {avg_files:.1f} files/commit"))
    elif avg_files < 2:
        traits.append(("\U0001f3af", f"Surgical Committer — avg {avg_files:.1f} files/commit"))

    if stats.avg_message_length > 60:
        traits.append(("\U0001f4dd", f"Storyteller — avg {stats.avg_message_length:.0f}-char messages"))
    elif stats.avg_message_length < 15:
        traits.append(("\u26a1", f"Terse Messenger — avg {stats.avg_message_length:.0f}-char messages"))

    if stats.longest_streak >= 7:
        traits.append(("\U0001f525", f"On Fire — {stats.longest_streak}-day commit streak"))

    if weekend_pct > 0.15:
        traits.append(("\U0001f3e0", f"Weekend Coder — {weekend_pct:.0%} on Sat/Sun"))

    # File-pattern traits
    md_count = sum(c for f, c in stats.top_files if f.endswith((".md", ".mdx", ".rst")))
    test_count = sum(c for f, c in stats.top_files if "test" in f.lower() or "spec" in f.lower())

    if md_count > total * 0.08:
        traits.append(("\U0001f4da", "Documentation Hero"))
    if test_count > total * 0.10:
        traits.append(("\U0001f9ea", "Test Champion"))

    stats.traits = traits[:6]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze(
    repo_path: str = ".",
    year: Optional[int] = None,
    author: Optional[str] = None,
) -> WrappedStats:
    """Analyze a git repository and return WrappedStats."""

    # Resolve repo name
    try:
        origin = _run_git(["remote", "get-url", "origin"], cwd=repo_path).strip()
        repo_name = Path(origin.rstrip(".git")).stem
    except RuntimeError:
        repo_name = Path(repo_path).resolve().name

    commits = parse_git_log(repo_path, year=year, author=author)
    if not commits:
        raise ValueError(
            "No commits found. Check --year and --author filters, "
            "or make sure you're inside a git repository."
        )

    stats = WrappedStats(repo_name=repo_name, year=year)
    stats.total_commits = len(commits)

    file_counter: Counter = Counter()
    lang_counter: Counter = Counter()
    msg_lengths: List[Tuple[int, str]] = []
    all_dates: Set[str] = set()
    author_counter: Counter = Counter()

    for commit in commits:
        stats.commits_by_hour[commit.date.hour] += 1
        stats.commits_by_weekday[commit.date.weekday()] += 1
        stats.commits_by_month[commit.date.month] += 1

        ds = commit.date.strftime("%Y-%m-%d")
        stats.daily_counts[ds] += 1
        all_dates.add(ds)

        author_counter[commit.author] += 1

        for adds, dels, fname in commit.files:
            stats.total_insertions += adds
            stats.total_deletions += dels
            file_counter[fname] += 1

            lang = _detect_language(fname)
            if lang:
                lang_counter[lang] += adds + dels

        stats.total_files_changed += len(commit.files)
        msg_lengths.append((len(commit.message), commit.message))

    # Dates
    stats.first_commit = min(c.date for c in commits)
    stats.last_commit = max(c.date for c in commits)
    stats.active_days = len(all_dates)

    # Top files
    stats.top_files = file_counter.most_common(10)

    # Languages
    stats.languages = dict(lang_counter.most_common(10))

    # Authors
    stats.authors = dict(author_counter.most_common(10))

    # Messages
    if msg_lengths:
        msg_lengths.sort(key=lambda x: x[0])
        stats.shortest_message = msg_lengths[0][1]
        stats.longest_message = msg_lengths[-1][1]
        stats.avg_message_length = sum(m[0] for m in msg_lengths) / len(msg_lengths)

    # Busiest day
    if stats.daily_counts:
        bd = max(stats.daily_counts.items(), key=lambda x: x[1])
        stats.busiest_day = bd

    # Most productive month
    if stats.commits_by_month:
        best_month = max(stats.commits_by_month, key=stats.commits_by_month.get)  # type: ignore[arg-type]
        stats.most_productive_month = MONTH_NAMES[best_month]

    # Streaks
    _calculate_streaks(stats, all_dates)

    # Holidays
    stats.holiday_commits = _detect_holidays(stats.daily_counts)

    # Personality
    _determine_personality(stats, commits)

    return stats
