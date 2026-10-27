# Mod repository structure

The contract for a TavernLauncher mod source: the files it serves, and what the two installers (the launcher in Python, TavernLib in C#) write to disk and say to each other. Both implement it byte for byte. A source is plain static JSON, generated however you like; how this repo does it is in [SUBMITTING.md](SUBMITTING.md).

## Files

A source is one base URL, the raw-content root a user pastes into **Add source**, e.g. `https://raw.githubusercontent.com/<user>/<repo>/<branch>`.

| Path under the base | Content |
| --- | --- |
| `repository.json` | The index. Required. The only file read while browsing; holds no install data. |
| `manifests/<author>/<repo>/<version>.json` | One manifest per release. Immutable, kept forever. Fetched (by id and version) only to install. |
| `manifests/<author>/<repo>/latest.json` | Copy of the highest version. |
| `manifests/<author>/<repo>/latest.<major>.json` | Copy of the highest version in that major. |

`<author>` and `<repo>` are the two halves of the mod's id.

## Targets

A target is the build a process runs, not a game scene.

| Target | Runs on |
| --- | --- |
| `client_windows` | The game on Windows as a player: SteamVR, a Quest over Link, or flycam. |
| `server` | A game server, launcher-run or headless (Windows). |
| `client_android` | The standalone Quest headset. Validated, but nothing installs it yet. |

A client always gets its own platform's build, whatever scene the server runs.

## repository.json

```jsonc
{
  "index_version": 2,
  "mods": {
    "ExampleDev.ExampleMod": {           // id
      "1": {                             // major version, as a string; one entry per major
        "name": "Example Mod",
        "author": "ExampleDev",
        "description": "Does something useful.",
        "parity_required": true,
        "targets": ["client_windows", "server"],
        "scenes": ["normal", "quest"],   // only when set
        "versions": ["1.0.0", "1.2.0"]   // every release in this major
      }
    }
  }
}
```

- A reader skips the whole file unless `index_version` is `2`. It is versioned separately from `manifest_version`.
- Every field but `versions` comes from the highest release in that major, in the key order shown. `targets` is the sorted union of that release's artifact targets.
- The default install is `max(versions)`.

## Manifest

The `<version>.json` and `latest*.json` files.

```jsonc
{
  "manifest_version": 2,
  "id": "ExampleDev.ExampleMod",
  "name": "Example Mod",
  "version": "1.2.0",
  "author": "ExampleDev",
  "description": "Does something useful.",
  "parity_required": true,
  "scenes": ["normal", "quest"],
  "dependencies": { "SomeDev.UtilKit": "1.2.0" },
  "artifacts": [
    {
      "targets": ["client_windows", "server"],
      "download_url": "https://github.com/ExampleDev/ExampleMod/releases/download/v1.2.0/ExampleMod.dll",
      "sha256": "<64 lowercase hex>",
      "package": "dll",
      "library_dependencies": [
        {
          "name": "ExampleLib",
          "download_url": "https://github.com/SomeVendor/ExampleLib/releases/download/v2.0.0/ExampleLib.dll",
          "sha256": "<64 lowercase hex>",
          "filename": "ExampleLib.dll"
        }
      ]
    },
    {
      "targets": ["client_android"],
      "download_url": "https://github.com/ExampleDev/ExampleMod/releases/download/v1.2.0/ExampleMod-android.zip",
      "sha256": "<64 lowercase hex>",
      "package": "zip",
      "library_dependencies": []
    }
  ]
}
```

Compiled key order: `manifest_version`, `id`, `name`, `version`, `author`, `description`, `screenshots`, `parity_required`, `scenes`, `dependencies`, `artifacts`. Artifact: `targets`, `download_url`, `sha256`, `package`, `library_dependencies`. Library: `name`, `download_url`, `sha256`, `filename`.

| Field | Rule |
| --- | --- |
| `manifest_version` | Integer `2`. A reader skips a manifest with any other major. |
| `id` | `<github-user>.<github-repo>`. The text before the first dot is the author. No path separators, no `.` or `..` segment. |
| `name` | Defaults to `id`. |
| `version` | `MAJOR.MINOR.PATCH`: three segments of ASCII digits, each at most 2147483647. No suffix. |
| `author` | Defaults to the text before the first dot in `id`. |
| `description` | Free text. |
| `screenshots` | Optional list of image URLs for this repo's page. Installers ignore it. |
| `parity_required` | Required boolean: whether a player needs this mod, at the server's exact version, to join a server running it. It compares versions, not files, so separate client and server artifacts don't affect it. Readers refuse a missing or non-boolean value. See [Joining a server](#joining-a-server). |
| `scenes` | Optional non-empty list of distinct scenes the mod works in, out of `normal`, `quest`, `tutorial`. Absent or `null` means all; listing all three is rejected. |
| `dependencies` | Always present. `{}` or `{"<mod id>": "<minimum version>"}`. |
| `artifacts` | Required, non-empty. One entry per build. |
| `artifacts[].targets` | Non-empty list. A target may appear in only one artifact; a duplicate refuses the manifest. A target no artifact lists is unsupported. |
| `artifacts[].download_url` | `https://` URL of one `.dll` or one `.zip`. |
| `artifacts[].sha256` | 64 hex characters, lowercase when compiled (readers lowercase it). Anything else refuses the manifest. Installers hash the download and refuse a mismatch. Zip members aren't hashed separately. |
| `artifacts[].package` | `"dll"` or `"zip"`, set by the tooling from the file's bytes (`PK` = zip), never by the author. Matched exactly: any other value, or none, and the artifact is ignored. |
| `artifacts[].library_dependencies` | Always present. `[]` or a list of libraries (fields above). |

There is no mod-level `filename`.

**Unknown names.** Readers ignore unknown target names (and an artifact left with no known target) and keep unknown scene names, so later additions don't break old builds. This repo's validator rejects both.

**Dependencies** are other mods, each in its own `Mods/<id>/`, resolved with conflict detection. The candidates are the versions in the minimum's major at or above it; the highest wins. Each install is for one target (`client_windows` from the client launcher, `server` from the server launcher and TavernLib). A dependency with no artifact for that target is left out, along with anything only it needed, and the installer logs it. This repo's validator rejects a dependency that shares no target with the mod, and notes one that covers only some of its targets.

**Libraries** install flat to `UserLibs/<filename>`, pinned by `filename` and `sha256`: no version resolution, no ownership check, any `https://` host. The same `filename` with the same `sha256` installs once, whatever the URLs. The same `filename` with a different `sha256` anywhere in the game folder, for any target, is a conflict, and the install is refused.

**Packaging.** A zip holds the build's own code and asset bundles, with at least one `.dll` at its root. Third-party or shared files go in `library_dependencies`. A native DLL must be a library: MelonLoader only searches `UserLibs/` for native DLLs.

**Screenshots.** This repo's page bakes in the first four at build time, and only those that are:

- `https://` on `github.com` or `raw.githubusercontent.com`, under the mod's own `owner/repo`;
- immutable: a release asset, or a raw URL pinned to a 40-character commit sha;
- `.png`, `.jpg`, `.jpeg`, `.webp` or `.gif`.

Others are skipped, with the reason in the build log.

## Install layout

```
<game>/Mods/<id>/manifest.json          install record (manifest.disabled.json when disabled)
<game>/Mods/<id>/.client_windows/       client_windows build
<game>/Mods/<id>/.server/               server build
<game>/UserLibs/<filename>              library
<game>/UserLibs/<filename>.meta.json    library sidecar: { filename, sha256, download_url }
```

- The client launcher installs only `client_windows`; the server launcher and TavernLib only `server`. Both folders can exist at once, and neither side touches the other's. Nothing else goes directly in `Mods/<id>/`.
- A *bare basename* is a name other than empty, `.` or `..`, with no `/`, `\` or `:`.
- `dll`: saved into the target folder under the `download_url`'s basename if that is a bare basename ending in `.dll`, else as `<id>.dll`.
- `zip`: extracted into the target folder. A member with an absolute path, a colon, a `..` that escapes, or a symlink refuses the whole install. A member that resolves (case-insensitively, after `.` and `..`) to `manifest.json` or `manifest.disabled.json` at the root is skipped.
- A library `filename` must be a bare basename.

**Which build loads.** MelonLoader 0.7 loads a `Mods/<name>/` folder that contains a `manifest.json` (it only checks the file exists), plus every subfolder except those starting with `.` or `~` (and a few reserved names). So it loads neither `.client_windows/` nor `.server/`. TavernLib adds one back: `.server/` in a server process (started with `/start_server`), `.client_windows/` otherwise. It adds that folder and its non-excluded subfolders to MelonLoader's mod folders and assembly search path, only for mods whose record is enabled, ours, and lists that target in `installed`. Without TavernLib, managed mods don't load; a process never loads two builds.

## Install record

`Mods/<id>/manifest.json`. Never written by hand. Both installers write it, and each library sidecar, byte for byte identically for the same state.

```jsonc
{
  "manifest_version": 2,
  "id": "ExampleDev.ExampleMod",
  "name": "Example Mod",
  "version": "1.2.0",
  "author": "ExampleDev",
  "description": "Does something useful.",
  "parity_required": true,
  "scenes": ["normal", "quest"],
  "dependencies": { "SomeDev.UtilKit": "1.2.0" },
  "artifacts": [ ... ],
  "source_repo": "https://raw.githubusercontent.com/.../main",
  "installed": {
    "client_windows": {
      "sha256": "<the installed artifact's sha256>",
      "libraries": ["ExampleLib.dll"],
      "files": { "ExampleMod.dll": "<sha256>" }
    },
    "server": { ... }
  }
}
```

- **Keys** in exactly this order. `scenes` only when set. `artifacts` is the manifest's, verbatim and in order, with compiled key order. `screenshots` is never copied.
- **`installed`** has one entry per installed target, keys sorted. Each holds the artifact's `sha256`; `libraries`, its library `filename`s in manifest order (used to reference-count `UserLibs/`); and `files`, `{path: sha256}` for every file in the target folder, paths relative with `/`, hashes lowercase, keys sorted by ordinal (code-unit) order.
- **Formatting:** two-space indent, `": "` after keys, non-ASCII escaped as lowercase `\uXXXX`, CRLF line endings, no trailing newline.
- **Install** of target T:
  - leaves the mod enabled: the record ends as `manifest.json` and any `manifest.disabled.json` is gone, which re-enables every target;
  - at the record's version, replaces only `.T/` and `installed.T`;
  - at any other version, or when the record has no `installed`, replaces the whole mod: other targets' entries are dropped and their folders removed, best effort (a folder left behind is out of `installed`, so nothing loads it);
  - writes the record last, after the target folder is in place.
- **Ours:** the record is the first of `manifest.json`, `manifest.disabled.json` that is strict UTF-8 (no BOM) holding a JSON object with a non-empty string `id`. The folder is ours only if that record's `parity_required` is a JSON boolean. Anything else is untracked, and never deleted.
- **Damaged:** a target whose `files` don't all match the disk. An installer repairs it the next time it would otherwise call it current.
- **Disable:** rename `manifest.json` to `manifest.disabled.json`. Files stay; MelonLoader skips the folder, so no target loads. One switch for the whole mod. **Enable** renames it back.
- **Uninstall:** delete `Mods/<id>/`. A library is deleted only when no remaining record's `installed` lists it.

## Joining a server

A mod is **running** on a server when its record is enabled, ours, and lists `server` in `installed`.

**What the server says.** Its auth port answers `ping` with `mods_hash` and `mods_count` (running mods only), and `mods_list` with `mods` (running mods) and `untracked` (enabled untracked mods, as `{name, kind}`). A `mods` entry:

```jsonc
{
  "id": "ExampleDev.ExampleMod",
  "version": "1.2.0",
  "parity_required": true,
  "source_repo": "https://raw.githubusercontent.com/.../main",   // a hint, never a pull source
  "targets": ["client_windows", "server"],                        // known targets of the record's usable artifacts, sorted
  "target_sha256": { "client_windows": "<sha>", "server": "<sha>" }, // per target, from the record's artifacts
  "scenes": ["normal"]                                            // only when set
}
```

`mods_hash` is the sha256 of these lines joined with `\n`: `<id>@<version>@req` (or `@opt` when `parity_required` is false) for each running mod, sorted by id; then `untracked:<name>@<mtime>` for each enabled untracked mod, sorted by lowercased name. Nothing else (`targets`, hashes, `scenes`) goes in it.

**What a Windows client does.** It always installs the `client_windows` artifact, whatever the server runs or its scene. Of the server's `mods`, it considers only those whose `targets` include `client_windows`:

- `parity_required: true`: installed at that exact version, or the launch is refused.
- `parity_required: false`: offered, ticked by default; the player can decline.

It leaves out its own pinned mods that don't support the server's scene, and never second-guesses the server's. If its installed `client_windows` sha256 differs from `target_sha256.client_windows`, it notes the mismatch without blocking. It launches the game with a `TavernMods` claim, `{id: version}` for every enabled mod installed for `client_windows`.

**What the server enforces** (TavernLib, at join):

- A join with a claim must hold the exact version of every running mod with `parity_required: true` whose `targets` include `client_windows`.
- A join with no claim, or an unreadable one (the standalone Quest app, TavernEssentials' in-game board, a direct connect), is refused if any running mod has `parity_required: true` and `targets` including `client_windows` or `client_android`, and admitted otherwise.
- Untracked mods are ignored both ways. The claim is self-reported.

**Scenes on a server.** A headless server skips a mod whose `scenes` exclude the scene it launches into, and disables an installed copy. The server launcher asks before installing such a mod and warns at start.

## Untracked mods

Anything MelonLoader would load from `Mods/` that isn't ours:

- a loose `Mods/<name>.dll`;
- a `Mods/<name>/` folder with a `manifest.json` or `manifest.disabled.json` that isn't ours. The file only has to exist, not parse.

A folder with neither file isn't reported. Folders starting with `.` or `~` are always skipped.

| | Managed | Untracked |
| --- | --- | --- |
| Install, update | yes | no |
| Enable, disable | yes | yes |
| Uninstall | yes | no |
| Join handshake | in `mods`, enforced | in `untracked`, advisory, never blocks |
| Exported modlist | in `mods` | in `untracked`, listed, never installed |

- **Toggling** a folder renames `manifest.json` ⇄ `manifest.disabled.json`; the file is never read or rewritten. A loose dll is renamed `X.dll` ⇄ `X.dll.disabled` and always named by `X.dll`; if both names exist, the toggle is refused. Either takes effect at the next game or server start.
- **Nothing automatic ever enables or disables an untracked mod**: not a headless reconcile, a modlist import, or a client's per-server join. Only a person does, from the launcher's Mod Manager or, on a headless server, by renaming by hand (`modmanager list` shows them, tagged). The one exception: a loose `Mods/<name>.dll` with the same filename as a DLL an install just placed is disabled by the same rename, so MelonLoader doesn't load the mod twice.
- **Exported modlist:** enabled untracked mods go under a top-level `untracked` key as `{name, kind}`, never in `mods` (a modlist doubles as a headless server's `/modlist` config, which parses every `mods` entry as `id` or `id@version`). An importer shows the block and installs nothing from it. It never fails an import, and importing never disables the importer's own untracked mods.

## Displaced folders

Installing a mod whose `Mods/<id>/` exists but isn't ours moves that folder to `Mods/.displaced/<id>/` (suffixed `.2`, `.3`, … if taken), logs the move, and installs. This applies to every install, including the launcher restoring a cached version. Nothing loads or lists `.displaced/`; clearing it is up to you.
