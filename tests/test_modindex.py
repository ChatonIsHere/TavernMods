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
MANIFEST_ORDER = ["manifest_version", "id", "name", "version", "author", "description",
                  "screenshots", "parity_required", "scenes", "dependencies", "artifacts"]
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
        out = mi.ordered_manifest(scrambled(manifest(scenes=["quest"], screenshots=[], artifacts=[
            artifact(package="dll", library_dependencies=[library()])])))
        self.assertEqual(list(out), MANIFEST_ORDER)
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

    def validate(self, *manifests, vt_max_malicious=None):
        paths = []
        for m in manifests:
            paths.append(os.path.join(self.root, "submissions", m["id"], f'{m["version"]}.json'))
            mi._write_json(paths[-1], m)
        return run_quiet(mi.cmd_validate, repo=self.root, paths=paths,
                         vt_max_malicious=vt_max_malicious)

    def split(self, server_zip):
        return manifest(artifacts=[
            self.serve(artifact(targets=["client_windows"], asset="Repo-pc.dll"), b"MZ pc"),
            self.serve(artifact(targets=["server"], asset="Repo-server.zip"), zip_bytes(server_zip))])

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
        stub(self, mi, "_sniff_package_from_url",
             lambda url: "zip" if url.endswith(".zip") else "dll")

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
        rc, _ = run_quiet(mi.cmd_validate, repo=self.root, paths=None, vt_max_malicious=None)
        self.assertEqual(rc, 0)

    def test_repo_template_is_v2_apart_from_its_placeholder_hash(self):
        with open(os.path.join(os.path.dirname(HERE), "submissions", "TEMPLATE.json"),
                  encoding="utf-8") as f:
            tmpl = json.load(f)
        self.assertEqual(mi.validate_structure(tmpl),
                         ["artifacts[0].sha256 must be 64 lowercase hex characters"])
        self.assertEqual(tmpl["artifacts"][0]["targets"], ["client_windows", "server"])


class Site(unittest.TestCase):
    def test_screenshot_rules(self):
        sha = "0123456789abcdef" * 2 + "01234567"
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
            self.assertIsNone(mi._screenshot_ok(url, "Owner", "Repo"), url)
        for url, needle in bad.items():
            self.assertIn(needle, mi._screenshot_ok(url, "Owner", "Repo"), url)

    def test_site_bakes_one_row_per_mod(self):
        root = temp_dir(self)
        os.makedirs(os.path.join(root, "tools"))
        with open(os.path.join(root, "tools", "page.html"), "w", encoding="utf-8") as f:
            f.write("<script>const MODS = /*__MODS__*/[];</script>")
        shots = [f"https://github.com/Owner/Repo/releases/download/v1/{i}.png" for i in range(5)]
        for v, extra in (("1.0.0", {}), ("1.1.0", {"description": "</script>", "screenshots": shots})):
            m = manifest(version=v, **extra)
            m["artifacts"][0]["package"] = "dll"
            mi._write_json(os.path.join(root, "manifests", "Owner", "Repo", f"{v}.json"), m)
        rc, out = run_quiet(mi.cmd_site, repo=root, out=None)
        self.assertEqual(rc, 0)
        self.assertIn("only the first 4", out)
        with open(os.path.join(root, "site", "index.html"), encoding="utf-8") as f:
            page = f.read()
        data = page[page.index("= ") + 2:page.rindex(";")]
        self.assertNotIn("<", data)          # nothing can close the <script>
        rows = json.loads(data)
        self.assertEqual([(r["id"], r["latest"], r["description"], len(r["screenshots"]))
                          for r in rows], [("Owner.Repo", "1.1.0", "</script>", 4)])


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
            rc = mi.cmd_validate(argparse.Namespace(repo=root, paths=[path], vt_max_malicious=None))
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


if __name__ == "__main__":
    unittest.main()
