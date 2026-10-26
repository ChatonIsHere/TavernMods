# Submitting a mod

Every launcher trusts this repo by default, so a mod gets in only after automated checks and a maintainer's review.

## Submitting

1. Publish each build as a release asset on your mod's GitHub repo: one `.dll`, or a `.zip` when it has several DLLs or asset bundles. One file can serve several targets.
2. Fork this repo. Copy [`submissions/TEMPLATE.json`](../submissions/TEMPLATE.json) to `submissions/<owner>.<repo>/<version>.json` and fill it in, following [REPO_STRUCTURE.md](REPO_STRUCTURE.md): one `artifacts` entry per build. Leave out `package`.
3. Once the release is public, fill in the hashes:
   ```
   python tools/modindex.py fill-hashes submissions/<owner>.<repo>/<version>.json
   ```
4. Open a pull request that adds only that file. The checks post their result as a comment and re-run on every push. If you change a build, run `fill-hashes` again.
5. A maintainer reviews and merges. Your manifest then moves to `manifests/<owner>/<repo>/<version>.json`, and the `latest*.json` pointers and `repository.json` are rebuilt.

Set `parity_required` to `false` only if clients and servers can run different versions of your mod; if unsure, keep `true`. Set `scenes` only if your mod breaks in some scene.

## Updating

Publish a new release with a higher version, then submit it exactly as above: a new file at `submissions/<owner>.<repo>/<new version>.json`. The launcher offers the update to anyone who has the mod.

A published version never changes. To fix a build, bump the version; a resubmission of an existing version is rejected.

## Checks

On top of the rules in [REPO_STRUCTURE.md](REPO_STRUCTURE.md), a submission fails if:

- it comes from a fork and does anything other than add one file at `submissions/<owner>.<repo>/<version>.json`;
- its version is already published;
- it is `manifest_version` 1, or has a v1 field (`client_side`, `server_side`, `download_url`, `sha256`, `package`, `library_dependencies`) at the top level;
- its `id`, or a dependency's id, isn't a valid GitHub `owner.repo`, or it depends on itself;
- an artifact's `download_url` isn't a GitHub release asset under the id's `owner/repo` (libraries may live on any `https://` host);
- a `sha256` isn't lowercase, or doesn't match the downloaded file;
- a target or scene name is unknown, or `scenes` lists all three;
- a dependency in this repo shares no target with your mod, judged on the version an install would pick. Partial overlap, or a dependency from another source, gets a note instead;
- a zip isn't valid, has no `.dll` at its root, has an unsafe member (absolute path, colon, escaping `..`, symlink), or exceeds 2000 entries, 500 MB extracted, or a 200:1 compression ratio on any entry over 1 MB;
- VirusTotal's malicious count exceeds `--vt-max-malicious`, when a maintainer sets it. Otherwise scan results are only reported, for the reviewer.

The scan runs when `VIRUSTOTAL_API_KEY` is set. It covers every `dll` artifact and library, and each code-bearing zip member (by extension or magic bytes), scanning each distinct file once. The free key allows 4 requests a minute, so the scan waits for free slots; the `VT_MAX_PER_MINUTE` repository variable raises the cap.

## Tooling

[`tools/modindex.py`](../tools/modindex.py) needs only the Python standard library.

| Command | Does | Runs in |
| --- | --- | --- |
| `fill-hashes [paths]` | Downloads every artifact and library and writes their `sha256`. | by hand |
| `validate [paths] [--vt-max-malicious N]` | The checks above. Exits non-zero on failure. | `validate.yml`, on each submission PR |
| `build [--ingest] [--prune]` | Compiles `manifests/` into the pointers and `repository.json`. `--ingest` first moves submissions into `manifests/`, setting `package`; `--prune` deletes the moved files. | `publish.yml`, on merge to `main` |
| `site [--out DIR]` | Bakes `tools/page.html` and the mod list into `site/index.html`. | `pages.yml`, after each build |

`paths` defaults to `submissions/`.

A rule change must land in the launcher (`TavernLauncher/tavern_shared/mods/`), TavernLib (`Backend/Mods/ModDataModel.cs`), this tool and REPO_STRUCTURE.md together.
