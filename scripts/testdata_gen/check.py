"""Verify that the committed testdata files are exactly what the generator produces.

Used by `generate_testdata.py --check` and by CI, so a hand-edit to a `testdata/*.jsonl` file or a
change to a generator module that was never re-run shows up as a failure rather than as a silent
drift between the generator and the catalog.
"""
import os

from common import PROJECT_ROOT


def first_difference(actual, expected):
    """The 1-based line number where two line lists diverge, or None when they match."""
    for i, (a, e) in enumerate(zip(actual, expected), start=1):
        if a != e:
            return i
    if len(actual) != len(expected):
        return min(len(actual), len(expected)) + 1
    return None


def compare(tables, root=PROJECT_ROOT):
    """Return (missing, stale) for the files the generator owns."""
    missing, stale = [], []
    for stem, rel in tables.paths.items():
        expected = tables.ordered_lines(stem)
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            missing.append(rel)
            continue
        with open(path) as handle:
            actual = [line.rstrip("\n") for line in handle if line.strip()]
        if actual != expected:
            stale.append((rel, first_difference(actual, expected), len(actual), len(expected)))
    return missing, stale


def run(tables, root=PROJECT_ROOT):
    """Print the verdict and return the process exit code."""
    missing, stale = compare(tables, root)
    for rel in missing:
        print(f"MISSING  {rel}")
    for rel, line, have, want in stale:
        print(f"STALE    {rel}  (differs at line {line}; {have} rows on disk, {want} expected)")
    if missing or stale:
        print(f"\n{len(missing) + len(stale)} of {len(tables.paths)} files are out of date. "
              f"Run: python3 scripts/generate_testdata.py")
        return 1
    print(f"{len(tables.paths)} files match the generator.")
    return 0
