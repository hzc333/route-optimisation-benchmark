"""Download benchmark instances + BKS solutions into data/raw/ (not versioned).

Source: https://github.com/PyVRP/Instances (instances and BKS mirrored from
CVRPLIB). Conventions stated by that repository:

* VRPTW (Solomon, Gehring & Homberger 1000): DIMACS convention, distances
  and durations truncated to one decimal; cost = total distance.
* CVRP (Uchoa X): distances rounded to the nearest integer; cost = distance.

HG 200-800 are deliberately not used: the readily available BKS for them
(SINTEF) use a hierarchical vehicles-then-distance objective with unrounded
distances, which is not comparable with the DIMACS convention.
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAW = Path(__file__).resolve().parent / "raw"
API = "https://api.github.com/repos/PyVRP/Instances/contents/{}"
RAW_URL = "https://raw.githubusercontent.com/PyVRP/Instances/main/{}"

SETS = {
    # local dir: repo dir
    "solomon": "VRPTW/Solomon",
    "hg1000": "VRPTW",
    "x": "CVRP",
}


def _list(repo_dir: str) -> list[str]:
    with urllib.request.urlopen(API.format(repo_dir), timeout=30) as resp:
        entries = json.load(resp)
    return [e["name"] for e in entries
            if e["type"] == "file" and e["name"].endswith((".vrp", ".sol"))]


def _fetch(repo_path: str, dest: Path) -> None:
    if dest.exists():
        return
    with urllib.request.urlopen(RAW_URL.format(repo_path), timeout=60) as resp:
        dest.write_bytes(resp.read())


def download(name: str) -> int:
    repo_dir = SETS[name]
    out = RAW / name
    out.mkdir(parents=True, exist_ok=True)
    files = _list(repo_dir)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda f: _fetch(f"{repo_dir}/{f}", out / f), files))
    return len(files)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("sets", nargs="*", help=f"subset of {list(SETS)} (default: all)")
    chosen = ap.parse_args().sets or list(SETS)
    if unknown := set(chosen) - set(SETS):
        ap.error(f"unknown sets {sorted(unknown)}")
    for s in chosen:
        print(f"{s}: {download(s)} files -> {(RAW / s).relative_to(RAW.parent)}")
