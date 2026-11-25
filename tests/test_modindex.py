"""Tests for tools/modindex.py. Offline: the network is stubbed wherever a
command would download. Run: python -m pytest tests"""

import argparse
import contextlib
import copy
import glob
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import urllib.error
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
import modindex as mi

FIXTURES = os.path.join(HERE, "fixtures", "v2")
CLEAN = {"malicious": 0, "suspicious": 0, "harmless": 1, "undetected": 60}
MANIFEST_ORDER = ["manifest_version", "id", "name", "version", "author", "description", "changelog",
                  "icons", "screenshots", "parity_required", "scenes", "dependencies", "incompatible_with",
                  "artifacts"]
ARTIFACT_ORDER = ["targets", "download_url", "sha256", "package", "library_dependencies"]
LIBRARY_ORDER = ["name", "download_url", "sha256", "filename"]


def artifact(owner="Owner", repo="Repo", version="1.0.0", targets=("client_windows", "server"),
             asset=None, **over):
    a = {"targets": list(targets),
         "download_url": (f"https://github.com/{owner}/{repo}/releases/download/"
                          f"v{version}/{asset or repo + '.dll'}"),
         "sha256": "a" * 64, "library_dependencies": []}
    a.update(over)
    return a


def library(name="ExampleLib", sha="b" * 64, **over):
    lib = {"name": name, "download_url": f"https://example.com/downloads/{name}.dll",
           "sha256": sha, "filename": f"{name}.dll"}
    lib.update(over)
    return lib


def manifest(mod_id="Owner.Repo", version="1.0.0", targets=("client_windows", "server"),
             artifacts=None, **over):
    author, repo = (mod_id.split(".", 1) + ["Repo"])[:2]
    d = {"manifest_version": 2, "id": mod_id, "name": repo, "version": version,
         "author": author, "description": "", "parity_required": True, "dependencies": {},
         "artifacts": (artifacts if artifacts is not None
                       else [artifact(author, repo, version, targets)])}
    d.update(over)
    return d


SHA40 = "0123456789abcdef" * 2 + "01234567"


def icon(size, owner="Owner", repo="Repo"):
    return {"size": size, "url": f"https://raw.githubusercontent.com/{owner}/{repo}/{SHA40}/icon-{size}.png"}


def png(width, height=None, pad=b""):
    """The first bytes of a PNG: signature and IHDR chunk."""
    return (mi.PNG_SIGNATURE + (13).to_bytes(4, "big") + b"IHDR" + width.to_bytes(4, "big")
            + (height or width).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00" + pad)


def with_artifact(m, i=0, **over):
    """m with artifacts[i] updated; a value of None removes the key."""
    m = copy.deepcopy(m)
    for k, v in over.items():
        if v is None:
            m["artifacts"][i].pop(k, None)
        else:
            m["artifacts"][i][k] = v
    return m


def without(m, key):
    return {k: v for k, v in m.items() if k != key}


def v1_manifest():
    return {"manifest_version": 1, "id": "Owner.Repo", "name": "Repo", "version": "1.0.0",
            "author": "Owner", "description": "", "client_side": True, "server_side": False,
            "parity_required": True, "dependencies": {}, "library_dependencies": [],
            "download_url": "https://github.com/Owner/Repo/releases/download/v1.0.0/Repo.dll",
            "sha256": "a" * 64}


def scrambled(m):
    """m with its keys reversed at every level."""
    m = dict(reversed(list(m.items())))
    m["artifacts"] = [dict(reversed(list(a.items()))) for a in m["artifacts"]]
    for a in m["artifacts"]:
        a["library_dependencies"] = [dict(reversed(list(lib.items())))
                                     for lib in a["library_dependencies"]]
    return m


def zip_bytes(entries):
    """entries: (name, data) or (name, data, external_attr)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for e in entries:
            info = zipfile.ZipInfo(e[0])
            info.compress_type = zipfile.ZIP_DEFLATED
            if len(e) == 3:
                info.external_attr = e[2]
            zf.writestr(info, e[1])
    return buf.getvalue()


def temp_file(tc, data):
    fd, path = tempfile.mkstemp(prefix="modindex_test_")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    tc.addCleanup(lambda: os.path.exists(path) and os.remove(path))
    return path


def temp_dir(tc):
    path = tempfile.mkdtemp(prefix="modindex_test_")
    tc.addCleanup(shutil.rmtree, path, True)
    return path


def stub(tc, obj, name, value):
    saved = getattr(obj, name)
    setattr(obj, name, value)
    tc.addCleanup(setattr, obj, name, saved)


def run_quiet(fn, **args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fn(argparse.Namespace(**args))
    return rc, out.getvalue()


class Structure(unittest.TestCase):
    def assertRejects(self, cases):
        for label, (m, needle) in cases.items():
            with self.subTest(label):
                errs = mi.validate_structure(m)
                self.assertTrue([e for e in errs if needle in e], errs)

    def test_valid_shapes_pass(self):
        cases = {
            "one build for pc and server": manifest(),
            "split builds": manifest(artifacts=[
                artifact(targets=["client_windows"], asset="Repo-pc.dll"),
                artifact(targets=["server"], asset="Repo-server.zip")]),
            "pc only": manifest(targets=["client_windows"]),
            "server only": manifest(targets=["server"]),
            "android only": manifest(targets=["client_android"]),
            "all three across two builds": manifest(artifacts=[
                artifact(targets=["client_windows", "server"]),
                artifact(targets=["client_android"], asset="Repo-android.zip")]),
            "package set by the tooling": with_artifact(manifest(), package="zip"),
            "unowned library": with_artifact(manifest(), library_dependencies=[library()]),
            "dependencies": manifest(dependencies={"Other.Kit": "1.2.0", "Third.Party": "2.0.1"}),
            "scenes null": manifest(scenes=None),
        }
        for scenes in (["normal"], ["quest", "tutorial"], ["tutorial"]):
            cases[f"scenes {scenes}"] = manifest(scenes=scenes)
        for targets in (["client_windows"], ["server"], ["client_android"], ["client_windows", "server"]):
            cases[f"parity false, {targets}"] = manifest(targets=targets, parity_required=False)
        for label, m in cases.items():
            with self.subTest(label):
                self.assertEqual(mi.validate_structure(m), [])

    def test_top_level_rules(self):
        cases = {
            "not an object": ([manifest()], "JSON object"),
            "future manifest_version": (manifest(manifest_version=3), "manifest_version must be 2"),
            "boolean manifest_version": (manifest(manifest_version=True), "manifest_version must be 2"),
            "id with no dot": (manifest("noseparator"), "must be '<user>.<repo>'"),
            "two-segment version": (manifest(version="1.0"), "MAJOR.MINOR.PATCH"),
            "version segment over int32": (manifest(version="1.2147483648.0"), "over 2147483647"),
            "parity_required missing": (without(manifest(), "parity_required"),
                                        "parity_required is required"),
            "no dependencies": (without(manifest(), "dependencies"), "dependencies must be an object"),
            "self dependency": (manifest(dependencies={"Owner.Repo": "1.0.0"}), "own id"),
            "every scene listed": (manifest(scenes=["normal", "quest", "tutorial"]), "leave it out"),
        }
        for bad in ("required", "false", 0, 1, None, []):
            cases[f"parity_required {bad!r}"] = (manifest(parity_required=bad), "parity_required")
        for bad in ([], "quest", ["Quest"], ["normal", "arena"], ["quest", "quest"], [1], {"quest": 1}):
            cases[f"scenes {bad!r}"] = (manifest(scenes=bad), "scene")
        deps = {"id with no dot": {"nodot": "1.0.0"}, "id traversal": {"../../evil": "1.0.0"},
                "id separator": {"Owner./evil": "1.0.0"}, "two segments": {"Other.Kit": "1.2"},
                "non-numeric": {"Other.Kit": "banana"}, "prerelease": {"Other.Kit": "1.2.0-rc1"},
                "non-string": {"Other.Kit": 1}, "over int32": {"Other.Kit": "9999999999.0.0"}}
        for label, d in deps.items():
            cases[f"dependency {label}"] = (manifest(dependencies=d), "dependencies")
        self.assertRejects(cases)

    def test_artifact_rules(self):
        m = manifest()
        cases = {
            "no artifacts": (without(m, "artifacts"), "artifacts must be a non-empty list"),
            "artifacts null": (dict(m, artifacts=None), "artifacts must be a non-empty list"),
            "artifact not an object": (manifest(artifacts=[artifact(), "Repo.dll"]),
                                       "artifacts[1] must be an object"),
            "short sha": (with_artifact(m, sha256="abc"), "artifacts[0].sha256"),
            "uppercase sha": (with_artifact(m, sha256="A" * 64), "artifacts[0].sha256"),
            "unknown package": (with_artifact(m, package="rar"), "artifacts[0].package"),
            "no download_url": (with_artifact(m, download_url=None), "download_url is required"),
            "http download_url": (with_artifact(m, download_url=(
                "http://github.com/Owner/Repo/releases/download/v1/x.dll")), "https://"),
            "not on github": (with_artifact(m, download_url="https://example.com/Owner/Repo/x.dll"),
                              "artifacts[0].download_url"),
            "no library_dependencies": (with_artifact(m, library_dependencies=None),
                                        "library_dependencies must be a list"),
            "library with no name": (with_artifact(m, library_dependencies=[library(name="")]),
                                     "name is required"),
            "library file url": (with_artifact(m, library_dependencies=[
                library(download_url="file:///etc/passwd")]), "https://"),
            "target twice in one artifact": (manifest(targets=["client_windows", "client_windows"]), "it already lists"),
        }
        for bad in ([], {}, "Repo.dll"):
            cases[f"artifacts {bad!r}"] = (manifest(artifacts=bad), "artifacts must be a non-empty list")
        for bad in ([], None, "client_windows"):
            cases[f"targets {bad!r}"] = (with_artifact(m, targets=bad), "artifacts[0].targets")
        for bad in ("android", "PC", "client", "", 1):
            cases[f"target {bad!r}"] = (manifest(targets=["client_windows", bad]), "isn't a known target")
        # ':' is a drive letter or an NTFS alternate data stream
        for bad in ("sub/y.dll", "C:ExampleLib.dll", "ExampleLib.dll:payload"):
            cases[f"library filename {bad}"] = (with_artifact(m, library_dependencies=[
                library(filename=bad)]), "bare filename")
        self.assertRejects(cases)

    def test_v1_manifest_gets_one_message(self):
        errs = mi.validate_structure(v1_manifest())
        self.assertEqual(len(errs), 1, errs)
        for needle in ("manifest_version 2", "client_side", "artifacts", "targets", "TEMPLATE.json"):
            self.assertIn(needle, errs[0])

    def test_leftover_v1_fields_point_at_artifacts(self):
        old = {"client_side": True, "server_side": True, "sha256": "a" * 64, "package": "dll",
               "download_url": "https://github.com/Owner/Repo/releases/download/v1/x.dll",
               "library_dependencies": []}
        for key, value in old.items():
            with self.subTest(key):
                errs = mi.validate_structure(manifest(**{key: value}))
                self.assertEqual(len(errs), 1, errs)
                self.assertIn(f"top-level {key}", errs[0])
                self.assertIn("artifacts", errs[0])

    def test_errors_name_their_artifact(self):
        split = manifest(artifacts=[artifact(targets=["client_windows"], asset="Repo-pc.dll"),
                                    artifact(targets=["server"], asset="Repo-server.zip")])
        self.assertEqual(mi.validate_structure(manifest(artifacts=[
            artifact(targets=["client_windows", "server"]),
            artifact(targets=["server"], asset="Repo-server.zip")])),
            ["artifacts[1].targets lists 'server', which artifacts[0] already lists; "
             "each target can have only one build"])
        errs = mi.validate_structure(with_artifact(split, 1, download_url=(
            "https://github.com/someoneelse/thing/releases/download/v1/x.zip")))
        self.assertEqual(len(errs), 1, errs)
        self.assertIn("artifacts[1].download_url", errs[0])
        self.assertIn("Owner/Repo", errs[0])
        self.assertEqual(mi.validate_structure(with_artifact(split, 1, sha256="x")),
                         ["artifacts[1].sha256 must be 64 lowercase hex characters"])
        self.assertEqual(mi.validate_structure(with_artifact(
            split, 1, library_dependencies=[library(), library("Bad", sha="x")])),
            ["artifacts[1].library_dependencies[1].sha256 must be 64 lowercase hex characters"])

    def test_check_urls_false_sets_aside_only_where_files_live(self):
        local = "http://127.0.0.1:8765/files/Repo.dll"
        m = with_artifact(manifest(), download_url=local,
                          library_dependencies=[library(download_url=local)])
        self.assertTrue(mi.validate_structure(m))
        self.assertEqual(mi.validate_structure(m, check_urls=False), [])
        for broken in (with_artifact(m, targets=["android"]), with_artifact(m, sha256="x"),
                       manifest(artifacts=[])):
            self.assertTrue(mi.validate_structure(broken, check_urls=False))

    def test_parse_id(self):
        self.assertEqual(mi.parse_id("User.Repo"), ("User", "Repo"))
        self.assertEqual(mi.parse_id("User.dotted.repo.name"), ("User", "dotted.repo.name"))
        for bad in ("nodot", ".Repo", "-bad.Repo", "User./evil", "User..", "User..."):
            with self.subTest(bad), self.assertRaises(mi.ValidationError):
                mi.parse_id(bad)

    def test_parity_reader_fails_closed(self):
        self.assertTrue(mi.parity_required({}))
        for bad in ("false", "", None, 0, "optional"):
            self.assertTrue(mi.parity_required({"parity_required": bad}), bad)
        self.assertFalse(mi.parity_required({"parity_required": False}))

    def test_sniff_package(self):
        self.assertEqual(mi._sniff_package(b"PK\x03\x04rest"), "zip")
        self.assertEqual(mi._sniff_package(b"MZ\x90\x00rest"), "dll")
        self.assertEqual(mi._sniff_package(b""), "dll")

    def test_manifest_targets_is_the_sorted_union(self):
        m = manifest(artifacts=[artifact(targets=["server"]), artifact(targets=["client_android", "client_windows"])])
        self.assertEqual(mi.manifest_targets(m), ["client_android", "client_windows", "server"])


class CanonicalOrder(unittest.TestCase):
    def test_every_level_is_reordered(self):
        out = mi.ordered_manifest(scrambled(manifest(scenes=["quest"], screenshots=[], changelog="c",
            incompatible_with={}, artifacts=[artifact(package="dll", library_dependencies=[library()])],
            icons=[{"url": "u", "size": 128}])))
        self.assertEqual(list(out), MANIFEST_ORDER)
        self.assertEqual(list(out["icons"][0]), ["size", "url"])
        self.assertEqual(list(out["artifacts"][0]), ARTIFACT_ORDER)
        self.assertEqual(list(out["artifacts"][0]["library_dependencies"][0]), LIBRARY_ORDER)

    def test_unknown_keys_are_kept_at_the_end(self):
        m = manifest(extra=1)
        m["artifacts"][0] = {"x_note": "hi", **m["artifacts"][0]}
        out = mi.ordered_manifest(m)
        self.assertEqual(list(out)[-1], "extra")
        self.assertEqual(list(out["artifacts"][0])[-1], "x_note")

    def test_summary_entry(self):
        entry = mi.summary_entry(manifest(scenes=["quest"], parity_required=False), ["1.0.0"])
        self.assertEqual(list(entry), ["name", "author", "description", "parity_required",
                                       "targets", "scenes", "versions"])
        self.assertIs(entry["parity_required"], False)
        self.assertEqual(entry["scenes"], ["quest"])
        self.assertNotIn("scenes", mi.summary_entry(manifest(), ["1.0.0"]))
        self.assertNotIn("icons", mi.summary_entry(manifest(), ["1.0.0"]))
        entry = mi.summary_entry(manifest(icons=[icon(512), {"url": icon(128)["url"], "size": 128}]), ["1.0.0"])
        self.assertEqual(list(entry)[:4], ["name", "author", "description", "icons"])
        self.assertEqual(entry["icons"], [icon(128), icon(512)])
        self.assertEqual(list(entry["icons"][0]), ["size", "url"])
        # a missing value never reaches the index as relaxed
        self.assertIs(mi.summary_entry(without(manifest(), "parity_required"),
                                       ["1.0.0"])["parity_required"], True)


class ZipBundle(unittest.TestCase):
    def errors(self, entries):
        return mi.inspect_zip_bundle(temp_file(self, zip_bytes(entries)))

    def test_valid_bundle_passes(self):
        self.assertEqual(self.errors([("Bundle.dll", b"MZ"), ("Content/data.bundle", b"x"),
                                      ("Second.dll", b"MZ")]), [])

    def test_rejected(self):
        cases = {
            "no dll": ([("readme.txt", b"hi")], "no .dll"),
            "dll only in a subfolder": ([("sub/Mod.dll", b"MZ")], "archive root"),
            "traversal": ([("Mod.dll", b"MZ"), ("../evil.dll", b"x")], "path traversal"),
            "absolute": ([("Mod.dll", b"MZ"), ("/abs.dll", b"x")], "absolute path"),
            "symlink": ([("Mod.dll", b"MZ"), ("link", b"/etc/passwd", 0o120777 << 16)], "symlink"),
            "drive letter": ([("Mod.dll", b"MZ"), ("C:evil.dll", b"x")], "colon"),
            "alternate data stream": ([("Mod.dll", b"MZ"), ("Mod.dll:payload", b"x")], "colon"),
        }
        for label, (entries, needle) in cases.items():
            with self.subTest(label):
                errs = self.errors(entries)
                self.assertTrue([e for e in errs if needle in e], errs)
        errs = mi.inspect_zip_bundle(temp_file(self, b"not a zip"))
        self.assertIn("not a valid .zip", errs[0])

    def test_caps(self):
        stub(self, mi, "ZIP_MAX_ENTRIES", 3)
        stub(self, mi, "ZIP_RATIO_MIN_SIZE", 1024)
        stub(self, mi, "ZIP_MAX_TOTAL_UNCOMPRESSED", 1024 * 1024)
        errs = self.errors([("m.dll", b"MZ"), ("big.bin", b"\0" * (2 * 1024 * 1024))]
                           + [(f"f{i}", b"x") for i in range(3)])
        self.assertTrue([e for e in errs if "entries" in e], errs)
        self.assertTrue([e for e in errs if "ratio" in e], errs)
        self.assertTrue([e for e in errs if "extracts to" in e], errs)


class ZipMemberScanning(unittest.TestCase):
    """Only code-bearing zip members are sent to VirusTotal."""

    def scan(self, entries, stats=CLEAN):
        seen = []
        def fake(path, sha, api_key):
            with open(path, "rb") as f:
                seen.append(f.read())
            return stats
        stub(self, mi, "vt_scan", fake)
        errs, warns = [], []
        mi._vt_scan_zip_members(temp_file(self, zip_bytes(entries)), "KEY", 0, "mod", errs, warns)
        return seen, errs, warns

    def test_is_code_bearing(self):
        self.assertTrue(mi._is_code_bearing("Mod.dll", b""))
        self.assertTrue(mi._is_code_bearing("run.ps1", b""))
        self.assertFalse(mi._is_code_bearing("model.fbx", b"asdf"))
        self.assertFalse(mi._is_code_bearing("tex.png", b"\x89PNG\r\n"))
        self.assertTrue(mi._is_code_bearing("totally_a.png", b"MZ\x90\x00"))

    def test_only_code_members_scanned(self):
        seen, errs, _ = self.scan([("Mod.dll", b"MZ real"), ("Assets/model.fbx", b"\0" * 4096),
                                   ("Assets/tex.png", b"\x89PNG"), ("sneaky.dat", b"MZ hidden")])
        self.assertEqual(errs, [])
        self.assertEqual(sorted(seen), [b"MZ hidden", b"MZ real"])

    def test_malicious_member_gates(self):
        _, errs, _ = self.scan([("Evil.dll", b"MZ bad")], dict(CLEAN, malicious=5))
        self.assertTrue([e for e in errs if "malicious=5" in e], errs)

    def test_no_code_members_uploads_nothing(self):
        seen, _, warns = self.scan([("Assets/model.fbx", b"\0" * 100), ("readme.txt", b"hi")])
        self.assertEqual(seen, [])
        self.assertTrue([w for w in warns if "no executable members" in w], warns)


class Validate(unittest.TestCase):
    """cmd_validate end to end: downloads come from self.files, and vt_scan
    records each sha it is asked about."""

    def setUp(self):
        self.root = temp_dir(self)
        self.files, self.scanned, self.stats = {}, [], dict(CLEAN)

        def fake_download(url):
            data = self.files[url]
            return temp_file(self, data), hashlib.sha256(data).hexdigest()

        def fake_vt(path, sha, api_key):
            self.scanned.append(sha)
            return self.stats

        stub(self, mi, "download_and_hash", fake_download)
        stub(self, mi, "vt_scan", fake_vt)
        saved = os.environ.get("VIRUSTOTAL_API_KEY")
        os.environ["VIRUSTOTAL_API_KEY"] = "KEY"
        self.addCleanup(lambda: os.environ.__setitem__("VIRUSTOTAL_API_KEY", saved)
                        if saved is not None else os.environ.pop("VIRUSTOTAL_API_KEY", None))

    def serve(self, obj, data):
        """Serve data at obj's download_url and set obj's sha256 to match."""
        self.files[obj["download_url"]] = data
        obj["sha256"] = hashlib.sha256(data).hexdigest()
        return obj

    def validate(self, *manifests, vt_max_malicious=None, report=None):
        paths = []
        for m in manifests:
            paths.append(os.path.join(self.root, "submissions", m["id"], f'{m["version"]}.json'))
            mi._write_json(paths[-1], m)
        return run_quiet(mi.cmd_validate, repo=self.root, paths=paths,
                         vt_max_malicious=vt_max_malicious, require_vt=False, report=report)

    def report(self, *manifests):
        path = os.path.join(self.root, "report.json")
        rc, out = self.validate(*manifests, report=path)
        with open(path, encoding="utf-8") as f:
            return rc, out, json.load(f)

    def test_report_has_each_part_with_what_it_confirmed(self):
        stub(self, mi, "_urlopen", lambda url, timeout: contextlib.nullcontext(io.BytesIO(png(128))))
        m = manifest(artifacts=[self.serve(artifact(library_dependencies=[self.serve(library(), b"MZ lib")]), b"MZ dll")],
                     dependencies={"Other.Kit": "1.2.0"}, icons=[icon(128)])
        rc, out, report = self.report(m)
        self.assertEqual(rc, 0, out)
        self.assertEqual(list(report), list(mi.REPORT_CHECKS) + ["review", "mentions"])
        self.assertEqual({k: report[k]["status"] for k in mi.REPORT_CHECKS},
                         {"Repository lists": "skipped", "Manifest rules": "pass", "Dependencies and libraries": "pass",
                          "Incompatibilities": "skipped", "Files match their hashes": "pass", "VirusTotal scan": "pass",
                          "Icons": "pass"})
        self.assertEqual(report["mentions"], [])
        self.assertEqual(report["Manifest rules"]["title"], "Owner.Repo 1.0.0 follows the manifest rules")
        self.assertIn("Version 1.0.0 is the first release of Owner.Repo", report["Manifest rules"]["ok"])
        self.assertEqual(report["Dependencies and libraries"]["title"], "1 dependency, 1 library")
        self.assertIn("Needs Other.Kit 1.2.0 or later, from another source", report["Dependencies and libraries"]["ok"])
        self.assertEqual(report["Files match their hashes"]["title"], "2 files downloaded and verified")
        self.assertEqual(report["VirusTotal scan"]["title"], "2 files clean")
        self.assertTrue(all("VirusTotal" in n for n in report["VirusTotal scan"]["notes"]))
        self.assertFalse([n for n in report["Files match their hashes"]["notes"] if "VirusTotal" in n])
        self.assertEqual(report["Icons"]["ok"], ["Icon 128: a 128 x 128 px PNG"])
        self.assertIn("  ok    Icon 128: a 128 x 128 px PNG", out)

    def test_report_marks_what_failed_and_what_never_ran(self):
        bad = self.serve(artifact(), b"MZ dll")
        bad["sha256"] = "b" * 64
        rc, out, report = self.report(manifest(artifacts=[bad]))
        self.assertEqual(rc, 1)
        self.assertEqual(report["Files match their hashes"]["status"], "fail")
        self.assertIn("sha256 mismatch", report["Files match their hashes"]["errors"][0])
        self.assertEqual(report["Files match their hashes"]["ok"], [])
        self.assertEqual(report["VirusTotal scan"]["status"], "skipped")   # never got that far
        self.assertEqual(report["Icons"]["status"], "skipped")             # none listed

        rc, out, report = self.report(manifest(version="1.0"))
        self.assertEqual(report["Manifest rules"]["status"], "fail")
        self.assertEqual(report["Manifest rules"]["ok"], [])
        self.assertEqual({k for k in mi.REPORT_CHECKS if report[k]["status"] == "skipped"},
                         set(mi.REPORT_CHECKS) - {"Manifest rules"})

    def split(self, server_zip):
        return manifest(artifacts=[
            self.serve(artifact(targets=["client_windows"], asset="Repo-pc.dll"), b"MZ pc"),
            self.serve(artifact(targets=["server"], asset="Repo-server.zip"), zip_bytes(server_zip))])

    def test_icons_are_downloaded_and_measured(self):
        sizes = {icon(128)["url"]: png(128), icon(256)["url"]: png(200)}
        stub(self, mi, "_urlopen", lambda url, timeout: contextlib.nullcontext(io.BytesIO(sizes[url])))
        m = manifest(artifacts=[self.serve(artifact(), b"MZ dll")], icons=[icon(128), icon(256)])
        rc, out = self.validate(m)
        self.assertEqual(rc, 1, out)
        self.assertIn("icon 256:", out)
        self.assertIn("is 200x200, not 256x256", out)
        self.assertNotIn("icon 128:", out)

    def test_every_artifact_is_downloaded_and_verified(self):
        rc, out = self.validate(self.split([("Repo.dll", b"MZ server")]))
        self.assertEqual(rc, 0, out)
        self.assertIn("artifacts[1] (server): detected a zip bundle", out)

    def test_failures_name_the_artifact(self):
        m = self.split([("Repo.dll", b"MZ server")])
        m["artifacts"][1]["sha256"] = "c" * 64
        rc, out = self.validate(m)
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  artifacts[1] (server): sha256 mismatch", out)
        rc, out = self.validate(self.split([("sub/Repo.dll", b"MZ server")]))
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  artifacts[1] (server): zip bundle has .dll files only in subfolders",
                      out)

    def test_a_published_version_cannot_be_resubmitted(self):
        published = manifest()
        published["artifacts"][0]["package"] = "dll"
        mi._write_json(os.path.join(self.root, "manifests", "Owner", "Repo", "1.0.0.json"), published)
        rc, out = self.validate(self.split([("Repo.dll", b"MZ server")]))
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  Owner.Repo 1.0.0 is already published", out)
        self.assertEqual(self.scanned, [])

    def test_v1_submission_fails_with_the_migration_message(self):
        rc, out = self.validate(v1_manifest())
        self.assertEqual(rc, 1)
        self.assertIn("manifest_version 1 is the old format", out)

    def test_each_distinct_file_is_scanned_once(self):
        lib_bytes, same = b"MZ shared library", b"MZ identical build"
        lib = self.serve(library(), lib_bytes)
        arts = [self.serve(artifact(targets=["client_windows"], asset="Repo-pc.dll"), same),
                self.serve(artifact(targets=["server"], asset="Repo-server.dll"), same)]
        for a in arts:
            a["library_dependencies"] = [dict(lib)]
        rc, out = self.validate(manifest(artifacts=arts))
        self.assertEqual(rc, 0, out)
        self.assertEqual(sorted(self.scanned), sorted(
            hashlib.sha256(b).hexdigest() for b in (same, lib_bytes)))
        self.assertEqual(out.count("already scanned"), 2, out)

    def test_zip_member_matching_a_library_is_scanned_once(self):
        lib_bytes = b"MZ shared library"
        art = self.serve(artifact(asset="Repo.zip"),
                         zip_bytes([("Repo.dll", b"MZ mod"), ("ExampleLib.dll", lib_bytes)]))
        art["library_dependencies"] = [self.serve(library(), lib_bytes)]
        rc, out = self.validate(manifest(artifacts=[art]))
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.scanned), 2)
        self.assertEqual(len(set(self.scanned)), 2)

    def test_a_flagged_file_fails_every_manifest_it_appears_in(self):
        self.stats = dict(CLEAN, malicious=3)
        a, b = manifest("Owner.First"), manifest("Owner.Second")
        for m in (a, b):
            self.serve(m["artifacts"][0], b"MZ same bytes")
        rc, out = self.validate(a, b, vt_max_malicious=0)
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.scanned), 1)
        self.assertEqual(out.count("malicious=3 exceeds"), 2, out)
        self.assertIn("2 manifest(s) checked, 2 failed.", out)

    def test_without_seen_every_call_scans(self):
        path = temp_file(self, b"x")
        for _ in range(2):
            mi._vt_scan_path(path, "d" * 64, "KEY", None, "f", [], [])
        self.assertEqual(len(self.scanned), 2)


class VirusTotalRateLimit(unittest.TestCase):
    def setUp(self):
        mi._vt_request_times.clear()
        self.slept = []
        stub(self, mi.time, "sleep", self.slept.append)
        stub(self, mi.urllib.request, "urlopen", mi.urllib.request.urlopen)

    def http_error(self, code, headers=None):
        return urllib.error.HTTPError("https://x/", code, "err", headers or {}, None)

    def test_retries_on_429_then_succeeds(self):
        calls = []
        def fake(req, timeout=120):
            calls.append(req)
            if len(calls) <= 2:
                raise self.http_error(429, {"Retry-After": "1"})
            return io.BytesIO(b'{"ok": true}')
        mi.urllib.request.urlopen = fake
        self.assertEqual(mi._vt_request("https://x/", "KEY"), {"ok": True})
        self.assertEqual((len(calls), len(self.slept)), (3, 2))

    def test_gives_up_after_max_retries_and_propagates_other_errors(self):
        for code, attempts in ((429, mi._VT_MAX_RETRIES + 1), (500, 1)):
            calls = []
            def fail(req, timeout=120, code=code):
                calls.append(req)
                raise self.http_error(code)
            mi.urllib.request.urlopen = fail
            with self.assertRaises(urllib.error.HTTPError):
                mi._vt_request("https://x/", "KEY")
            self.assertEqual(len(calls), attempts, code)

    def test_throttle(self):
        mi._vt_throttle()
        mi._vt_throttle()
        self.assertEqual(self.slept, [])            # under the cap: no wait
        clock = [1000.0]
        stub(self, mi.time, "monotonic", lambda: clock[0])
        mi.time.sleep = lambda s: (self.slept.append(s), clock.__setitem__(0, clock[0] + s))
        mi._vt_request_times[:] = [1000.0] * 4      # window full at the default cap
        mi._vt_throttle()
        self.assertTrue(self.slept)


class FetchSafety(unittest.TestCase):
    def test_is_https_url(self):
        self.assertTrue(mi._is_https_url("https://github.com/a/b"))
        for bad in ("http://github.com/a/b", "file:///etc/passwd", "ftp://x/y", "not a url", ""):
            self.assertFalse(mi._is_https_url(bad))

    def test_assert_safe_to_fetch(self):
        for bad in ("http://example.com/x", "file:///etc/passwd", "ftp://x/y",
                    "https://127.0.0.1/x", "https://169.254.169.254/x",
                    "https://[::1]/x", "https://10.0.0.5/x", "https://localhost/x"):
            with self.subTest(bad), self.assertRaises(mi.ValidationError):
                mi._assert_safe_to_fetch(bad)
        stub(self, mi.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
        mi._assert_safe_to_fetch("https://example.com/x")


class Build(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)
        stub(self, mi, "fetch_verified_head",
             lambda url, sha256, what: b"PK\x03\x04" if url.endswith(".zip") else b"MZ\x90\x00")

    def submit(self, m):
        mi._write_json(os.path.join(self.root, "submissions", m["id"], f'{m["version"]}.json'), m)

    def place(self, m):
        """Write m straight into manifests/, as ingest would have."""
        author, repo = m["id"].split(".", 1)
        for a in m["artifacts"]:
            a.setdefault("package", "dll")
        mi._write_json(os.path.join(self.root, "manifests", author, repo,
                                    f'{m["version"]}.json'), m)

    def build(self, ingest=True):
        return run_quiet(mi.cmd_build, repo=self.root, ingest=ingest, prune=ingest)

    def read(self, *parts):
        with open(os.path.join(self.root, *parts), encoding="utf-8") as f:
            return json.load(f)

    def test_ingest_writes_manifests_pointers_and_a_slim_index(self):
        self.submit(scrambled(manifest(scenes=["quest"], artifacts=[
            artifact(targets=["client_windows"], asset="Repo-pc.dll", library_dependencies=[library()]),
            artifact(targets=["server"], asset="Repo-server.zip")])))
        self.build()
        base = ("manifests", "Owner", "Repo")
        for name in ("1.0.0.json", "latest.json", "latest.1.json"):
            out = self.read(*base, name)
            self.assertEqual(list(out), [k for k in MANIFEST_ORDER if k in out], name)
            self.assertEqual(list(out["artifacts"][0]), ARTIFACT_ORDER, name)
            self.assertEqual(list(out["artifacts"][0]["library_dependencies"][0]), LIBRARY_ORDER)
            self.assertEqual([a["package"] for a in out["artifacts"]], ["dll", "zip"])
        index = self.read("repository.json")
        self.assertEqual(index["index_version"], 2)
        entry = index["mods"]["Owner.Repo"]["1"]
        self.assertEqual((entry["versions"], entry["name"], entry["targets"]),
                         (["1.0.0"], "Repo", ["client_windows", "server"]))
        for absent in ("download_url", "sha256", "artifacts", "dependencies", "version"):
            self.assertNotIn(absent, entry)
        self.assertFalse(os.path.exists(os.path.join(self.root, "submissions", "Owner.Repo")))

    def test_highest_per_major(self):
        self.submit(manifest(version="1.0.0", targets=["client_windows"]))
        self.submit(manifest(version="1.2.0", artifacts=[
            artifact(version="1.2.0", targets=["server"], asset="Repo-server.dll"),
            artifact(version="1.2.0", targets=["client_windows"], asset="Repo-pc.dll")]))
        self.submit(manifest(version="2.0.0", targets=["client_android"]))
        self.build()
        base = ("manifests", "Owner", "Repo")
        self.assertEqual(self.read(*base, "latest.json")["version"], "2.0.0")
        self.assertEqual(self.read(*base, "latest.1.json")["version"], "1.2.0")
        self.assertEqual(self.read(*base, "latest.2.json")["version"], "2.0.0")
        mods = self.read("repository.json")["mods"]["Owner.Repo"]
        self.assertEqual(list(mods), ["1", "2"])
        self.assertEqual(mods["1"]["versions"], ["1.0.0", "1.2.0"])
        self.assertEqual(mods["1"]["targets"], ["client_windows", "server"])
        self.assertEqual(mods["2"]["targets"], ["client_android"])

    def test_empty_repo_gets_an_empty_index_and_rebuilds_are_idempotent(self):
        self.build()
        self.assertEqual(self.read("repository.json"), {"index_version": 2, "mods": {}})
        self.submit(manifest())
        self.build()
        with open(os.path.join(self.root, "repository.json"), "rb") as f:
            first = f.read()
        self.build()
        with open(os.path.join(self.root, "repository.json"), "rb") as f:
            self.assertEqual(f.read(), first)

    def test_bad_manifests_block_the_build(self):
        compiled = os.path.join(self.root, "manifests", "Owner", "Repo", "1.0.0.json")
        cases = (("invalid submission", lambda: self.submit(manifest(version="nope")), "version"),
                 ("v1 submission", lambda: self.submit(v1_manifest()), "old format"),
                 ("compiled without package", lambda: mi._write_json(compiled, manifest()),
                  "no package"))
        for label, setup, needle in cases:
            with self.subTest(label):
                shutil.rmtree(self.root, ignore_errors=True)
                setup()
                with self.assertRaises(mi.ValidationError) as cm:
                    self.build()
                self.assertIn(needle, str(cm.exception))

    def test_ingest_never_overwrites_a_published_manifest(self):
        self.place(manifest(description="published"))
        self.submit(manifest(description="resubmitted"))
        with self.assertRaises(mi.ValidationError) as cm:
            self.build()
        self.assertIn("would overwrite", str(cm.exception))
        self.assertEqual(self.read("manifests", "Owner", "Repo", "1.0.0.json")["description"],
                         "published")

    def test_dependency_targets_are_enforced_repo_wide(self):
        self.place(manifest("Dev.UIKit", targets=["client_windows"]))
        self.place(manifest("Dev.Dual", dependencies={"Dev.UIKit": "1.0.0"}))
        self.build(ingest=False)        # a pc-only dependency of a pc+server mod is fine
        self.place(manifest("Dev.Srv", targets=["server"], dependencies={"Dev.UIKit": "1.0.0"}))
        os.remove(os.path.join(self.root, "repository.json"))
        with self.assertRaises(mi.ValidationError) as cm:
            self.build(ingest=False)
        self.assertIn("Dev.Srv", str(cm.exception))
        self.assertFalse(os.path.isfile(os.path.join(self.root, "repository.json")))

    def test_template_is_ignored(self):
        tmpl = os.path.join(self.root, "submissions", "TEMPLATE.json")
        mi._write_json(tmpl, {"id": "YourGitHubUser.YourRepo", "version": "1.0.0"})
        self.submit(manifest())
        self.build()
        self.assertTrue(os.path.exists(tmpl))
        self.assertEqual(list(self.read("repository.json")["mods"]), ["Owner.Repo"])
        rc, _ = run_quiet(mi.cmd_validate, repo=self.root, paths=None, vt_max_malicious=None, require_vt=False)
        self.assertEqual(rc, 0)

    def test_repo_template_is_v2_apart_from_its_placeholder_hash(self):
        with open(os.path.join(os.path.dirname(HERE), "submissions", "TEMPLATE.json"),
                  encoding="utf-8") as f:
            tmpl = json.load(f)
        self.assertEqual(mi.validate_structure(tmpl),
                         ["artifacts[0].sha256 must be 64 lowercase hex characters"])
        self.assertEqual(tmpl["artifacts"][0]["targets"], ["client_windows", "server"])


class Icons(unittest.TestCase):
    def test_valid_icons_pass(self):
        for icons in ([icon(128)], [icon(128), icon(256), icon(512)], [icon(512), icon(256)],
                      [{"size": 256, "url": "https://github.com/Owner/Repo/releases/download/v1/i.png"}]):
            with self.subTest(icons):
                self.assertEqual(mi.validate_structure(manifest(icons=icons)), [])
        self.assertEqual(mi.validate_structure(manifest(icons=None)), [])

    def test_bad_icons_are_refused(self):
        cases = {
            "not a list": ("icon.png", "non-empty list"),
            "empty": ([], "non-empty list"),
            "not an object": (["https://x/i.png"], "exactly size and url"),
            "extra key": ([{**icon(128), "alt": "x"}], "exactly size and url"),
            "missing url": ([{"size": 128}], "exactly size and url"),
            "odd size": ([icon(64)], "128/256/512"),
            "size as text": ([{**icon(128), "size": "128"}], "128/256/512"),
            "size as bool": ([{**icon(128), "size": True}], "128/256/512"),
            "duplicate size": ([icon(128), icon(128)], "size 128 twice"),
            "not png": ([{"size": 128, "url": icon(128)["url"][:-4] + ".jpg"}], "must end in .png"),
            "branch url": ([{"size": 128, "url": "https://raw.githubusercontent.com/Owner/Repo/main/i.png"}],
                           "commit sha"),
            "other repo": ([icon(128, owner="Other")], "under Owner/Repo"),
        }
        for label, (icons, needle) in cases.items():
            with self.subTest(label):
                errs = mi.validate_structure(manifest(icons=icons))
                self.assertTrue([e for e in errs if needle in e], errs)

    def serve(self, data):
        stub(self, mi, "_urlopen", lambda url, timeout: contextlib.nullcontext(io.BytesIO(data)))

    def test_icon_problem_checks_the_png(self):
        url = icon(128)["url"]
        self.serve(png(128, pad=b"rest"))
        self.assertIsNone(mi.icon_problem(url, 128))
        self.assertIn("is 128x128, not 256x256", mi.icon_problem(url, 256))
        self.serve(png(128, 96))
        self.assertIn("is 128x96", mi.icon_problem(url, 128))
        self.serve(b"GIF89a" + b"\0" * 30)
        self.assertIn("isn't a PNG", mi.icon_problem(url, 128))
        self.serve(png(128, pad=b"\0" * mi.ICON_MAX_BYTES))
        self.assertIn("is over 1024 KB", mi.icon_problem(url, 128))

        def refuse(url, timeout):
            raise urllib.error.URLError("down")
        stub(self, mi, "_urlopen", refuse)
        self.assertIn("could not download", mi.icon_problem(url, 128))


class Site(unittest.TestCase):
    def test_screenshot_rules(self):
        sha = SHA40
        ok = ["https://github.com/Owner/Repo/releases/download/v1/a.png",
              "https://github.com/owner/repo/releases/download/v1/a.JPG",
              f"https://raw.githubusercontent.com/Owner/Repo/{sha}/docs/a.webp"]
        bad = {"http://github.com/Owner/Repo/releases/download/v1/a.png": "https",
               "https://github.com/Owner/Repo/releases/download/v1/a.svg": ".png",
               "https://github.com/Other/Repo/releases/download/v1/a.png": "under Owner/Repo",
               "https://github.com/Owner/Repo/blob/main/a.png": "release asset",
               "https://raw.githubusercontent.com/Owner/Repo/main/a.png": "commit sha",
               "https://example.com/Owner/Repo/x/a.png": "github.com"}
        for url in ok:
            self.assertIsNone(mi._image_url_error(url, "Owner", "Repo"), url)
        for url, needle in bad.items():
            self.assertIn(needle, mi._image_url_error(url, "Owner", "Repo"), url)
        self.assertIn(".png", mi._image_url_error(ok[2], "Owner", "Repo", png_only=True))

    @staticmethod
    def _write_page(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("<script>window.MODS = /*__MODS__*/[];</script>")

    @staticmethod
    def _baked_rows(path):
        with open(path, encoding="utf-8") as f:
            page = f.read()
        return page[page.index("= ") + 2:page.rindex(";")]

    def test_site_bakes_one_row_per_mod(self):
        root = temp_dir(self)
        self._write_page(os.path.join(root, "web", "dist", "index.html"))   # what npm run build leaves
        shots = [f"https://github.com/Owner/Repo/releases/download/v1/{i}.png" for i in range(5)]
        for v, extra in (("1.0.0", {}), ("1.1.0", {"description": "</script>", "screenshots": shots,
                                                   "icons": [icon(128)]})):
            m = manifest(version=v, **extra)
            m["artifacts"][0]["package"] = "dll"
            mi._write_json(os.path.join(root, "manifests", "Owner", "Repo", f"{v}.json"), m)
        rc, out = run_quiet(mi.cmd_site, repo=root, template=None, out=None, owner=None)
        self.assertEqual(rc, 0)
        self.assertIn("only the first 4", out)
        data = self._baked_rows(os.path.join(root, "site", "index.html"))
        self.assertNotIn("<", data)          # nothing can close the <script>
        rows = json.loads(data)
        self.assertEqual([(r["id"], r["latest"], r["description"], len(r["screenshots"]), r["icons"])
                          for r in rows], [("Owner.Repo", "1.1.0", "</script>", 4, [icon(128)])])

    def test_site_template_and_out(self):
        root = temp_dir(self)
        m = manifest()
        m["artifacts"][0]["package"] = "dll"
        mi._write_json(os.path.join(root, "manifests", "Owner", "Repo", "1.0.0.json"), m)
        out_dir = os.path.join(root, "elsewhere")
        site = ["--repo", root, "site", "--out", out_dir]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            # No built page yet: a clear error, not a traceback.
            self.assertEqual(mi.main(site), 1)
            self.assertIn("npm run build", err.getvalue())
            template = os.path.join(root, "page.html")
            self._write_page(template)
            self.assertEqual(mi.main(site + ["--template", template, "--owner", "owner"]), 0)
        rows = json.loads(self._baked_rows(os.path.join(out_dir, "index.html")))
        self.assertEqual([(r["id"], r["own"]) for r in rows], [("Owner.Repo", True)])
        self.assertFalse(os.path.exists(os.path.join(root, "site")))


class FillHashes(unittest.TestCase):
    def fill(self, m):
        root = temp_dir(self)
        stub(self, mi, "_sha256_of_url", lambda url: hashlib.sha256(url.encode()).hexdigest())
        path = os.path.join(root, "submissions", m["id"], f'{m["version"]}.json')
        mi._write_json(path, m)
        rc, _ = run_quiet(mi.cmd_fill, repo=root, paths=[path])
        with open(path, encoding="utf-8") as f:
            return rc, json.load(f)

    def test_fill_writes_every_artifact_and_library_hash(self):
        rc, out = self.fill(manifest(artifacts=[
            artifact(targets=["client_windows"], asset="Repo-pc.dll", sha256="P",
                     library_dependencies=[library("A", sha="P")]),
            artifact(targets=["server"], asset="Repo-server.zip", sha256="P",
                     library_dependencies=[library("B", sha="P")])]))
        self.assertEqual(rc, 0)
        arts = out["artifacts"]
        for obj in arts + [lib for a in arts for lib in a["library_dependencies"]]:
            self.assertEqual(obj["sha256"], hashlib.sha256(obj["download_url"].encode()).hexdigest())
        self.assertEqual(mi.validate_structure(out), [])

    def test_v1_file_is_refused_and_left_alone(self):
        self.assertEqual(self.fill(v1_manifest()), (1, v1_manifest()))


class VersionFloor(unittest.TestCase):
    KNOWN = {"Owner.Repo": {"1.2.0": {}, "2.0.0": {}, "10.0.0": {}}}

    def floor(self, version):
        return mi.version_floor_error({"id": "Owner.Repo", "version": version}, self.KNOWN)

    def test_new_mod_takes_any_version(self):
        self.assertIsNone(mi.version_floor_error({"id": "New.Mod", "version": "0.0.1"}, self.KNOWN))

    def test_an_existing_version_is_refused(self):
        self.assertIn("already published", self.floor("2.0.0"))

    def test_lower_than_its_majors_highest_is_refused(self):
        self.assertIn("lower than 1.2.0, the highest published 1.x", self.floor("1.1.9"))

    def test_a_fix_to_an_older_major_is_allowed(self):
        self.assertIsNone(self.floor("1.2.1"))
        self.assertIsNone(self.floor("2.0.1"))

    def test_a_new_major_below_the_newest_is_refused(self):
        self.assertIn("would start major 3, below the newest published version 10.0.0", self.floor("3.0.0"))

    def test_a_new_highest_major_is_allowed(self):
        self.assertIsNone(self.floor("11.0.0"))

    def test_validate_refuses_a_lower_version(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        published = manifest(version="1.2.0")
        mi._write_json(os.path.join(root, "manifests", "Owner", "Repo", "1.2.0.json"), published)
        path = os.path.join(root, "submissions", "Owner.Repo", "1.1.0.json")
        mi._write_json(path, manifest(version="1.1.0"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = mi.cmd_validate(argparse.Namespace(repo=root, paths=[path], vt_max_malicious=None, require_vt=False))
        self.assertEqual(rc, 1)
        self.assertIn("FAIL  Owner.Repo 1.1.0 is lower than 1.2.0", out.getvalue())


class DependencyTargets(unittest.TestCase):
    """Differing targets are allowed (with a note); no shared target is an error."""

    def check(self, m, *known):
        index = {}
        for k in known:
            index.setdefault(k["id"], {})[k["version"]] = k
        return mi.validate_dependency_targets(m, index)

    def mod(self, targets=("client_windows", "server"), artifacts=None, minimum="1.0.0"):
        return manifest("Dev.Mod", targets=targets, artifacts=artifacts,
                        dependencies={"Dev.Kit": minimum})

    def test_partial_overlap_is_a_note(self):
        split = [artifact("Dev", "Mod", targets=["server"]),
                 artifact("Dev", "Mod", targets=["client_windows", "client_android"])]
        cases = ((self.mod(), ["client_windows"], "server build will load without it"),
                 (self.mod(), ["server"], "client_windows build"),
                 (self.mod(artifacts=split), ["client_windows"], "client_android+server builds will load without it"))
        for mod, theirs, needle in cases:
            with self.subTest(needle):
                errs, warns = self.check(mod, manifest("Dev.Kit", targets=theirs))
                self.assertEqual(errs, [])
                self.assertEqual(len(warns), 1)
                self.assertIn(needle, warns[0])

    def test_covering_targets_are_silent(self):
        self.assertEqual(self.check(self.mod(), manifest("Dev.Kit")), ([], []))
        self.assertEqual(self.check(self.mod(["client_windows"]),
                                    manifest("Dev.Kit", targets=["client_windows", "server", "client_android"])), ([], []))

    def test_no_shared_target_is_rejected(self):
        for mine, theirs in ((["server"], ["client_windows"]), (["client_windows"], ["server"]),
                             (["client_android"], ["client_windows", "server"]), (["client_windows", "server"], ["client_android"])):
            with self.subTest(mine=mine, theirs=theirs):
                errs, _ = self.check(self.mod(mine), manifest("Dev.Kit", targets=theirs))
                self.assertEqual(len(errs), 1)
                self.assertIn("share no target", errs[0])

    def test_judges_the_version_an_install_would_pick(self):
        mod = self.mod(["server"], minimum="1.1.0")
        # the highest release in the minimum's major wins
        self.assertEqual(self.check(mod, manifest("Dev.Kit", "1.1.0", targets=["client_windows"]),
                                    manifest("Dev.Kit", "1.5.0")), ([], []))
        # another major, or a release below the minimum, isn't consulted, and an
        # unknown dependency is only a note
        for known in ([manifest("Dev.Kit", "2.0.0")], [manifest("Dev.Kit", "1.0.0")], []):
            errs, warns = self.check(mod, *known)
            self.assertEqual(errs, [])
            self.assertIn("isn't in this repository", warns[0])

    def test_malformed_version_is_left_to_validate_structure(self):
        mod = self.mod(minimum="not-a-version")
        self.assertEqual(self.check(mod), ([], []))
        self.assertTrue(mi.validate_structure(mod))


class ReferenceFixtures(unittest.TestCase):
    """tests/fixtures/v2 was generated from docs/REPO_STRUCTURE.md by an
    independent script, for a local http:// repo. It pins this tool to the same
    reading of the spec as the launcher and TavernLib."""

    def manifests(self):
        out = []
        for path in sorted(glob.glob(os.path.join(FIXTURES, "manifests", "*", "*", "*.json"))):
            with open(path, encoding="utf-8") as f:
                out.append(json.load(f))
        self.assertEqual(len(out), 3)
        return out

    def test_only_the_url_rules_fail_and_keys_are_canonical(self):
        for m in self.manifests():
            with self.subTest(m["id"]):
                self.assertEqual(mi.validate_structure(m, check_urls=False), [])
                for e in mi.validate_structure(m):
                    self.assertIn("download_url must be an https:// URL", e)
                self.assertEqual(json.dumps(mi.ordered_manifest(m)), json.dumps(m))

    def test_build_reproduces_the_reference_index(self):
        """Rehosted on GitHub so the URL rules pass, key order included."""
        root = temp_dir(self)
        for m in self.manifests():
            author, repo = mi.parse_id(m["id"])
            for a in m["artifacts"]:
                a["download_url"] = (f"https://github.com/{author}/{repo}/releases/download/"
                                     f"v{m['version']}/{a['download_url'].rsplit('/', 1)[1]}")
                for lib in a["library_dependencies"]:
                    lib["download_url"] = "https://example.com/" + lib["filename"]
            mi._write_json(os.path.join(root, "manifests", author, repo,
                                        f"{m['version']}.json"), m)
        _, out = run_quiet(mi.cmd_build, repo=root, ingest=False, prune=False)
        self.assertIn("ExampleDev.PcHelper 1.0.0 has builds for client_windows only", out)
        with open(os.path.join(root, "repository.json"), encoding="utf-8") as f:
            built = json.load(f)
        with open(os.path.join(FIXTURES, "repository.json"), encoding="utf-8") as f:
            reference = json.load(f)
        self.assertEqual(json.dumps(built, ensure_ascii=False),
                         json.dumps(reference, ensure_ascii=False))



class ListedFields(unittest.TestCase):
    """changelog, incompatible_with, and unknown fields."""

    def errors(self, **over):
        return mi.validate_structure(manifest(**over))

    def test_unknown_fields_are_refused_at_every_level(self):
        self.assertIn("'incompatable_with'", " ".join(self.errors(incompatable_with={})))
        m = with_artifact(manifest(), url="x")
        self.assertIn("artifacts[0] has an unknown field 'url'", " ".join(mi.validate_structure(m)))
        m = manifest(artifacts=[artifact(library_dependencies=[library(version="1")])])
        self.assertIn("unknown field 'version'", " ".join(mi.validate_structure(m)))
        self.assertEqual(self.errors(), [])

    def test_changelog(self):
        self.assertEqual(self.errors(changelog="Fixed the dye vats."), [])
        for bad in ("", "   ", 3, "x" * (mi.CHANGELOG_MAX + 1)):
            self.assertIn("changelog", " ".join(self.errors(changelog=bad)), bad)

    def test_incompatible_with(self):
        self.assertEqual(self.errors(incompatible_with={}), [])
        self.assertEqual(self.errors(incompatible_with={"Other.Kit": {"note": "Both patch vats", "below": "2.0.0"}}), [])
        bad = {
            "own id": ({"owner.repo": {"note": "x"}}, "own id"),
            "bad id": ({"no-dot": {"note": "x"}}, "not a valid mod id"),
            "no note": ({"Other.Kit": {}}, ".note must be text"),
            "long note": ({"Other.Kit": {"note": "x" * (mi.NOTE_MAX + 1)}}, ".note must be text"),
            "bad below": ({"Other.Kit": {"note": "x", "below": "2.0"}}, "MAJOR.MINOR.PATCH"),
            "unknown key": ({"Other.Kit": {"note": "x", "since": "1.0.0"}}, "unknown field 'since'"),
            "not an object": ([], "must be an object"),
            "string entry": ({"Other.Kit": "x"}, 'with "note"'),
        }
        for name, (value, needle) in bad.items():
            self.assertIn(needle, " ".join(self.errors(incompatible_with=value)), name)

    def test_new_fields_keep_their_place(self):
        out = mi.ordered_manifest(scrambled(manifest(changelog="c", incompatible_with={})))
        keys = list(out)
        self.assertEqual(keys.index("changelog"), keys.index("description") + 1)
        self.assertEqual(keys.index("incompatible_with"), keys.index("dependencies") + 1)


class Incompatibilities(unittest.TestCase):
    """declare_incompatibilities and validate_incompatibilities on their own."""

    A, B = "Owner.Repo", "Other.Kit"

    def declare(self, m, known, incs):
        return mi.declare_incompatibilities(m, known, incs)

    def test_a_new_pair_with_the_other_side_bounded(self):
        incs = []
        m = manifest(incompatible_with={self.B: {"note": "Both patch vats", "below": "2.0.0"}})
        notes, owners = self.declare(m, {}, incs)
        self.assertEqual(incs, [{"mods": {self.B: {"below": "2.0.0"}, self.A: {}}, "note": "Both patch vats"}])
        self.assertEqual(owners, [("Other", self.B)])
        self.assertIn("until Other.Kit 2.0.0", notes[0])

    def test_same_owner_is_not_mentioned(self):
        _, owners = self.declare(manifest(incompatible_with={"owner.Tool": {"note": "x"}}), {}, [])
        self.assertEqual(owners, [])

    def test_dropping_it_in_a_later_release_marks_it_fixed(self):
        v1 = manifest(incompatible_with={self.B: {"note": "x"}})
        incs = []
        self.declare(v1, {}, incs)
        known = {self.A: {"1.0.0": v1}}
        notes, owners = self.declare(manifest(version="1.1.0"), known, incs)
        self.assertEqual(incs[0]["mods"][self.A], {"below": "1.1.0"})
        self.assertIn("no longer lists Other.Kit", notes[0])
        self.assertEqual(owners, [])
        # Listing it again undoes that.
        known[self.A]["1.1.0"] = manifest(version="1.1.0")
        notes, owners = self.declare(manifest(version="1.2.0", incompatible_with={self.B: {"note": "x"}}), known, incs)
        self.assertEqual(incs[0]["mods"][self.A], {})
        self.assertIn("lists it again", notes[0])
        self.assertEqual(owners, [])        # the pair isn't new

    def test_a_fix_to_an_older_major_marks_nothing(self):
        incs = []
        v2 = manifest(version="2.0.0", incompatible_with={self.B: {"note": "x"}})
        self.declare(v2, {}, incs)
        self.declare(manifest(version="1.5.0"), {self.A: {"2.0.0": v2}}, incs)
        self.assertEqual(incs[0]["mods"][self.A], {})

    def test_a_removed_pair_stays_removed_when_dropped(self):
        known = {self.A: {"1.0.0": manifest(incompatible_with={self.B: {"note": "x"}})}}
        incs = []
        notes, _ = self.declare(manifest(version="1.1.0"), known, incs)
        self.assertEqual((incs, notes), ([], []))

    def test_note_and_below_updates(self):
        incs = [{"mods": {self.A: {}, self.B: {}}, "note": "old"}]
        notes, _ = self.declare(manifest(incompatible_with={"other.kit": {"note": "new", "below": "3.1.0"}}), {}, incs)
        self.assertEqual(incs, [{"mods": {self.A: {}, self.B: {"below": "3.1.0"}}, "note": "new"}])
        self.assertIn("works with it from 3.1.0", notes[0])

    def test_validate_the_list(self):
        mods = {self.A: {"1.0.0": manifest()}, self.B: {"1.0.0": manifest(self.B)}}
        good = [{"mods": {self.A: {}, self.B: {"below": "2.0.0"}}, "note": "x"}]
        self.assertEqual(mi.validate_incompatibilities(good, mods, {}), [])
        cases = {
            "unpublished": ([{"mods": {self.A: {}, "Gone.Mod": {}}, "note": "x"}], {}, "isn't published"),
            "replaced": (good, {self.B: {"by": self.A}}, "has been replaced"),
            "one mod": ([{"mods": {self.A: {}}, "note": "x"}], {}, "two different mods"),
            "same mod twice": ([{"mods": {self.A: {}, "owner.repo": {}}, "note": "x"}], {}, "two different mods"),
            "no note": ([{"mods": {self.A: {}, self.B: {}}}], {}, "note must be text"),
            "twice": (good + good, {}, "more than once"),
            "bad below": ([{"mods": {self.A: {}, self.B: {"below": "x"}}, "note": "x"}], {}, "below"),
            "unknown side key": ([{"mods": {self.A: {"from": "1.0.0"}, self.B: {}}, "note": "x"}], {}, "'from'"),
            "not an object": (["x"], {}, "must be an object"),
        }
        for name, (incs, reps, needle) in cases.items():
            self.assertIn(needle, " ".join(mi.validate_incompatibilities(incs, mods, reps)), name)

    def test_validate_withdrawn(self):
        mods = {self.A: {"1.0.0": manifest()}}
        self.assertEqual(mi.validate_withdrawn({self.A: {"1.0.0": "Corrupts saves"}}, mods), [])
        for wd, needle in (({"Gone.Mod": {"1.0.0": "x"}}, "no such mod"),
                           ({self.A: {"9.9.9": "x"}}, "no such version"),
                           ({self.A: {"1.0.0": ""}}, "reason must be text"),
                           ({self.A: {}}, "version -> reason")):
            self.assertIn(needle, " ".join(mi.validate_withdrawn(wd, mods)), wd)


class ValidateLists(unittest.TestCase):
    """The PR check with incompatibilities and withdrawn versions."""

    setUp, serve, validate, report = Validate.setUp, Validate.serve, Validate.validate, Validate.report

    def publish(self, m):
        author, repo = m["id"].split(".", 1)
        mi._write_json(os.path.join(self.root, "manifests", author, repo, f'{m["version"]}.json'), m)

    def write(self, name, data):
        mi._write_json(os.path.join(self.root, name), data)

    def submission(self, **over):
        return manifest(artifacts=[self.serve(artifact(), b"MZ dll")], **over)

    def test_a_new_incompatibility_is_flagged_and_its_owner_mentioned(self):
        self.publish(manifest("Other.Kit"))
        rc, out, report = self.report(self.submission(incompatible_with={"Other.Kit": {"note": "Both patch vats"}}))
        self.assertEqual(rc, 0, out)
        part = report["Incompatibilities"]
        self.assertEqual((part["status"], part["ok"]), ("pass", ["Doesn't work with Other.Kit"]))
        self.assertIn("Adds Owner.Repo and Other.Kit as incompatible: Both patch vats", part["notes"])
        self.assertIn("Adds Owner.Repo and Other.Kit as incompatible: Both patch vats", report["review"])
        self.assertEqual(report["mentions"], [{"login": "Other", "mod": "Other.Kit", "by": "Owner.Repo"}])
        self.assertFalse(any("VirusTotal clean" in n for n in report["review"]))

    def test_an_already_listed_pair_mentions_nobody(self):
        self.publish(manifest("Other.Kit"))
        self.write(mi.INCOMPATIBILITIES_FILE, [{"mods": {"Other.Kit": {}, "Owner.Repo": {}}, "note": "Both patch vats"}])
        rc, out, report = self.report(self.submission(incompatible_with={"Other.Kit": {"note": "Both patch vats"}}))
        self.assertEqual(rc, 0, out)
        self.assertEqual((report["mentions"], report["Incompatibilities"]["notes"]), ([], []))
        self.assertEqual(report["Repository lists"]["status"], "pass")

    def test_what_it_names_must_be_listed_here_and_not_a_dependency(self):
        self.publish(manifest("Other.Kit"))
        self.publish(manifest("Old.Kit"))
        self.write(mi.REPLACEMENTS_FILE, {"Old.Kit": {"by": "Other.Kit"}})
        for named, deps, needle in (("Nobody.Here", {}, "isn't in this repository"),
                                    ("other.kit", {}, "isn't in this repository"),
                                    ("Old.Kit", {}, "has been replaced by Other.Kit"),
                                    ("Other.Kit", {"Other.Kit": "1.0.0"}, "depends on")):
            rc, out, report = self.report(self.submission(dependencies=deps, incompatible_with={named: {"note": "x"}}))
            self.assertEqual(rc, 1, named)
            self.assertEqual(report["Incompatibilities"]["status"], "fail", named)
            self.assertIn(needle, " ".join(report["Incompatibilities"]["errors"]), named)
            self.assertEqual(report["mentions"], [], named)
            self.assertEqual(report["Files match their hashes"]["status"], "skipped", named)

    def test_bad_lists_fail_their_part(self):
        self.write(mi.INCOMPATIBILITIES_FILE, [{"mods": {"Owner.Repo": {}, "Gone.Mod": {}}, "note": "x"}])
        self.write(mi.WITHDRAWN_FILE, {"Gone.Mod": {"1.0.0": "x"}})
        rc, out, report = self.report(self.submission())
        self.assertEqual(rc, 1)
        errors = " ".join(report["Repository lists"]["errors"])
        self.assertIn("Gone.Mod isn't published here", errors)
        self.assertIn("withdrawn.json: Gone.Mod: no such mod", errors)

    def test_a_dependency_only_withdrawn_versions_meet_fails(self):
        self.publish(manifest("Other.Kit", version="1.2.0"))
        self.write(mi.WITHDRAWN_FILE, {"Other.Kit": {"1.2.0": "Corrupts saves"}})
        rc, out, report = self.report(self.submission(dependencies={"Other.Kit": "1.0.0"}))
        self.assertEqual(rc, 1, out)
        self.assertIn("every version that meets it has been withdrawn",
                      " ".join(report["Dependencies and libraries"]["errors"]))
        self.assertIn("Other.Kit 1.2.0 is withdrawn: Corrupts saves", report["Repository lists"]["ok"])


class BuildLists(unittest.TestCase):
    """Ingest and build with incompatibilities and withdrawn versions."""

    setUp, submit, place, build, read = Build.setUp, Build.submit, Build.place, Build.build, Build.read

    def test_ingest_adds_and_later_fixes_a_pair(self):
        self.place(manifest("Other.Kit"))
        self.submit(manifest(incompatible_with={"Other.Kit": {"note": "Both patch vats", "below": "2.0.0"}}))
        self.build()
        pair = {"mods": {"Other.Kit": {"below": "2.0.0"}, "Owner.Repo": {}}, "note": "Both patch vats"}
        self.assertEqual(self.read(mi.INCOMPATIBILITIES_FILE), [pair])
        self.assertEqual(self.read("repository.json")["incompatible"], [pair])
        self.assertIn("incompatible_with", self.read("manifests", "Owner", "Repo", "1.0.0.json"))

        self.submit(manifest(version="1.1.0"))
        rc, out = self.build()
        self.assertEqual(rc, 0, out)
        pair["mods"]["Owner.Repo"] = {"below": "1.1.0"}
        self.assertEqual(self.read(mi.INCOMPATIBILITIES_FILE), [pair])
        self.assertEqual(self.read("repository.json")["incompatible"], [pair])

    def test_a_maintainers_list_needs_no_manifest(self):
        self.place(manifest("Other.Kit"))
        self.place(manifest())
        mi._write_json(os.path.join(self.root, mi.INCOMPATIBILITIES_FILE),
                       [{"mods": {"Owner.Repo": {}, "Other.Kit": {}}, "note": "Reported by players"}])
        rc, out = self.build(ingest=False)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read("repository.json")["incompatible"],
                         [{"mods": {"Other.Kit": {}, "Owner.Repo": {}}, "note": "Reported by players"}])

    def test_a_bad_list_blocks_the_build(self):
        self.place(manifest())
        mi._write_json(os.path.join(self.root, mi.WITHDRAWN_FILE), {"Owner.Repo": {"9.0.0": "x"}})
        with self.assertRaises(mi.ValidationError) as cm:
            self.build(ingest=False)
        self.assertIn("no such version", str(cm.exception))

    def test_withdrawn_versions_leave_the_pointers_and_listing(self):
        for v in ("1.0.0", "1.1.0", "2.0.0"):
            self.place(manifest(version=v, changelog=f"Release {v}"))
        self.build(ingest=False)
        base = ("manifests", "Owner", "Repo")
        mi._write_json(os.path.join(self.root, mi.WITHDRAWN_FILE),
                       {"Owner.Repo": {"2.0.0": "Corrupts saves", "1.1.0": "Crashes servers"}})
        rc, out = self.build(ingest=False)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.read(*base, "latest.json")["version"], "1.0.0")
        self.assertEqual(self.read(*base, "latest.1.json")["version"], "1.0.0")
        self.assertFalse(os.path.exists(os.path.join(self.root, *base, "latest.2.json")))
        self.assertTrue(os.path.exists(os.path.join(self.root, *base, "2.0.0.json")))    # manifests stay
        index = self.read("repository.json")
        self.assertEqual(list(index["mods"]["Owner.Repo"]), ["1"])
        self.assertEqual(index["mods"]["Owner.Repo"]["1"]["versions"], ["1.0.0"])
        self.assertEqual(index["mods"]["Owner.Repo"]["1"]["changelog"], "Release 1.0.0")
        self.assertEqual(index["withdrawn"], {"Owner.Repo": {"1.1.0": "Crashes servers", "2.0.0": "Corrupts saves"}})

        mi._write_json(os.path.join(self.root, mi.WITHDRAWN_FILE),
                       {"Owner.Repo": {v: "x" for v in ("1.0.0", "1.1.0", "2.0.0")}})
        rc, out = self.build(ingest=False)
        self.assertEqual(rc, 0, out)
        self.assertNotIn("Owner.Repo", self.read("repository.json")["mods"])
        self.assertEqual([n for n in os.listdir(os.path.join(self.root, *base)) if n.startswith("latest")], [])
        self.assertIn("every version is withdrawn", out)

    def test_the_site_skips_withdrawn_versions(self):
        for v in ("1.0.0", "1.1.0"):
            self.place(manifest(version=v, changelog=f"Release {v}"))
        mi._write_json(os.path.join(self.root, mi.WITHDRAWN_FILE), {"Owner.Repo": {"1.1.0": "x"}})
        Site._write_page(os.path.join(self.root, "web", "dist", "index.html"))
        rc, out = run_quiet(mi.cmd_site, repo=self.root, template=None, out=None, owner=None)
        self.assertEqual(rc, 0, out)
        rows = json.loads(Site._baked_rows(os.path.join(self.root, "site", "index.html")))
        self.assertEqual([(r["latest"], r["changelog"]) for r in rows], [("1.0.0", "Release 1.0.0")])


if __name__ == "__main__":
    unittest.main()
