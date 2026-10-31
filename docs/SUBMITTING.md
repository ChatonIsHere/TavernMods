# Submitting a mod

## Submitting

1. Publish each build as a release asset on your mod's GitHub repo, at a tag: one `.dll`, or a `.zip` when it has several DLLs or asset bundles. One file can serve several targets (`client_windows`, `server`, `client_android`). Link to it as `https://github.com/<owner>/<repo>/releases/download/<tag>/<file>`, and never replace the file afterwards.
2. Write the manifest. The easiest way is the [manifest builder](https://moddingtavern.github.io/TavernMods/builder.html), which checks it as you type. Paste your release link at the top and it fills in the id, version, build links and hashes. Or copy [`submissions/TEMPLATE.json`](../submissions/TEMPLATE.json) and fill it in by hand, following [REPO_STRUCTURE.md](REPO_STRUCTURE.md): one `artifacts` entry per build, and leave out `package`.
3. Fill in each build's and library's `sha256` from the exact file you uploaded: the builder's **Hash a file** button does it, or `python tools/modindex.py fill-hashes submissions/<owner>.<repo>/<version>.json` downloads every file and writes them in.
4. Open a pull request that adds only `submissions/<owner>.<repo>/<version>.json`. Only maintainers can add files here directly, so fork this repo first. The builder's **Add to your fork** button then opens the file in your fork, ready to commit to a new branch and propose as a pull request. The checks post their result as a comment and re-run on every push.
5. A maintainer reviews and merges, and the index rebuilds itself.

`parity_required`: keep `true` if players need your mod, at the server's exact version, to join a server running it, or if unsure. Set `scenes` only if your mod breaks in some scene.

## Updating

Publish a new release with a higher version, then submit it as above at `submissions/<owner>.<repo>/<new version>.json`. In the builder, paste the new release's link at the top: it starts from your published manifest and swaps in the new version, links and hashes. A published version never changes, so to fix a build, bump the version.

## Checks

On top of the rules in [REPO_STRUCTURE.md](REPO_STRUCTURE.md), a submission fails if:

- it comes from a fork and does anything other than add one file, or that file isn't at `submissions/<id>/<version>.json` for its own id and version;
- its version is already published, or is lower than the highest published version in its major. A fix to an older major is fine, but a new major can't start below the newest version;
- its id, or a dependency's id, has been replaced (see below), or its id differs only in case from a published or replaced one;
- its `id`, or a dependency's id, isn't a valid GitHub `owner.repo`, or it depends on itself;
- an artifact's `download_url` isn't a tagged release asset of the id's own repo, as in step 1 (libraries may live on any `https://` host);
- a `sha256` isn't lowercase or doesn't match the downloaded file, or an artifact is neither a DLL nor a zip;
- a target or scene name is unknown, or `scenes` lists all three;
- a dependency in this repo shares no target with your mod, judged on the version an install would pick. Partial overlap, or a dependency from another source, gets a note instead;
- one library `filename` has two `sha256`s across your artifacts. The same filename at another `sha256` in another listed mod gets a note: the two can't be installed together;
- a zip isn't valid or can't be read back (encrypted, or an unusual compression), has no `.dll` at its root, has an unsafe member (absolute path, colon, escaping `..`, symlink, a name ending in a dot or space), or exceeds 2000 entries, 500 MB extracted, or a 200:1 compression ratio on any entry over 1 MB;
- VirusTotal can't scan a file, or counts it malicious more times than the `VT_MAX_MALICIOUS` repository variable allows (default 0). Every `dll` artifact and library and each code-bearing zip member is scanned.

The hashes are checked again when the submission is published, so a file changed after review stops the publish.

**Screenshots.** The page shows the first four `screenshots` that are `https://` on `github.com` or `raw.githubusercontent.com` under your own `owner/repo`, immutable (a tagged release asset, or a raw URL pinned to a 40-character commit sha), and `.png`, `.jpg`, `.jpeg`, `.webp` or `.gif`. Others are skipped.

## Replacing a mod

Maintainers only; to ask for one, open an issue. To retire a mod in favour of another, add it to [`replacements.json`](../replacements.json) in the same PR as the replacement's submission, or after it is published:

```json
{
  "OldDev.ExampleMod": {
    "by": "ExampleDev.ExampleMod",
    "note": "Moved to ExampleDev."
  }
}
```

The old mod's manifests stay, so servers still running it can be joined, but it leaves the listing and takes no new releases. Launchers offer players the switch; see [REPO_STRUCTURE.md](REPO_STRUCTURE.md#replaced-mods). The checks fail if the old mod isn't published here, or `by` isn't published or submitted here, is the old id itself, is replaced too, or lacks a Windows or server build the old mod has. A fork PR can't change the file.

## Tooling

[`tools/modindex.py`](../tools/modindex.py) needs only Python 3.8 or later.

| Command | Does | Runs in |
| --- | --- | --- |
| `fill-hashes [paths]` | Downloads every artifact and library and writes their `sha256`. | by hand |
| `validate [paths] [--vt-max-malicious N] [--require-vt]` | The checks above, and `replacements.json`. Exits non-zero on failure. | `validate.yml`, on each PR that adds a submission or changes `replacements.json` |
| `build [--ingest] [--prune]` | Compiles `manifests/` and `replacements.json` into the pointers and `repository.json`. `--ingest` first moves submissions into `manifests/`, re-checking their hashes and setting `package`; `--prune` deletes the moved files. | `publish.yml`, on merge to `main` |
| `site [--out DIR] [--owner NAME]` | Bakes `tools/page.html` and the mod list into `site/index.html`, the owner's mods first. | `pages.yml`, after each build, which also publishes `tools/builder.html` |

`paths` defaults to `submissions/`.
