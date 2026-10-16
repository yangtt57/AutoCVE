#!/usr/bin/env python3
"""Verify reviewed text packages, or restore missing pinned source archives. Never execute them."""

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(root, name):
    rel = PurePosixPath(name)
    path = root / name
    if rel.is_absolute() or ".." in rel.parts or "\\" in name:
        raise ValueError(f"Invalid relative path: {name}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"Path escapes package: {name}")
    for item in [path, *path.parents]:
        if item == root:
            break
        if item.is_symlink():
            raise ValueError(f"Symlink is not a reviewed resource: {name}")
    return path


def verify(fetch=False):
    manifest = load(ROOT / "skills_sources_manifest.json")
    catalog = load(safe_path(ROOT, manifest["catalog_path"]))
    inventories = {}
    for alias, source in manifest["sources"].items():
        if not re.fullmatch(r"[0-9a-f]{40}", source["upstream_commit"]):
            raise ValueError(f"Unpinned source: {alias}")
        archive = safe_path(ROOT, source["archive_path"])
        if fetch and not archive.exists():
            request = Request(source["archive_url"], headers={"User-Agent": "AutoCVE-skill-vendor"})
            with urlopen(request, timeout=60) as response:
                data = response.read(40 * 1024 * 1024 + 1)
            if sha(data) != source["archive_sha256"]:
                raise ValueError(f"Downloaded archive hash mismatch: {alias}")
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(data)
        if sha(archive.read_bytes()) != source["archive_sha256"]:
            raise ValueError(f"Source archive hash mismatch: {alias}")
        # List only: no extraction, imports, hook evaluation, or test discovery.
        with tarfile.open(archive) as tar:
            inventories[source["upstream_repo"]] = {
                PurePosixPath(m.name).parts[1:] for m in tar.getmembers() if m.isfile()
            }
    count = 0
    for slug, entry in catalog["packages"].items():
        if slug != entry["slug"] or not re.fullmatch(r"autocve-[a-z0-9-]+", slug):
            raise ValueError(f"Invalid package name: {slug}")
        folder = safe_path(ROOT / "skill_library", slug)
        metadata = load(folder / "metadata.json")
        if metadata["metadata"] != entry:
            raise ValueError(f"Catalog and package metadata disagree: {slug}")
        for field in [
            "upstream_repo",
            "upstream_commit",
            "license",
            "source_paths",
            "local_changes",
            "required_tools",
            "applicable_scenarios",
            "stages",
            "output_contract_version",
            "adaptation_version",
        ]:
            if not entry.get(field):
                raise ValueError(f"Missing {field}: {slug}")
        if entry["runtime"] == "discovery_v2" and set(entry["required_tools"]) - {
            "Read",
            "Grep",
            "Glob",
            "RecordCandidate",
            "RecordCoverage",
            "UpdateCandidate",
            "GetCandidate",
            "GetEvidence",
            "RequestFollowup",
            "GetScanObservation",
            "SubmitFeedbackDecisions",
        }:
            raise ValueError(f"Unexpected tool permissions: {slug}")
        for name, resource in entry["resources"].items():
            path = safe_path(folder, name)
            if path.suffix != ".md" or path.stat().st_size > 128 * 1024:
                raise ValueError(f"Not a bounded text resource: {slug}/{name}")
            text = path.read_text(encoding="utf-8")
            if sha(path.read_bytes()) != resource["sha256"]:
                raise ValueError(f"Reviewed asset changed: {slug}/{name}")
            if name == "SKILL.md":
                frontmatter = text.split("---", 2)[1]
                if re.search(r"(?mi)^(hooks|shell|model|allowed-tools)\s*:", frontmatter):
                    raise ValueError(f"Host tool override in adapted frontmatter: {slug}")
            for source_path in resource["source_paths"]:
                if entry["upstream_repo"] == "AutoCVE/local":
                    safe_path(ROOT, source_path).read_bytes()
                elif PurePosixPath(source_path).parts not in inventories[entry["upstream_repo"]]:
                    raise ValueError(f"Missing upstream reference: {slug}: {source_path}")
            for target in re.findall(r"\]\(([^)]+)\)", text):
                if "://" not in target and not target.startswith("#"):
                    if not safe_path(path.parent, target.split("#")[0]).exists():
                        raise ValueError(f"Broken relative reference: {slug}: {target}")
            count += 1
        if not (folder / "NOTICE.md").is_file():
            raise ValueError(f"Missing attribution: {slug}")
        if entry["upstream_repo"] != "AutoCVE/local" and not (folder / "LICENSE").is_file():
            raise ValueError(f"Missing license: {slug}")
    print(
        f"Verified {len(catalog['packages'])} packages, {count} text resources, {len(inventories)} pinned source archives."
    )
    print("No upstream scripts, tests, hooks, installers, or target applications executed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["verify", "fetch"], nargs="?", default="verify")
    args = parser.parse_args()
    verify(fetch=args.action == "fetch")
