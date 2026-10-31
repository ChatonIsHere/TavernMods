"""The pipeline's defences: release-asset links, re-checked hashes at publish,
strict ids and paths, replacements, libraries, unreadable zips, VirusTotal in
CI, and vetted downloads. Offline, as test_modindex is."""
import hashlib
import io
import os
import struct
import unittest
import urllib.request

from test_modindex import (
    CLEAN, artifact, library, manifest, mi, run_quiet, stub, temp_dir, temp_file, zip_bytes,
)

REAL_FETCH_VERIFIED_HEAD = mi.fetch_verified_head


def encrypted(zip_data):
    """zip_data with every central-directory entry flagged encrypted."""
    data, at = bytearray(zip_data), 0
    while (at := data.find(b"PK\x01\x02", at)) >= 0:
        flags = struct.unpack_from("<H", data, at + 8)[0]
        struct.pack_into("<H", data, at + 8, flags | 1)
        at += 4
    return bytes(data)


class Rules(unittest.TestCase):
    def test_download_url_must_be_a_tagged_release_asset(self):
        base = "https://github.com/Owner/Repo"
        for url, ok in ((f"{base}/releases/download/v1/Repo.dll", True),
                        (f"{base}/releases/latest/download/Repo.dll", False),
                        (f"{base}/raw/main/Repo.dll", False),
                        (f"{base}/raw/0123456789abcdef0123456789abcdef01234567/Repo.dll", False),
                        ("https://github.com/Other/Repo/releases/download/v1/Repo.dll", False)):
            errs = mi.validate_structure(manifest(artifacts=[artifact(download_url=url)]))
            with self.subTest(url):
                self.assertEqual(not errs, ok, errs)

    def test_patterns_refuse_a_trailing_newline_and_other_digits(self):
        for over in ({"version": "1.0.0\n"}, {"version": "١.0.0"}, {"id": "Owner.Repo\n"},
                     {"id": "Owner.Repo."}):
            with self.subTest(over):
                self.assertTrue(mi.validate_structure(manifest(**over)))
        self.assertTrue(mi.validate_structure(manifest(artifacts=[artifact(sha256="a" * 64 + "\n")])))

    def test_ids_equal_ignoring_case_clash(self):
        self.assertEqual(mi.case_clash("owner.repo", {"Owner.Repo", "Other.Mod"}), "Owner.Repo")
        self.assertIsNone(mi.case_clash("Owner.Repo", {"Owner.Repo"}))

    def test_a_replacement_must_be_able_to_take_over(self):
        old = {"1.0.0": manifest("Old.Mod")}
        both = {"1.0.0": manifest("New.Mod")}
        pc_only = {"1.0.0": manifest("New.Mod", targets=("client_windows", "client_android"))}
        self.assertEqual(mi.validate_replacements({"Old.Mod": {"by": "New.Mod"}},
                                                  {"Old.Mod": old, "New.Mod": both}), [])
        for reps, mods, needle in (
                ({"Old.Mod": {"by": "New.Mod"}}, {"New.Mod": both}, "no such mod"),
                ({"Old.Mod": {"by": "old.mod"}}, {"Old.Mod": old, "old.mod": both}, "replace itself"),
                ({"Old.Mod": {"by": "New.Mod"}}, {"Old.Mod": old, "New.Mod": pc_only}, "no server build")):
            errs = mi.validate_replacements(reps, mods)
            with self.subTest(needle):
                self.assertTrue(any(needle in e for e in errs), errs)

    def test_one_library_name_at_two_hashes(self):
        a = artifact(targets=["client_windows"], library_dependencies=[library()])
        b = artifact(targets=["server"], asset="S.dll", library_dependencies=[library(sha="c" * 64)])
        errs, _ = mi.library_problems(manifest(artifacts=[a, b]), {})
        self.assertEqual(len(errs), 1)
        other = manifest("Other.Mod", artifacts=[artifact("Other", "Mod", library_dependencies=[
            library(sha="d" * 64)])])
        errs, warns = mi.library_problems(manifest(artifacts=[a]), {"Other.Mod": {"1.0.0": other}})
        self.assertEqual((errs, len(warns)), ([], 1))


class Validating(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)
        self.files = {}

        def fake_download(url):
            data = self.files[url]
            return temp_file(self, data), hashlib.sha256(data).hexdigest()
        stub(self, mi, "download_and_hash", fake_download)
        stub(self, mi, "vt_scan", lambda path, sha, key: CLEAN)
        saved = os.environ.pop("VIRUSTOTAL_API_KEY", None)
        os.environ["VIRUSTOTAL_API_KEY"] = "KEY"
        self.addCleanup(lambda: os.environ.__setitem__("VIRUSTOTAL_API_KEY", saved)
                        if saved is not None else os.environ.pop("VIRUSTOTAL_API_KEY", None))

    def serve(self, m, data, i=0):
        a = m["artifacts"][i]
        self.files[a["download_url"]] = data
        a["sha256"] = hashlib.sha256(data).hexdigest()
        return m

    def validate(self, m, at=None, require_vt=False):
        path = os.path.join(self.root, "submissions", *(at or (m["id"], f'{m["version"]}.json')))
        mi._write_json(path, m)
        return run_quiet(mi.cmd_validate, repo=self.root, paths=[path], vt_max_malicious=None,
                         require_vt=require_vt)

    def assertFails(self, needle, *args, **kw):
        rc, out = self.validate(*args, **kw)
        self.assertEqual(rc, 1, out)
        self.assertIn(needle, out)

    def test_the_file_sits_at_its_own_id_and_version(self):
        m = self.serve(manifest(), b"MZ build")
        self.assertFails("must be at submissions/Owner.Repo/1.0.0.json", m,
                         at=("Owner.Repo", "1.0.1.json"))

    def test_an_id_differing_only_in_case_is_refused(self):
        mi._write_json(os.path.join(self.root, "manifests", "Owner", "Repo", "1.0.0.json"),
                       manifest(version="1.0.0"))
        m = self.serve(manifest("owner.repo", version="1.0.0",
                                artifacts=[artifact("owner", "repo")]), b"MZ build")
        self.assertFails("differs from Owner.Repo only in case", m)

    def test_an_artifact_must_be_a_dll_or_a_zip(self):
        self.assertFails("neither a zip nor a DLL", self.serve(manifest(), b"<html>"))

    def test_a_zip_must_read_back(self):
        data = encrypted(zip_bytes([("Repo.dll", b"MZ mod")]))
        self.assertFails("can't be read", self.serve(manifest(artifacts=[artifact(asset="Repo.zip")]), data))

    def test_a_zip_name_windows_would_change_is_refused(self):
        data = zip_bytes([("Repo.dll", b"MZ mod"), ("assets./a.bundle", b"x")])
        self.assertFails("ends in a dot or space",
                         self.serve(manifest(artifacts=[artifact(asset="Repo.zip")]), data))

    def test_an_archive_inside_the_zip_is_noted_not_unpacked(self):
        inner = zip_bytes([("Hidden.dll", b"MZ hidden")])
        data = zip_bytes([("Repo.dll", b"MZ mod"), ("extras/pack.bin", inner), ("more.7z", b"x")])
        rc, out = self.validate(self.serve(manifest(artifacts=[artifact(asset="Repo.zip")]), data))
        self.assertEqual(rc, 0, out)
        self.assertIn("extras/pack.bin is an archive inside the zip", out)
        self.assertIn("more.7z is an archive inside the zip", out)
        self.assertNotIn("Hidden.dll", out)

    def test_ci_fails_a_scan_that_cant_run(self):
        os.environ.pop("VIRUSTOTAL_API_KEY")
        m = self.serve(manifest(), b"MZ build")
        rc, _ = self.validate(m)
        self.assertEqual(rc, 0)
        self.assertFails("VirusTotal skipped", m, require_vt=True)
        os.environ["VIRUSTOTAL_API_KEY"] = "KEY"

        def down(*_a):
            raise OSError("quota")
        stub(self, mi, "vt_scan", down)
        self.assertFails("VirusTotal scan could not complete (quota)", m, require_vt=True)


class Downloads(unittest.TestCase):
    def test_every_redirect_is_vetted(self):
        req = urllib.request.Request("https://github.com/x")
        for url in ("https://10.0.0.1/x", "http://github.com/x"):
            with self.subTest(url), self.assertRaises(mi.ValidationError):
                mi._SafeRedirect().redirect_request(req, None, 302, "Found", {}, url)

    def test_a_download_over_the_cap_is_refused(self):
        class Resp(io.BytesIO):
            def __enter__(self):
                return self
        stub(self, mi, "DOWNLOAD_MAX", 10)
        stub(self, mi, "_urlopen", lambda url, timeout: Resp(b"x" * 64))
        with self.assertRaisesRegex(mi.ValidationError, "is over"):
            mi.download_and_hash("https://github.com/x")


class Publishing(unittest.TestCase):
    def setUp(self):
        self.root = temp_dir(self)
        self.heads = {}
        stub(self, mi, "fetch_verified_head", lambda url, sha, what: self.heads.get(url, b"MZ\x90\x00"))

    def submit(self, m):
        path = os.path.join(self.root, "submissions", m["id"], f'{m["version"]}.json')
        mi._write_json(path, m)
        return path

    def build(self):
        return run_quiet(mi.cmd_build, repo=self.root, ingest=True, prune=True)

    def test_a_file_changed_since_review_stops_the_publish(self):
        m = manifest()
        tmp = temp_file(self, b"MZ swapped")
        stub(self, mi, "fetch_verified_head", REAL_FETCH_VERIFIED_HEAD)
        stub(self, mi, "download_and_hash", lambda url: (tmp, hashlib.sha256(b"MZ swapped").hexdigest()))
        self.submit(m)
        with self.assertRaisesRegex(mi.ValidationError, "changed since review"):
            self.build()

    def test_a_dll_artifact_without_an_mz_header_stops_it(self):
        m = manifest()
        self.heads[m["artifacts"][0]["download_url"]] = b"<html>"
        self.submit(m)
        with self.assertRaisesRegex(mi.ValidationError, "neither a zip nor a DLL"):
            self.build()

    def test_an_identical_resubmission_is_pruned_not_fatal(self):
        m = manifest()
        self.submit(m)
        self.assertEqual(self.build()[0], 0)
        path = self.submit(m)
        rc, out = self.build()
        self.assertEqual(rc, 0)
        self.assertIn("identical to the published", out)
        self.assertFalse(os.path.exists(path))
        self.submit(manifest(description="changed"))
        with self.assertRaisesRegex(mi.ValidationError, "would overwrite"):
            self.build()
