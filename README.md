# TavernMods

The default mod index for TavernLauncher: static JSON telling the launcher where each mod's files are (in the mod's own GitHub releases) and how to install them.

- **Players:** nothing to set up. Open **Mod Manager → Community Mods** in the launcher. Other sources can be added under **Manage Sources**, but nobody reviews them, so only add ones you trust.
- **Mod authors:** [docs/SUBMITTING.md](docs/SUBMITTING.md) covers submitting a mod and updating it. The [manifest builder](https://moddingtavern.github.io/TavernMods/builder.html) writes the file for you.
- **Hosting your own source:** serve the layout in [docs/REPO_STRUCTURE.md](docs/REPO_STRUCTURE.md) from any static host. Players add its base URL under **Manage Sources**; a headless server with `modmanager addrepo <url>`.

## Trust

- This repo: automated checks, a VirusTotal scan and a maintainer's review before anything merges. Trusted by default.
- A source you add: unreviewed, shown as unverified.
- Every install, from any source, is hash-checked against its manifest and lands only in `Mods/` or `UserLibs/`.

## License

The tooling and docs are [MIT-licensed](LICENSE). Mods listed here belong to their authors under their own licenses.
