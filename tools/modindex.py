#!/usr/bin/env python3
"""
modindex: validates TavernMods submissions and compiles the static index.

  fill-hashes [paths]   write the real sha256 of every artifact and library
  validate [paths]      check submissions, downloading and hashing every file
                        (VirusTotal too when VIRUSTOTAL_API_KEY is set)
  build                 compile manifests/ and replacements.json into latest*.json
                        and repository.json (--ingest moves submissions in first,
                        --prune deletes them)
  site                  bake tools/page.html with the mod list into site/index.html

paths default to submissions/. Rules: docs/REPO_STRUCTURE.md, which the
launcher (tavern_shared/mods/), TavernLib (Backend/Mods/) and tools/builder.html
implement too; change them together.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import zlib
from urllib.parse import urlparse

SUPPORTED_MANIFEST_MAJOR = 2
SUPPORTED_INDEX_MAJOR = 2
TARGETS = ("client_windows", "server", "client_android")
SCENES = ("normal", "quest", "tutorial")
_PACKAGE_TYPES = ("dll", "zip")

# \Z, not $, which also matches before a final newline; ASCII digits only.
GITHUB_USER_RE = re.compile(r"\A[A-Za-z0-9](?:-?[A-Za-z0-9]){0,38}\Z")
GITHUB_REPO_RE = re.compile(r"\A[A-Za-z0-9._-]{1,100}\Z")
VERSION_RE = re.compile(r"\A[0-9]+\.[0-9]+\.[0-9]+\Z")
SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")
VERSION_SEGMENT_MAX = 2147483647   # TavernLib parses segments as Int32

_MANIFEST_ORDER = [
    "manifest_version", "id", "name", "version", "author", "description",
    "screenshots", "parity_required", "scenes", "dependencies", "artifacts",
]
_ARTIFACT_ORDER = ["targets", "download_url", "sha256", "package", "library_dependencies"]
_LIB_ORDER = ["name", "download_url", "sha256", "filename"]

_V1_FIELDS = {
    "client_side": "replaced by the targets of each entry in artifacts (client_windows, server, client_android)",
    "server_side": "replaced by the targets of each entry in artifacts (client_windows, server, client_android)",
    "download_url": "moved into each entry of artifacts",
    "sha256": "moved into each entry of artifacts",
    "package": "moved into each entry of artifacts (and set by the tooling, not written)",
    "library_dependencies": "moved into each entry of artifacts",
}

_V1_MESSAGE = (
    "manifest_version 1 is the old format; this repo takes manifest_version 2. "
    "What changed: client_side / server_side are gone, replaced by an "
    "\"artifacts\" list where each entry names the targets it is built for "
    "(\"client_windows\", \"server\", \"client_android\") and carries its own "
    "download_url, sha256 and library_dependencies. A mod that ships one DLL for "
    "players and servers "
    "has one artifact with \"targets\": [\"client_windows\", \"server\"]. See "
    "submissions/TEMPLATE.json and docs/REPO_STRUCTURE.md.")

# Zip limits; the launcher's extractor applies the same ones at install time.
ZIP_MAX_ENTRIES = 2000
ZIP_MAX_TOTAL_UNCOMPRESSED = 500 * 1024 * 1024
ZIP_MAX_RATIO = 200                      # per entry, uncompressed / compressed
ZIP_RATIO_MIN_SIZE = 1 * 1024 * 1024     # entries smaller than this skip the ratio check

_VT_BASE = "https://www.virustotal.com/api/v3"
_VT_SIMPLE_UPLOAD_MAX = 32 * 1024 * 1024   # larger files need an upload URL

# Zip members worth a VirusTotal scan, by extension or magic bytes (a renamed
# executable is still caught). Inert assets are never uploaded.
_CODE_EXTENSIONS = {
    ".dll", ".exe", ".so", ".dylib", ".netmodule",
    ".bat", ".cmd", ".com", ".scr", ".msi", ".jar",
    ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse",
    ".wsf", ".wsh", ".hta", ".py", ".sh",
}
_CODE_MAGICS = (
    b"MZ", b"\x7fELF",                                                    # PE, ELF
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",  # Mach-O
    b"\xca\xfe\xba\xbe",                                                  # Mach-O fat / Java
    b"#!",
)

SITE_MARKER = "/*__MODS__*/[]"   # the [] keeps the template a valid page on its own
SCREENSHOT_EXT_RE = re.compile(r"\.(?:png|jpe?g|webp|gif)$", re.IGNORECASE)
SCREENSHOT_MAX = 4
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

_NON_SUBMISSION_BASENAMES = {"readme.json", "template.json"}

REPLACEMENTS_FILE = "replacements.json"
_REPLACEMENT_FIELDS = ("by", "note")


class ValidationError(Exception):
    """A failure that blocks a submission or a build."""


# -- helpers -------------------------------------------------------------------

def repo_root(explicit=None):
    return os.path.abspath(explicit) if explicit else os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, obj):
    # LF on every OS, matching .gitattributes.
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _vkey(version):
    return tuple(int(x) for x in version.split("."))


def _is_safe_basename(name):
    # ':' is a drive letter or an NTFS alternate data stream on Windows.
    return (isinstance(name, str) and name not in ("", ".", "..")
            and not any(c in name for c in "/\\:") and os.path.basename(name) == name)


def parse_id(mod_id):
    """'<github-user>.<github-repo>' -> (author, repo), or ValidationError."""
    if not isinstance(mod_id, str) or "." not in mod_id:
        raise ValidationError(f"id {mod_id!r} must be '<user>.<repo>'")
    author, repo = mod_id.split(".", 1)
    if not GITHUB_USER_RE.match(author):
        raise ValidationError(f"id author segment {author!r} is not a valid GitHub username")
    if not GITHUB_REPO_RE.match(repo):
        raise ValidationError(f"id repo segment {repo!r} is not a valid GitHub repo name")
    if repo in (".", "..") or repo.endswith("."):
        raise ValidationError(f"id segment {repo!r} is path-unsafe (Windows drops a trailing dot)")
    return author, repo


def case_clash(mod_id, ids):
    """An id in ids spelled differently but equal ignoring case, else None: on
    Windows the two would share one Mods/ folder."""
    return next((k for k in ids if k != mod_id and k.casefold() == mod_id.casefold()), None)


def parity_required(m, default=True):
    # Only a literal false relaxes it, so malformed data fails closed.
    return m.get("parity_required", default) is not False


def scenes_error(m):
    value = m.get("scenes")
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        return ("scenes must be a non-empty list of scenes the mod works in, out of "
                + ", ".join(SCENES) + " (leave it out for a mod that works in all of them)")
    bad = [s for s in value if not isinstance(s, str) or s not in SCENES]
    if bad:
        return (f"scenes lists {bad!r}, which isn't one of " + ", ".join(SCENES))
    if len(set(value)) != len(value):
        return "scenes lists the same scene more than once"
    if set(value) == set(SCENES):
        return "scenes lists every scene; leave it out instead, which means the same"
    return None


def _sniff_package(head):
    return "zip" if head[:2] == b"PK" else "dll"


def _ordered(d, order):
    out = {k: d[k] for k in order if k in d}
    out.update((k, v) for k, v in d.items() if k not in out)   # unknown keys last
    return out


def ordered_manifest(m):
    """m with its keys in the spec's order at every level."""
    out = _ordered(m, _MANIFEST_ORDER)
    if isinstance(out.get("artifacts"), list):
        arts = []
        for a in out["artifacts"]:
            if isinstance(a, dict):
                a = _ordered(a, _ARTIFACT_ORDER)
                if isinstance(a.get("library_dependencies"), list):
                    a["library_dependencies"] = [
                        _ordered(lib, _LIB_ORDER) if isinstance(lib, dict) else lib
                        for lib in a["library_dependencies"]]
            arts.append(a)
        out["artifacts"] = arts
    return out


def manifest_targets(m):
    """Sorted union of the known targets across m's artifacts."""
    found = set()
    for a in m.get("artifacts") or []:
        if isinstance(a, dict) and isinstance(a.get("targets"), list):
            found.update(t for t in a["targets"] if t in TARGETS)
    return sorted(found)


def _display(m):
    return {"name": m.get("name", m["id"]),
            "author": m.get("author", m["id"].split(".", 1)[0]),
            "description": m.get("description", "")}


def summary_entry(highest_manifest, versions_in_major):
    """The repository.json entry for one (id, major)."""
    m = highest_manifest
    entry = {**_display(m), "parity_required": parity_required(m),
             "targets": manifest_targets(m)}
    if m.get("scenes") is not None:
        entry["scenes"] = list(m["scenes"])
    entry["versions"] = versions_in_major
    return entry


# -- structural validation (no network) ---------------------------------------

def _version_error(value, what):
    if not isinstance(value, str) or not VERSION_RE.match(value):
        return f"{what} {value!r} must be exactly MAJOR.MINOR.PATCH (three integers)"
    if any(int(seg) > VERSION_SEGMENT_MAX for seg in value.split(".")):
        return f"{what} {value!r} has a segment over {VERSION_SEGMENT_MAX}"
    return None


def _is_https_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False
    return p.scheme == "https" and bool(p.hostname)


def _release_asset(parts, author, repo):
    """parts is <author>/<repo>/releases/download/<tag>/<file>: a tagged
    release asset, which a fork can't serve under its parent's path and a
    later release can't change."""
    return (len(parts) == 6 and parts[0].lower() == author.lower() and parts[1].lower() == repo.lower()
            and parts[2:4] == ["releases", "download"])


def _url_owned_by(url, author, repo):
    """url is a release asset of github.com/author/repo (case-insensitive, like GitHub)."""
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.scheme != "https" or p.netloc.lower() != "github.com":
        return False
    return _release_asset([seg for seg in p.path.split("/") if seg], author, repo)


def validate_structure(m, check_urls=True):
    """Error strings for every schema rule m breaks. check_urls=False skips the
    https and ownership rules, for a manifest written for another host."""
    if not isinstance(m, dict):
        return ["a manifest must be a JSON object"]
    mv = m.get("manifest_version")
    if type(mv) is int and mv == 1:
        return [_V1_MESSAGE]     # every other error would be a symptom of this one
    errs = []
    if type(mv) is not int or mv != SUPPORTED_MANIFEST_MAJOR:
        errs.append(f"manifest_version must be {SUPPORTED_MANIFEST_MAJOR}, got {mv!r}")

    mod_id = m.get("id")
    author = repo = None
    try:
        author, repo = parse_id(mod_id)
    except ValidationError as e:
        errs.append(str(e))

    problem = _version_error(m.get("version"), "version")
    if problem:
        errs.append(problem)

    for key, what in _V1_FIELDS.items():
        if key in m:
            errs.append(f"top-level {key} isn't part of manifest v2: it's {what}")

    if "parity_required" not in m:
        errs.append("parity_required is required: true if a client joining a "
                    "server that runs this mod must have this exact version, "
                    "false if the server should not block the join over it")
    elif not isinstance(m["parity_required"], bool):
        errs.append("parity_required must be a boolean")

    problem = scenes_error(m)
    if problem:
        errs.append(problem)

    deps = m.get("dependencies")
    if not isinstance(deps, dict):
        errs.append("dependencies must be an object, always present (use {} when none)")
    else:
        for dep_id, min_version in deps.items():
            try:
                parse_id(dep_id)
            except ValidationError as e:
                errs.append(f"dependencies key {dep_id!r} is not a valid mod id: {e}")
            problem = _version_error(min_version, f"dependencies[{dep_id!r}] minimum version")
            if problem:
                errs.append(problem)
            elif dep_id == mod_id:
                errs.append(f"dependencies lists {dep_id!r}, the mod's own id; "
                            f"a mod can't depend on itself")

    arts = m.get("artifacts")
    if not isinstance(arts, list) or not arts:
        errs.append("artifacts must be a non-empty list: one entry per build the "
                    "mod ships, each naming the targets it's for")
    else:
        claimed = {}     # target -> index of the artifact that lists it
        for i, a in enumerate(arts):
            errs += _artifact_errors(a, i, claimed, author, repo, check_urls)
    return errs


def _artifact_errors(a, i, claimed, author, repo, check_urls):
    where = f"artifacts[{i}]"
    if not isinstance(a, dict):
        return [f"{where} must be an object"]
    errs = []

    targets = a.get("targets")
    if not isinstance(targets, list) or not targets:
        errs.append(f"{where}.targets must be a non-empty list of targets, out of "
                    + ", ".join(TARGETS))
    else:
        for t in targets:
            if not isinstance(t, str) or t not in TARGETS:
                errs.append(f"{where}.targets lists {t!r}, which isn't a known target "
                            "(" + ", ".join(TARGETS) + ")")
            elif t in claimed:
                other = claimed[t]
                errs.append(
                    f"{where}.targets lists {t!r}, which "
                    + ("it already lists" if other == i else f"artifacts[{other}] already lists")
                    + "; each target can have only one build")
            else:
                claimed[t] = i

    url = a.get("download_url")
    if not isinstance(url, str) or not url:
        errs.append(f"{where}.download_url is required")
    elif check_urls:
        if not _is_https_url(url):
            errs.append(f"{where}.download_url must be an https:// URL")
        elif author and repo and not _url_owned_by(url, author, repo):
            errs.append(
                f"{where}.download_url {url!r} must be a GitHub release asset, "
                f"https://github.com/{author}/{repo}/releases/download/<tag>/<file> "
                f"(the repo the id names, at a tag, so it can't change after review).")

    if not isinstance(a.get("sha256"), str) or not SHA256_RE.match(a["sha256"]):
        errs.append(f"{where}.sha256 must be 64 lowercase hex characters")

    # Normally omitted (ingest sets it), but must be valid if present.
    pkg = a.get("package")
    if pkg is not None and pkg not in _PACKAGE_TYPES:
        errs.append(f"{where}.package {pkg!r} must be one of {_PACKAGE_TYPES} "
                    "(normally omitted, the tooling sets it)")

    libs = a.get("library_dependencies")
    if not isinstance(libs, list):
        errs.append(f"{where}.library_dependencies must be a list, always present "
                    "(use [] when none)")
        return errs
    for j, lib in enumerate(libs):
        lwhere = f"{where}.library_dependencies[{j}]"
        if not isinstance(lib, dict):
            errs.append(f"{lwhere} must be an object")
            continue
        if not isinstance(lib.get("name"), str) or not lib["name"]:
            errs.append(f"{lwhere}.name is required")
        if not _is_safe_basename(lib.get("filename")):
            errs.append(f"{lwhere}.filename must be a bare filename")
        if not isinstance(lib.get("download_url"), str) or not lib["download_url"]:
            errs.append(f"{lwhere}.download_url is required")
        elif check_urls and not _is_https_url(lib["download_url"]):
            errs.append(f"{lwhere}.download_url must be an https:// URL")
        if not isinstance(lib.get("sha256"), str) or not SHA256_RE.match(lib["sha256"]):
            errs.append(f"{lwhere}.sha256 must be 64 lowercase hex characters")
    return errs


# -- dependency targets --------------------------------------------------------

def _targets_text(targets):
    return "+".join(sorted(targets)) if targets else "no target"


def version_floor_error(m, known):
    """Why m's version can't join the versions already published, or None.
    Each major is its own line, so a fix to an older major is allowed, but a
    release must beat its major's highest and a new major can't start below
    the newest one."""
    published = sorted((_vkey(v) for v in known.get(m["id"], {})), reverse=True)
    v, show = _vkey(m["version"]), lambda k: ".".join(map(str, k))
    if v in published:
        return (f"{m['id']} {m['version']} is already published and a published "
                f"version never changes; bump the version instead")
    in_major = [p for p in published if p[0] == v[0]]
    if in_major and v < in_major[0]:
        return (f"{m['id']} {m['version']} is lower than {show(in_major[0])}, the highest "
                f"published {v[0]}.x; use a higher version")
    if not in_major and published and v[0] < published[0][0]:
        return (f"{m['id']} {m['version']} would start major {v[0]}, below the newest "
                f"published version {show(published[0])}; use a higher version")
    return None


def _resolve_dep_in_repo(known, dep_id, min_version):
    """The manifest an install would pick: highest in min_version's major that
    is >= it. None if this repo doesn't carry one."""
    versions = known.get(dep_id) or {}
    major, key = min_version.split(".")[0], _vkey(min_version)
    candidates = [v for v in versions if v.split(".")[0] == major and _vkey(v) >= key]
    return versions[max(candidates, key=_vkey)] if candidates else None


def validate_dependency_targets(m, known):
    """(errs, warns): a dependency sharing no target with m is an error, since
    per-target installs leave it out everywhere m runs. Partial overlap is only
    a note: whether m's other builds work without it is for a reviewer."""
    errs, warns = [], []
    mine = set(manifest_targets(m))
    for dep_id, min_version in sorted((m.get("dependencies") or {}).items()):
        if _version_error(min_version, "") is not None:
            continue        # validate_structure reports it
        dep = _resolve_dep_in_repo(known, dep_id, min_version)
        if dep is None:
            warns.append(
                f"dependency {dep_id} >= {min_version} isn't in this repository, "
                f"so its targets can't be checked here. If it lives in another "
                f"source, users need that source added to install this.")
            continue
        theirs = set(manifest_targets(dep))
        shared = mine & theirs
        if not shared:
            errs.append(
                f"dependency {dep_id} {dep.get('version')} has builds for "
                f"{_targets_text(theirs)}, but this mod has builds for "
                f"{_targets_text(mine)}. They share no target, so the dependency "
                f"can't be satisfied anywhere this mod runs.")
        elif shared != mine:
            missing = _targets_text(mine - shared)
            builds, does = (("builds", "don't") if len(mine - shared) > 1
                            else ("build", "doesn't"))
            warns.append(
                f"dependency {dep_id} {dep.get('version')} has builds for "
                f"{_targets_text(theirs)} only, so this mod's {missing} {builds} "
                f"will load without it. Fine if only its {_targets_text(shared)} "
                f"build needs it -- installers leave it out there rather than "
                f"installing something that would fail to load. Make sure the "
                f"{missing} {builds} really {does} touch it.")
    return errs, warns


def _manifest_files(root):
    """Every manifests/**/<version>.json, skipping the latest*.json pointers."""
    for dirpath, _dirs, files in os.walk(os.path.join(root, "manifests")):
        for name in sorted(files):
            if name.endswith(".json") and not name.startswith("latest"):
                yield os.path.join(dirpath, name)


def _known_manifests(root):
    """id -> {version: manifest}, unvalidated: another mod's problem must not
    fail an unrelated submission."""
    known = {}
    for path in _manifest_files(root):
        try:
            m = _load_json(path)
            known.setdefault(m["id"], {})[m["version"]] = m
        except Exception:
            continue
    return known


def _collect_manifests(root):
    """id -> {version: manifest}, strictly validated, for the build."""
    mods = {}
    for path in _manifest_files(root):
        m = _load_json(path)
        errs = validate_structure(m)
        if not errs:   # ingest always sets package, so a missing one was hand-placed
            errs = [f"artifacts[{i}] has no package (ingest sets it from the file)"
                    for i, a in enumerate(m["artifacts"]) if "package" not in a]
        if errs:
            raise ValidationError(f"{os.path.relpath(path, root)} is invalid:\n  - "
                                  + "\n  - ".join(errs))
        mods.setdefault(m["id"], {})[m["version"]] = m
    return mods


def load_replacements(root):
    """replacements.json: {old id: {"by": new id, "note": text}}, or {} when
    there is none. Maintainers edit it; a fork PR can only add a submission."""
    path = os.path.join(root, REPLACEMENTS_FILE)
    if not os.path.isfile(path):
        return {}
    try:
        reps = _load_json(path)
    except ValueError as e:
        raise ValidationError(f"{REPLACEMENTS_FILE} is not valid JSON: {e}")
    if not isinstance(reps, dict):
        raise ValidationError(f"{REPLACEMENTS_FILE} must be an object of old id -> entry")
    return reps


def _installable_targets(versions):
    """The targets an installer can take, from the highest version's manifest."""
    m = versions[max(versions, key=_vkey)]
    return set(manifest_targets(m)) - {"client_android"}


def validate_replacements(reps, mods):
    """Errors in replacements.json against mods ({id: {version: manifest}}):
    each old id is published, replaced by a different published mod that
    isn't itself replaced and builds every target the old one does."""
    errs = []
    for old_id, entry in sorted(reps.items()):
        where = f"{REPLACEMENTS_FILE}: {old_id}"
        try:
            parse_id(old_id)
        except ValidationError as e:
            errs.append(f"{where}: {e}")
            continue
        if not isinstance(entry, dict):
            errs.append(f'{where}: must be an object with "by" and optionally "note"')
            continue
        unknown = sorted(set(entry) - set(_REPLACEMENT_FIELDS))
        if unknown:
            errs.append(f"{where}: unknown field(s) {', '.join(unknown)}")
        new_id = entry.get("by")
        if not isinstance(new_id, str):
            errs.append(f'{where}: "by" must be the id of the mod that replaces it')
            continue
        if "note" in entry and not isinstance(entry["note"], str):
            errs.append(f'{where}: "note" must be text')
        if new_id.casefold() == old_id.casefold():
            errs.append(f"{where}: a mod can't replace itself")
        elif new_id in reps:
            errs.append(f"{where}: replaced by {new_id}, which is replaced too; "
                        f"point it at {new_id}'s replacement instead")
        elif new_id not in mods:
            errs.append(f"{where}: replaced by {new_id}, which isn't published here")
        elif old_id not in mods:
            errs.append(f"{where}: no such mod is published here")
        elif lost := _installable_targets(mods[old_id]) - _installable_targets(mods[new_id]):
            errs.append(f"{where}: {new_id} has no {_targets_text(lost)} build, so installs "
                        f"of {old_id} there could never switch to it")
    return errs


def library_problems(m, known):
    """(errs, warns): UserLibs/ is shared by every target, so one filename at
    two sha256s in m is an error, and against another mod's newest release a
    note: installers refuse to put the two in one game folder."""
    errs, warns, mine = [], [], {}
    for a in m["artifacts"]:
        for lib in a["library_dependencies"]:
            if mine.setdefault(lib["filename"], lib["sha256"]) != lib["sha256"]:
                errs.append(f"library {lib['filename']} is pinned at two sha256s across this "
                            f"mod's artifacts")
    for mod_id, versions in sorted(known.items()):
        try:
            version = max(versions, key=_vkey)
        except (TypeError, ValueError):
            continue
        if mod_id == m["id"]:
            continue
        for a in versions[version].get("artifacts") or []:
            for lib in (a.get("library_dependencies") or []) if isinstance(a, dict) else []:
                if (isinstance(lib, dict) and lib.get("filename") in mine
                        and lib.get("sha256") != mine[lib["filename"]]):
                    warns.append(f"library {lib['filename']} is pinned at another sha256 by "
                                 f"{mod_id} {version}, so the two can't be installed together")
    return errs, sorted(set(warns))


def replacement_errors(m, reps):
    """Why a submission clashes with replacements.json, as a list."""
    errs = []
    if m["id"] in reps:
        errs.append(f"{m['id']} has been replaced by {reps[m['id']].get('by')} and takes "
                    f"no new releases")
    for dep_id in sorted(m.get("dependencies") or {}):
        if dep_id in reps:
            errs.append(f"dependency {dep_id} has been replaced by {reps[dep_id].get('by')}; "
                        f"depend on that instead")
    return errs


# -- downloads -----------------------------------------------------------------

def _assert_safe_to_fetch(url):
    """Refuse non-https URLs and hosts resolving to non-public addresses, since
    validation runs with secrets. DNS rebinding isn't covered: urllib can't pin
    the vetted address, and the runner only holds a VirusTotal key."""
    p = urlparse(url)
    if p.scheme != "https":
        raise ValidationError(f"refusing to fetch non-https URL {url!r}")
    host = p.hostname
    if not host:
        raise ValidationError(f"refusing to fetch URL with no host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, p.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise ValidationError(f"cannot resolve host {host!r}: {e}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            raise ValidationError(
                f"refusing to fetch {url!r}: host {host!r} resolves to "
                f"non-public address {ip}")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Vets every hop, not just the first URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_safe_to_fetch(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)
# TavernLib refuses a bigger download too.
DOWNLOAD_MAX = ZIP_MAX_TOTAL_UNCOMPRESSED


def _urlopen(url, timeout):
    _assert_safe_to_fetch(url)
    req = urllib.request.Request(url, headers={"User-Agent": "modindex"})
    return _opener.open(req, timeout=timeout)


def download_and_hash(url):
    """Stream url to a temp file; return (temp_path, sha256). Caller deletes it."""
    fd, tmp = tempfile.mkstemp(prefix="modindex_", suffix=".bin")
    h = hashlib.sha256()
    size = 0
    try:
        with os.fdopen(fd, "wb") as out, _urlopen(url, 120) as r:
            while chunk := r.read(65536):
                size += len(chunk)
                if size > DOWNLOAD_MAX:
                    raise ValidationError(f"{url} is over {DOWNLOAD_MAX // (1024 * 1024)} MB")
                h.update(chunk)
                out.write(chunk)
        return tmp, h.hexdigest()
    except Exception:
        os.remove(tmp)
        raise


def _sha256_of_url(url):
    tmp, digest = download_and_hash(url)
    os.remove(tmp)
    return digest


def fetch_verified_head(url, sha256, what):
    """url's first bytes, after checking the file still hashes to sha256."""
    try:
        tmp, actual = download_and_hash(url)
    except ValidationError:
        raise
    except Exception as e:
        raise ValidationError(f"{what}: could not download {url} ({e})")
    try:
        if actual != sha256:
            raise ValidationError(f"{what}: {url} changed since review (sha256 {actual}, "
                                  f"manifest says {sha256})")
        with open(tmp, "rb") as f:
            return f.read(8)
    finally:
        os.remove(tmp)


# -- VirusTotal ----------------------------------------------------------------

# The free API allows 4 requests a minute, so calls are paced in a rolling
# window (VT_MAX_PER_MINUTE raises the cap) and a 429 is waited out and retried.
_VT_WINDOW_SECONDS = 60
_VT_MAX_RETRIES = 5
_vt_request_times = []       # monotonic times of recent calls


def _vt_max_per_min():
    try:
        return max(1, int(os.environ.get("VT_MAX_PER_MINUTE", "4")))
    except ValueError:
        return 4


def _vt_throttle():
    def prune(now):
        while _vt_request_times and _vt_request_times[0] <= now - _VT_WINDOW_SECONDS:
            _vt_request_times.pop(0)

    now = time.monotonic()
    prune(now)
    if len(_vt_request_times) >= _vt_max_per_min():
        wait = _vt_request_times[0] + _VT_WINDOW_SECONDS - now + 0.5
        if wait > 0:
            print(f"  ..    VirusTotal rate limit reached; waiting {wait:.0f}s for "
                  f"the next slot", flush=True)
            time.sleep(wait)
        prune(time.monotonic())
    _vt_request_times.append(time.monotonic())


def _vt_request(url, api_key, method="GET", data=None, content_type=None):
    headers = {"x-apikey": api_key, "Accept": "application/json", "User-Agent": "modindex"}
    if content_type:
        headers["Content-Type"] = content_type
    for attempt in range(_VT_MAX_RETRIES + 1):
        _vt_throttle()
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt >= _VT_MAX_RETRIES:
                raise
            try:
                wait = float(e.headers.get("Retry-After")) if e.headers else 0
            except (TypeError, ValueError):
                wait = 0
            wait = max(wait, _VT_WINDOW_SECONDS)
            print(f"  ..    VirusTotal returned 429 (rate limited); waiting "
                  f"{wait:.0f}s then retrying ({attempt + 1}/{_VT_MAX_RETRIES})",
                  flush=True)
            time.sleep(wait)


def vt_lookup(sha256, api_key):
    """last_analysis_stats for a known hash, or None."""
    try:
        return _vt_request(f"{_VT_BASE}/files/{sha256}", api_key)["data"]["attributes"]["last_analysis_stats"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def vt_upload(path, api_key):
    """Upload a file for analysis; return the analysis id."""
    url = f"{_VT_BASE}/files"
    if os.path.getsize(path) > _VT_SIMPLE_UPLOAD_MAX:
        url = _vt_request(f"{_VT_BASE}/files/upload_url", api_key)["data"]
    boundary = uuid.uuid4().hex
    with open(path, "rb") as f:
        content = f.read()
    body = b"".join([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'.encode(),
        b"Content-Type: application/octet-stream\r\n\r\n",
        content, b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    j = _vt_request(url, api_key, method="POST", data=body,
                    content_type=f"multipart/form-data; boundary={boundary}")
    return j["data"]["id"]


def vt_wait(analysis_id, api_key, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        attrs = _vt_request(f"{_VT_BASE}/analyses/{analysis_id}", api_key)["data"]["attributes"]
        if attrs.get("status") == "completed":
            return attrs["stats"]
        time.sleep(15)
    raise ValidationError("VirusTotal analysis did not complete in time")


def vt_scan(path, sha256, api_key):
    """Analysis stats, uploading only if VirusTotal hasn't seen the hash."""
    stats = vt_lookup(sha256, api_key)
    if stats is None:
        stats = vt_wait(vt_upload(path, api_key), api_key)
    return stats


def _vt_scan_path(path, sha, api_key, vt_max_malicious, label, errs, warns, seen=None,
                  require=False):
    """Scan one file: result in warns, gate failure in errs. A scan that can't
    run is a note, or with `require` a failure. `seen` (sha -> (label, stats))
    scans each distinct file once; a flagged file still fails every label it
    appears under."""
    seen = {} if seen is None else seen
    if sha in seen:
        first, stats = seen[sha]
        if stats is None:
            (errs if require else warns).append(
                f"{label}: same file as {first}, whose VirusTotal scan could not complete")
            return
        warns.append(f"{label}: same file as {first}, already scanned; "
                     f"not scanned again")
    else:
        try:
            stats = vt_scan(path, sha, api_key)
        except Exception as e:
            seen[sha] = (label, None)
            (errs if require else warns).append(
                f"{label}: VirusTotal scan could not complete ({e})"
                + ("" if require else "; not gating on it"))
            return
        seen[sha] = (label, stats)
    mal = stats.get("malicious", 0)
    sus = stats.get("suspicious", 0)
    summary = (f"malicious={mal} suspicious={sus} "
               f"harmless={stats.get('harmless', 0)} undetected={stats.get('undetected', 0)}")
    warns.append(f"{label}: VirusTotal "
                 f"{'flagged this file' if (mal or sus) else 'clean'}: {summary}")
    if vt_max_malicious is not None and mal > vt_max_malicious:
        errs.append(f"{label}: VirusTotal malicious={mal} exceeds "
                    f"--vt-max-malicious={vt_max_malicious}")


def _is_code_bearing(name, head):
    return (os.path.splitext(name)[1].lower() in _CODE_EXTENSIONS
            or any(head.startswith(m) for m in _CODE_MAGICS))


def _vt_scan_zip_members(zip_path, api_key, vt_max_malicious, label, errs, warns, seen=None,
                         require=False):
    """Scan each code-bearing member on its own rather than the whole archive,
    which could exceed VirusTotal's size limit."""
    scanned = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info) as f:
                head = f.read(8)
                if not _is_code_bearing(info.filename, head):
                    continue
                data = head + f.read()
            scanned += 1
            fd, mtmp = tempfile.mkstemp(prefix="modindex_member_")
            try:
                with os.fdopen(fd, "wb") as out:
                    out.write(data)
                _vt_scan_path(mtmp, hashlib.sha256(data).hexdigest(), api_key, vt_max_malicious,
                              f"{label} :: {info.filename}", errs, warns, seen, require)
            finally:
                os.remove(mtmp)
    if scanned == 0:
        warns.append(f"{label}: no executable members in the zip to VirusTotal-scan "
                     "(all inert assets); the archive as a whole was not uploaded")


# -- validate ------------------------------------------------------------------

def _submission_files(paths):
    """The .json files under paths, minus README.json and TEMPLATE.json."""
    for p in paths:
        if os.path.isdir(p):
            for dirpath, _dirs, files in os.walk(p):
                for name in sorted(files):
                    if name.endswith(".json") and name.lower() not in _NON_SUBMISSION_BASENAMES:
                        yield os.path.join(dirpath, name)
        elif p.endswith(".json") and os.path.basename(p).lower() not in _NON_SUBMISSION_BASENAMES:
            yield p


def inspect_zip_bundle(path):
    """Errors in a zip artifact: unsafe members, size caps, no root .dll."""
    errs = []
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as e:
        return [f'package is "zip" but the download is not a valid .zip ({e})']
    with zf:
        infos = zf.infolist()
        if len(infos) > ZIP_MAX_ENTRIES:
            errs.append(f"zip has {len(infos)} entries, over the {ZIP_MAX_ENTRIES} cap")
        total = any_dll = root_dll = 0
        for info in infos:
            name = info.filename
            if name.startswith(("/", "\\")):
                errs.append(f"unsafe zip entry {name!r}: absolute path")
                continue
            if ":" in name:
                errs.append(f"unsafe zip entry {name!r}: contains a colon "
                            f"(drive letter or NTFS alternate data stream)")
                continue
            norm = name.replace("\\", "/")
            if ".." in norm.split("/"):
                errs.append(f"unsafe zip entry {name!r}: path traversal")
                continue
            if any(p != p.rstrip(". ") for p in norm.split("/") if p not in ("", ".")):
                errs.append(f"unsafe zip entry {name!r}: a name ends in a dot or space, "
                            f"which Windows drops")
                continue
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and (mode & 0o170000) == 0o120000:
                errs.append(f"unsafe zip entry {name!r}: symlink")
                continue
            total += info.file_size
            if info.file_size > ZIP_RATIO_MIN_SIZE and info.compress_size > 0:
                ratio = info.file_size / info.compress_size
                if ratio > ZIP_MAX_RATIO:
                    errs.append(f"zip entry {name!r} decompression ratio {ratio:.0f} "
                                f"exceeds {ZIP_MAX_RATIO} (possible zip bomb)")
            if norm.lower().endswith(".dll"):
                any_dll += 1
                if "/" not in norm.strip("/"):
                    root_dll += 1
        if total > ZIP_MAX_TOTAL_UNCOMPRESSED:
            errs.append(f"zip extracts to {total} bytes, over the "
                        f"{ZIP_MAX_TOTAL_UNCOMPRESSED}-byte cap")
        if any_dll == 0:
            errs.append('package is "zip" but the archive contains no .dll, '
                        "MelonLoader would have nothing to load")
        elif root_dll == 0:
            errs.append("zip bundle has .dll files only in subfolders, none at the "
                        "archive root. The archive root becomes the build's folder "
                        "and the mod's main assembly belongs there; DLLs only in "
                        "subfolders are almost always a packaging mistake. Put the "
                        "mod assembly at the archive root.")
        if not errs:
            errs += _zip_read_errors(zf)
    return errs


def _zip_read_errors(zf):
    """Reads every member back, as installers extract them, counting what is
    produced: headers can understate a bomb, and an encrypted or oddly
    compressed member only fails here."""
    total = 0
    for info in zf.infolist():
        try:
            with zf.open(info) as f:
                while chunk := f.read(1 << 20):
                    total += len(chunk)
                    if total > ZIP_MAX_TOTAL_UNCOMPRESSED:
                        return [f"zip extracts to over {ZIP_MAX_TOTAL_UNCOMPRESSED} bytes"]
        except (RuntimeError, NotImplementedError, zipfile.BadZipFile, EOFError, zlib.error) as e:
            return [f"zip entry {info.filename!r} can't be read ({e}); use stored or "
                    f"deflated members, unencrypted"]
    return []


def _check_file(url, expected_sha, api_key, vt_max_malicious, label, allow_zip=False,
                vt_seen=None, require_vt=False):
    """Download url, verify its hash, check an artifact is a dll or a sound
    zip, and scan it. Returns (errs, warns)."""
    errs, warns = [], []
    try:
        tmp, actual = download_and_hash(url)
    except Exception as e:
        return [f"{label}: could not download {url} ({e})"], warns
    try:
        if actual.lower() != str(expected_sha).lower():
            errs.append(f"{label}: sha256 mismatch, manifest says {expected_sha}, file is {actual}")
            return errs, warns
        with open(tmp, "rb") as f:
            head = f.read(8)
        is_zip = allow_zip and _sniff_package(head) == "zip"
        if allow_zip and not is_zip and head[:2] != b"MZ":
            errs.append(f"{label}: the file is neither a zip nor a DLL (no MZ header)")
            return errs, warns
        if is_zip:
            warns.append(f"{label}: detected a zip bundle (package=zip)")
            errs += [f"{label}: {e}" for e in inspect_zip_bundle(tmp)]
            if errs:
                return errs, warns
        if not api_key:
            (errs if require_vt else warns).append(
                f"{label}: VirusTotal skipped (no VIRUSTOTAL_API_KEY set)")
        elif is_zip:
            _vt_scan_zip_members(tmp, api_key, vt_max_malicious, label, errs, warns, vt_seen,
                                 require_vt)
        else:
            _vt_scan_path(tmp, actual, api_key, vt_max_malicious, label, errs, warns, vt_seen,
                          require_vt)
    finally:
        os.remove(tmp)
    return errs, warns


def cmd_validate(args):
    root = repo_root(args.repo)
    files = list(_submission_files(args.paths or [os.path.join(root, "submissions")]))
    known = _known_manifests(root)
    submitted = {}
    for path in files:
        try:
            m = _load_json(path)
            submitted.setdefault(m["id"], {})[m["version"]] = m
        except Exception:
            pass
    rep_failed = False
    if os.path.isfile(os.path.join(root, REPLACEMENTS_FILE)):
        print(f"== {REPLACEMENTS_FILE} ==")
        # A replacement may name a mod submitted in the same PR.
        both = {i: {**known.get(i, {}), **submitted.get(i, {})} for i in set(known) | set(submitted)}
        errs = validate_replacements(load_replacements(root), both)
        for e in errs:
            print(f"  FAIL  {e}")
        if not errs:
            print("  OK    every replacement points at a published or submitted mod")
        rep_failed = bool(errs)

    if not files:
        print("No submission manifests to validate.")
        return 1 if rep_failed else 0

    api_key = os.environ.get("VIRUSTOTAL_API_KEY", "").strip() or None
    reps = load_replacements(root)
    sub_root = os.path.join(os.path.abspath(root), "submissions")
    all_ids = set(known) | set(reps) | set(submitted)
    vt_seen = {}
    failures = 0
    for path in files:
        print(f"\n== {os.path.relpath(path, root)} ==")
        try:
            m = _load_json(path)
        except Exception as e:
            print(f"  FAIL  not valid JSON: {e}")
            failures += 1
            continue

        errs = validate_structure(m)
        warns = []
        if not errs:
            errs = replacement_errors(m, reps)
            want = os.path.join(sub_root, m["id"], f'{m["version"]}.json')
            if os.path.abspath(path).startswith(sub_root + os.sep) and os.path.abspath(path) != want:
                errs.append(f"must be at submissions/{m['id']}/{m['version']}.json, its id and version")
            if other := case_clash(m["id"], all_ids):
                errs.append(f"id {m['id']} differs from {other} only in case; on Windows "
                            f"both would install to one folder")
        if not errs and (floor := version_floor_error(m, known)):
            errs = [floor]
        if not errs:
            errs, warns = validate_dependency_targets(m, known)
            lib_errs, lib_warns = library_problems(m, known)
            errs += lib_errs
            warns += lib_warns
        if not errs:
            for i, art in enumerate(m["artifacts"]):
                label = f"artifacts[{i}] ({'+'.join(art['targets'])})"
                checks = [(art, label, True)] + [
                    (lib, f"{label} library[{j}] {lib['name']}", False)
                    for j, lib in enumerate(art["library_dependencies"])]
                for obj, what, allow_zip in checks:
                    e, w = _check_file(obj["download_url"], obj["sha256"], api_key,
                                       args.vt_max_malicious, what, allow_zip, vt_seen,
                                       args.require_vt)
                    errs += e
                    warns += w

        for w in warns:
            print(f"  note  {w}")
        if errs:
            failures += 1
            for e in errs:
                print(f"  FAIL  {e}")
        else:
            print("  OK    structurally valid, all hashes verified")

    print(f"\n{len(files)} manifest(s) checked, {failures} failed.")
    return 1 if failures or rep_failed else 0


# -- fill-hashes ---------------------------------------------------------------

def _fill_one(obj, label):
    url = obj.get("download_url")
    if not url:
        print(f"  skip  {label}: no download_url")
        return False
    try:
        digest = _sha256_of_url(url)
    except Exception as e:
        print(f"  FAIL  {label}: could not download {url} ({e})")
        return False
    old = obj.get("sha256")
    obj["sha256"] = digest
    print(f"  set   {label}: {digest}" + (f"  (was {old})" if old and old != digest else ""))
    return True


def cmd_fill(args):
    root = repo_root(args.repo)
    files = list(_submission_files(args.paths or [os.path.join(root, "submissions")]))
    if not files:
        print("No manifest files to fill.")
        return 0

    failures = 0
    for path in files:
        print(f"\n== {os.path.relpath(path, root)} ==")
        try:
            m = _load_json(path)
        except Exception as e:
            print(f"  FAIL  not valid JSON: {e}")
            failures += 1
            continue
        arts = m.get("artifacts") if isinstance(m, dict) else None
        if not isinstance(arts, list) or not arts:
            print("  FAIL  no artifacts list to fill (a manifest_version 1 file? "
                  "see submissions/TEMPLATE.json for the v2 shape)")
            failures += 1
            continue
        ok = True
        for i, art in enumerate(arts):
            if not isinstance(art, dict):
                print(f"  skip  artifacts[{i}]: not an object")
                ok = False
                continue
            label = f"artifacts[{i}]"
            ok = _fill_one(art, label) and ok
            libs = art.get("library_dependencies")
            for j, lib in enumerate(libs if isinstance(libs, list) else []):
                if isinstance(lib, dict):
                    ok = _fill_one(lib, f"{label} library[{j}] {lib.get('name', '')}") and ok
        if ok:
            _write_json(path, m)
            print(f"  wrote {os.path.relpath(path, root)}")
        else:
            failures += 1
            print("  left unchanged (a file couldn't be fetched)")

    print(f"\n{len(files)} manifest(s) processed, {failures} with problems.")
    return 1 if failures else 0


# -- build ---------------------------------------------------------------------

def _ingest_submissions(root):
    """Move each valid submission into manifests/, with package sniffed from
    its file after re-checking every hash, since a release asset can be
    replaced after review. An identical copy of a published one is only
    pruned. Returns the moved paths."""
    moved = []
    for path in _submission_files([os.path.join(root, "submissions")]):
        rel = os.path.relpath(path, root)
        m = _load_json(path)
        errs = validate_structure(m)
        if errs:
            raise ValidationError(f"{rel} is not structurally valid:\n  - " + "\n  - ".join(errs))
        author, repo = parse_id(m["id"])
        dest = os.path.join(root, "manifests", author, repo, f'{m["version"]}.json')
        for i, art in enumerate(m["artifacts"]):
            head = fetch_verified_head(art["download_url"], art["sha256"], f"{rel} artifacts[{i}]")
            art["package"] = _sniff_package(head)
            if art["package"] == "dll" and head[:2] != b"MZ":
                raise ValidationError(f"{rel} artifacts[{i}]: the file is neither a zip nor a DLL")
            for j, lib in enumerate(art["library_dependencies"]):
                fetch_verified_head(lib["download_url"], lib["sha256"], f"{rel} artifacts[{i}] library[{j}]")
        out = ordered_manifest(m)
        if os.path.exists(dest):
            if _load_json(dest) != out:
                raise ValidationError(f"{rel} would overwrite {os.path.relpath(dest, root)}, "
                                      f"which is published")
            print(f"skipped {rel}: identical to the published {os.path.relpath(dest, root)}")
        else:
            _write_json(dest, out)
            print(f"ingested {rel} -> {os.path.relpath(dest, root)}")
        moved.append(path)
    return moved


def cmd_build(args):
    root = repo_root(args.repo)
    moved = _ingest_submissions(root) if args.ingest else []
    mods = _collect_manifests(root)
    reps = load_replacements(root)
    rep_errs = validate_replacements(reps, mods)
    if rep_errs:
        raise ValidationError(f"{REPLACEMENTS_FILE} is invalid:\n  - " + "\n  - ".join(rep_errs))

    # Checked repo-wide: a new release can break an old dependent.
    target_errs = []
    for mod_id in sorted(mods):
        for version in sorted(mods[mod_id], key=_vkey):
            errs, warns = validate_dependency_targets(mods[mod_id][version], mods)
            target_errs += [f"{mod_id} {version}: {e}" for e in errs]
            for w in warns:
                print(f"note  {mod_id} {version}: {w}")
    if target_errs:
        raise ValidationError("dependencies share no target with their dependents:\n  - "
                              + "\n  - ".join(target_errs))

    # A replaced mod keeps its manifests and pointers, so a server still on it
    # can be joined, but leaves the listing.
    repo_index = {"index_version": SUPPORTED_INDEX_MAJOR, "mods": {}}
    if reps:
        repo_index["replaced"] = {
            old_id: {k: reps[old_id][k] for k in _REPLACEMENT_FIELDS if k in reps[old_id]}
            for old_id in sorted(reps)}
    for mod_id in sorted(mods):
        versions = mods[mod_id]
        author, repo = parse_id(mod_id)
        mod_dir = os.path.join(root, "manifests", author, repo)
        ordered_versions = sorted(versions, key=_vkey)
        by_major = {}
        for v in ordered_versions:
            by_major.setdefault(v.split(".")[0], []).append(v)

        _write_json(os.path.join(mod_dir, "latest.json"),
                    ordered_manifest(versions[ordered_versions[-1]]))
        for major, vs in by_major.items():
            _write_json(os.path.join(mod_dir, f"latest.{major}.json"),
                        ordered_manifest(versions[vs[-1]]))

        majors = sorted(by_major, key=int)
        if mod_id in reps:
            print(f"kept {mod_id} unlisted: replaced by {reps[mod_id]['by']}")
            continue
        repo_index["mods"][mod_id] = {
            major: summary_entry(versions[by_major[major][-1]], by_major[major])
            for major in majors}
        print(f"indexed {mod_id}: majors {majors} (latest {ordered_versions[-1]})")

    _write_json(os.path.join(root, "repository.json"), repo_index)
    print(f"\nwrote repository.json ({len(repo_index['mods'])} mod(s), "
          f"{len(reps)} replaced)")

    if args.prune:
        sub_root = os.path.abspath(os.path.join(root, "submissions"))
        for path in moved:
            os.remove(path)
            d = os.path.dirname(path)
            while os.path.abspath(d) != sub_root and os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
                d = os.path.dirname(d)
        if moved:
            print(f"pruned {len(moved)} ingested submission file(s)")
    return 0


# -- site ----------------------------------------------------------------------

def _screenshot_ok(url, author, repo):
    """None if url may go on the page, else why not: GitHub under the mod's own
    repo (no third-party host sees visitors), immutable (a release asset or a
    commit-pinned raw URL, so a reviewed image can't be swapped), raster only."""
    if not isinstance(url, str) or not _is_https_url(url):
        return "must be an https:// URL"
    p = urlparse(url)
    parts = [seg for seg in p.path.split("/") if seg]
    if not SCREENSHOT_EXT_RE.search(p.path):
        return "must end in .png, .jpg, .jpeg, .webp or .gif (an .svg can carry script)"
    if len(parts) < 3 or parts[0].lower() != author.lower() or parts[1].lower() != repo.lower():
        return f"must live under {author}/{repo}"
    host = p.netloc.lower()
    if host == "github.com":
        return None if _release_asset(parts, author, repo) else (
            "on github.com, only a tagged release asset URL is accepted")
    if host == "raw.githubusercontent.com":
        return None if _COMMIT_SHA_RE.match(parts[2]) else (
            "a raw URL must pin a 40-character commit sha rather than a "
            "branch name, which can be repointed after review")
    return "must be hosted on github.com or raw.githubusercontent.com"


def _screenshots_for(m):
    raw = m.get("screenshots")
    if raw is None:
        return []
    if not isinstance(raw, list):
        print(f"note  {m['id']}: screenshots must be a list of URLs, ignored")
        return []
    if len(raw) > SCREENSHOT_MAX:
        print(f"note  {m['id']}: {len(raw)} screenshots listed, only the first "
              f"{SCREENSHOT_MAX} are published")
    author, repo = parse_id(m["id"])
    out = []
    for url in raw[:SCREENSHOT_MAX]:
        why = _screenshot_ok(url, author, repo)
        if why:
            print(f"note  {m['id']}: not publishing screenshot {url!r} - {why}")
        else:
            out.append(url)
    return out


def index_owner(root, explicit=None):
    """The GitHub owner this index belongs to: --owner, else GITHUB_REPOSITORY (set in Actions), else the
    origin remote. None when none of those says."""
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        return repo.split("/")[0]
    try:
        url = subprocess.run(["git", "-C", root, "remote", "get-url", "origin"], capture_output=True,
                             text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    m = re.search(r"github\.com[:/]([^/]+)/", url)
    return m.group(1) if m else None


def cmd_site(args):
    """Bake the mod list into the page. It reads manifests/, not
    repository.json, because the index doesn't carry screenshots."""
    root = repo_root(args.repo)
    template_path = os.path.join(root, "tools", "page.html")
    if not os.path.isfile(template_path):
        raise ValidationError(f"no page template at {template_path}")
    with open(template_path, encoding="utf-8") as f:
        template = f.read()
    if SITE_MARKER not in template:
        raise ValidationError(f"{template_path} has no {SITE_MARKER} to inject into")

    mods = _collect_manifests(root)
    reps = load_replacements(root)
    rows = []
    for mod_id in sorted(set(mods) - set(reps)):
        latest = sorted(mods[mod_id], key=_vkey)[-1]
        m = mods[mod_id][latest]
        rows.append({"id": mod_id, **_display(m), "targets": manifest_targets(m),
                     "parity_required": parity_required(m), "latest": latest,
                     "dependencies": m.get("dependencies") or {},
                     "screenshots": _screenshots_for(m)})
    # The index owner's own mods (ModdingTavern's in ModdingTavern/TavernMods) come first and are marked.
    owner = index_owner(root, args.owner)
    for r in rows:
        r["own"] = bool(owner) and r["id"].split(".")[0].lower() == owner.lower()
    rows.sort(key=lambda r: (not r["own"], r["name"].lower()))

    # Escaping '<' stops a string from closing the <script> it's embedded in.
    data = json.dumps(rows, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    out_dir = args.out or os.path.join(root, "site")
    out_path = os.path.join(out_dir, "index.html")
    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(template.replace(SITE_MARKER, data))

    shots = sum(len(r["screenshots"]) for r in rows)
    print(f"wrote {out_path}: {len(rows)} mod(s), {shots} screenshot(s)")
    return 0


# -- entry point ---------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(prog="modindex", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", help="repository root (default: parent of this tools/ dir)")
    sub = parser.add_subparsers(dest="command", required=True)

    f = sub.add_parser("fill-hashes", help="download a manifest's files and write their sha256 in")
    f.add_argument("paths", nargs="*", help="manifest files or dirs (default: submissions/)")
    f.set_defaults(func=cmd_fill)

    v = sub.add_parser("validate", help="check submission manifests")
    v.add_argument("paths", nargs="*", help="manifest files or dirs (default: submissions/)")
    v.add_argument("--vt-max-malicious", type=int, default=None,
                   help="fail if VirusTotal malicious count exceeds this (default: report only)")
    v.add_argument("--require-vt", action="store_true",
                   help="fail when a VirusTotal scan can't run, as CI does")
    v.set_defaults(func=cmd_validate)

    b = sub.add_parser("build", help="compile pointers + repository.json")
    b.add_argument("--ingest", action="store_true",
                   help="first move validated submissions/ manifests into manifests/")
    b.add_argument("--prune", action="store_true",
                   help="with --ingest, delete the moved submission files afterwards")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("site", help="bake tools/page.html + the mod list into site/index.html")
    s.add_argument("--out", help="output directory (default: site/)")
    s.add_argument("--owner", help="the index's GitHub owner, whose mods go first (default: from Actions or git)")
    s.set_defaults(func=cmd_site)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValidationError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
