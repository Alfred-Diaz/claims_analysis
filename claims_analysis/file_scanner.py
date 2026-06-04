"""Automatic file scanner for Claims Analysis.

Expected raw folder examples:
    data/raw/Claims Process_20260604.csv
    data/raw/Check Date Created_20260604.csv

The scanner pairs files by date-like tokens in the filename. If no date token is
found, it pairs the newest Claims Process file with the newest Check Date Created
file.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from datetime import datetime
import re
import shutil

from claims_analysis.analyzer import AnalysisConfig, run_analysis


DATE_PATTERN = re.compile(r"(20\d{2}[-_]?\d{2}[-_]?\d{2})")


@dataclass
class FilePair:
    claims_file: Path
    checks_file: Path
    pair_key: str


def normalize_name(path: Path) -> str:
    return path.stem.lower().replace("_", " ").replace("-", " ")


def extract_pair_key(path: Path) -> str:
    match = DATE_PATTERN.search(path.name)
    if match:
        return match.group(1).replace("-", "").replace("_", "")
    return "latest"


def is_claims_file(path: Path) -> bool:
    name = normalize_name(path)
    return "claims process" in name and path.suffix.lower() == ".csv"


def is_checks_file(path: Path) -> bool:
    name = normalize_name(path)
    return "check date created" in name and path.suffix.lower() == ".csv"


def discover_pairs(raw_dir: str | Path = "data/raw") -> list[FilePair]:
    raw_path = Path(raw_dir)
    raw_path.mkdir(parents=True, exist_ok=True)

    claims_files = sorted(
        [path for path in raw_path.iterdir() if path.is_file() and is_claims_file(path)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    checks_files = sorted(
        [path for path in raw_path.iterdir() if path.is_file() and is_checks_file(path)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    claims_by_key: dict[str, Path] = {}
    checks_by_key: dict[str, Path] = {}

    for file_path in claims_files:
        claims_by_key.setdefault(extract_pair_key(file_path), file_path)

    for file_path in checks_files:
        checks_by_key.setdefault(extract_pair_key(file_path), file_path)

    pairs: list[FilePair] = []
    for key in sorted(set(claims_by_key) & set(checks_by_key)):
        pairs.append(FilePair(claims_by_key[key], checks_by_key[key], key))

    if not pairs and claims_files and checks_files:
        pairs.append(FilePair(claims_files[0], checks_files[0], "latest"))

    return pairs


def archive_files(pair: FilePair, archive_root: str | Path = "archive") -> Path:
    now = datetime.now()
    archive_dir = Path(archive_root) / now.strftime("%Y") / now.strftime("%m") / pair.pair_key
    archive_dir.mkdir(parents=True, exist_ok=True)

    shutil.move(str(pair.claims_file), archive_dir / pair.claims_file.name)
    shutil.move(str(pair.checks_file), archive_dir / pair.checks_file.name)
    return archive_dir


def run_next_pair(
    raw_dir: str | Path = "data/raw",
    archive_root: str | Path = "archive",
    output_root: str | Path = "reports/history",
    amount_column: str = "amount",
    fuzzy_threshold: int = 80,
    archive_after_run: bool = True,
) -> Path:
    pairs = discover_pairs(raw_dir)
    if not pairs:
        raise FileNotFoundError(
            "No matching file pair found. Expected CSV files containing "
            "'Claims Process' and 'Check Date Created' in data/raw."
        )

    pair = pairs[0]
    config = AnalysisConfig(amount_column=amount_column, fuzzy_threshold=fuzzy_threshold)
    run_dir = run_analysis(
        claims_path=pair.claims_file,
        checks_path=pair.checks_file,
        output_root=output_root,
        config=config,
    )

    if archive_after_run:
        archive_files(pair, archive_root=archive_root)

    return run_dir
