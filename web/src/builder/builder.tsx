import { useEffect, useId, useRef, useState } from "react"
import { CircleAlertIcon, CircleCheckIcon } from "lucide-react"

import { SiteHeader } from "@/components/site-header"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { AddButton, CheckRow, Field, HashButton, Hint, Item, RemoveButton, Section, Status } from "./fields"
import {
  blankArtifact, blankLibrary, blankState, fileName, fillFromRelease, INDEX, type IndexMods, loadManifest,
  manifestText, modId, problems, publishedOf, RAW, REPO_RE, SCENES, type State, splitId, submissionPath,
  TARGETS, USER_RE,
} from "./manifest"

const DOCS = `https://github.com/${INDEX.owner}/${INDEX.repo}/blob/${INDEX.branch}/docs/SUBMITTING.md`
const FORK = `https://github.com/${INDEX.owner}/${INDEX.repo}/fork`

const stored = (key: string) => { try { return localStorage.getItem(key) } catch { return null } }
const store = (key: string, value: string) => { try { localStorage.setItem(key, value) } catch { /* storage blocked */ } }

function savedDraft(): State {
  try {
    const draft = JSON.parse(stored("builder-draft") || "null")
    if (draft && Array.isArray(draft.artifacts)) return { ...blankState(), ...draft }
  } catch { /* no draft */ }
  return blankState()
}

const options = (values: string[]) => [...new Set(values)].sort().map((v) => <option key={v} value={v} />)

export function Builder() {
  const ids = { owners: useId(), repos: useId(), mods: useId() }
  const [state, setState] = useState<State>(savedDraft)
  const [indexMods, setIndexMods] = useState<IndexMods | null>(null)
  const [submitterInput, setSubmitterInput] = useState(() => stored("builder-submitter") || "")
  const [releaseUrl, setReleaseUrl] = useState("")
  const [releaseStatus, setReleaseStatus] = useState("")
  const [loadStatus, setLoadStatus] = useState("")
  const [outStatus, setOutStatus] = useState("")
  const loadFile = useRef<HTMLInputElement>(null)

  // Every change goes through here, on a copy, so the rules read like the form.
  const edit = (fn: (s: State) => void) => setState((prev) => {
    const next = structuredClone(prev)
    fn(next)
    return next
  })

  useEffect(() => { store("builder-draft", JSON.stringify(state)) }, [state])
  useEffect(() => {
    fetch(`${RAW}/repository.json`, { cache: "no-store" })
      .then((r) => r.json())
      .then((index) => setIndexMods(index.mods || {}))
      .catch(() => {})
  }, [])

  const { errors, hashless } = problems(state, indexMods)
  const json = manifestText(state)
  const path = submissionPath(state)
  const submitter = submitterInput.trim() || state.owner
  const canSubmit = !errors.length && !hashless.length && USER_RE.test(submitter)
  const validId = USER_RE.test(state.owner) && REPO_RE.test(state.repo)
  const published = validId ? publishedOf(indexMods, modId(state)) : []
  const indexIds = Object.keys(indexMods || {}).map(splitId)

  // Each target can have only one build, so a target another build has is locked.
  const targetOwner: Record<string, number> = {}
  state.artifacts.forEach((a, i) => a.targets.forEach((t) => { if (!(t in targetOwner)) targetOwner[t] = i }))

  const startFromRelease = async () => {
    const result = await fillFromRelease(releaseUrl.trim(), indexMods, () => setReleaseStatus("Reading the release…"))
    if (result.state) setState(result.state)
    setReleaseStatus(result.status)
  }

  const loadPublished = async () => {
    if (!validId) { setLoadStatus("Fill in the owner and repo first."); return }
    setLoadStatus("Loading…")
    try {
      const r = await fetch(`${RAW}/manifests/${state.owner}/${state.repo}/latest.json`, { cache: "no-store" })
      if (!r.ok) { setLoadStatus(`${modId(state)} isn't published in ${INDEX.owner}/${INDEX.repo} yet.`); return }
      const m = await r.json()
      setState(loadManifest(m))
      setLoadStatus(`Loaded ${m.version}. Set the new version, then update each build's link and hash.`)
    } catch (e) { setLoadStatus("Couldn't load it: " + (e as Error).message) }
  }

  const download = () => {
    const a = document.createElement("a")
    a.href = URL.createObjectURL(new Blob([json], { type: "application/json" }))
    a.download = fileName(state)
    a.click()
    URL.revokeObjectURL(a.href)
    setOutStatus(`Saved ${fileName(state)}. It goes in ${path}.`)
  }
  const copy = async () => {
    try { await navigator.clipboard.writeText(json); setOutStatus("Copied.") }
    catch { setOutStatus("Couldn't copy; select the text below instead.") }
  }
  // Only collaborators can add a file to the index itself, so the file goes to the
  // submitter's fork, whose pull requests target the index by default.
  const openPr = () => {
    const q = new URLSearchParams({ filename: path, value: json })
    window.open(`https://github.com/${submitter}/${INDEX.repo}/new/${INDEX.branch}?${q}`, "_blank", "noopener")
  }

  const issues = [...errors]
  if (hashless.length) issues.push(`No hash yet for ${hashless.join(", ")}: hash the file here, or download and run fill-hashes.`)

  return (
    <>
      <SiteHeader current="builder" />
      <main className="mx-auto max-w-[80rem] px-4 pt-6 pb-12 sm:px-6">
        <div className="mb-6 border-b pb-5">
          <h1 className="text-3xl font-bold text-primary">Manifest Builder</h1>
          <p className="mt-2 max-w-prose">
            Fill this in to make the manifest for a new mod or a new version, then open the pull request or download the
            file. Rules: <a href={DOCS} className="text-primary underline underline-offset-4">SUBMITTING.md</a>. A release
            link is looked up through GitHub's API; nothing else you enter leaves your browser until you submit.
          </p>
        </div>

        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,28rem)]">
          <div className="grid gap-6">
            <Section
              title="Start from a release"
              hint={<>Paste a link to your GitHub release, or to one of its files. The builder fills in the owner, repo,
                version, each build's link and its hash. If the mod is already listed, everything else carries over from
                the published version.</>}
            >
              <div className="flex flex-wrap items-end gap-2">
                <Field
                  label="Release link"
                  className="flex-[1_1_18rem]"
                  value={releaseUrl}
                  onChange={setReleaseUrl}
                  onEnter={startFromRelease}
                  placeholder="https://github.com/you/YourMod/releases/tag/v1.0.0"
                />
                <Button type="button" className="h-9" onClick={startFromRelease}>Fill in</Button>
              </div>
              <Status>{releaseStatus}</Status>
            </Section>

            <Section
              title="Mod"
              hint={<>The id is your GitHub <code className="text-info">owner.repo</code>; every build must be a release asset
                of that repo. Updating? Start from the new release above, or fill in the owner and repo and load what's
                published.</>}
            >
              <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-4">
                <Field label="GitHub owner" value={state.owner} list={ids.owners} placeholder="YourGitHubUser"
                  onChange={(v) => edit((s) => { s.owner = v.trim() })} />
                <Field label="GitHub repo" value={state.repo} list={ids.repos} placeholder="YourRepo"
                  onChange={(v) => edit((s) => { s.repo = v.trim() })} />
                <Field label="Version" value={state.version} placeholder="1.0.0"
                  onChange={(v) => edit((s) => { s.version = v.trim() })} />
                <Field label="Name" value={state.name} placeholder="Your Mod Name"
                  onChange={(v) => edit((s) => { s.name = v })} />
                <Field label="Author" value={state.author} placeholder="defaults to the owner"
                  onChange={(v) => edit((s) => { s.author = v.trim() })} />
              </div>
              {published.length > 0 && (
                <Hint className="text-foreground">
                  {modId(state)} is published: {published.slice(0, 5).join(", ")}{published.length > 5 ? ", …" : ""}. Load
                  the latest to start from it.
                </Hint>
              )}
              <datalist id={ids.owners}>{options(indexIds.map(([o]) => o))}</datalist>
              <datalist id={ids.repos}>
                {options(indexIds.filter(([o]) => !state.owner || o.toLowerCase() === state.owner.toLowerCase()).map(([, r]) => r))}
              </datalist>
              <datalist id={ids.mods}>{options(Object.keys(indexMods || {}))}</datalist>
              <Field label="Description" value={state.description} placeholder="One short line describing what the mod does."
                onChange={(v) => edit((s) => { s.description = v })} />
              <div className="flex flex-wrap gap-2">
                <Button type="button" variant="outline" onClick={loadPublished}>Load published manifest</Button>
                <Button type="button" variant="outline" onClick={() => loadFile.current?.click()}>Load a manifest file…</Button>
                <input
                  ref={loadFile}
                  type="file"
                  accept=".json,application/json"
                  tabIndex={-1}
                  aria-hidden
                  className="sr-only"
                  onChange={async (e) => {
                    const f = e.target.files?.[0]
                    e.target.value = ""
                    if (!f) return
                    try { setState(loadManifest(JSON.parse(await f.text()))); setLoadStatus(`Loaded ${f.name}.`) }
                    catch (err) { setLoadStatus("Couldn't load it: " + (err as Error).message) }
                  }}
                />
              </div>
              <Status>{loadStatus}</Status>
            </Section>

            <Section
              title="Joining a server"
              hint={<>Separate client and server builds from one release are still one version, so they don't change this.
                If unsure, keep the first: <code className="text-info">parity_required: true</code>.</>}
            >
              <RadioGroup
                aria-label="Joining a server"
                value={String(state.parity)}
                onValueChange={(v) => edit((s) => { s.parity = v === "true" })}
                className="gap-3"
              >
                {([
                  ["true", "Players must have this mod, at the server's exact version, to join a server running it"],
                  ["false", "Optional: players can join without it, or with a different version"],
                ] as const).map(([value, label]) => (
                  <div key={value} className="flex items-start gap-2.5">
                    <RadioGroupItem value={value} id={`parity-${value}`} className="mt-1" />
                    <Label htmlFor={`parity-${value}`} className="block text-base leading-snug font-normal">{label}</Label>
                  </div>
                ))}
              </RadioGroup>
            </Section>

            <Section title="Scenes" hint="Leave all unticked if the mod works in every scene. Tick only the ones it works in otherwise.">
              <fieldset className="flex flex-wrap gap-x-6 gap-y-2">
                <legend className="sr-only">Scenes the mod works in</legend>
                {SCENES.map(([scene, label]) => (
                  <CheckRow key={scene} label={label} checked={state.scenes.includes(scene)}
                    onChange={(on) => edit((s) => {
                      s.scenes = SCENES.map(([x]) => x as string).filter((x) => x === scene ? on : s.scenes.includes(x))
                    })} />
                ))}
              </fieldset>
            </Section>

            <Section
              title="Builds"
              hint={<>One entry per file you ship: a <code className="text-info">.dll</code>, or a{" "}
                <code className="text-info">.zip</code> with the mod's DLL at its root. One file can serve several targets,
                but each target can have only one build. Hash a file here, or leave the hash empty and run{" "}
                <code className="text-info">python tools/modindex.py fill-hashes</code> on the downloaded manifest.</>}
            >
              {state.artifacts.map((a, i) => (
                <Item
                  key={i}
                  title={`Build ${i + 1}`}
                  action={state.artifacts.length > 1 && (
                    <RemoveButton what={`build ${i + 1}`} onClick={() => edit((s) => { s.artifacts.splice(i, 1) })} />
                  )}
                >
                  <fieldset className="grid gap-1">
                    <legend className="mb-1 text-sm font-medium">Targets</legend>
                    {TARGETS.map(([t, label]) => {
                      const taken = !a.targets.includes(t) && t in targetOwner
                      return (
                        <CheckRow key={t} label={label} checked={a.targets.includes(t)} disabled={taken}
                          note={taken ? `build ${targetOwner[t] + 1} already covers this` : undefined}
                          onChange={(on) => edit((s) => {
                            const art = s.artifacts[i]
                            art.targets = TARGETS.map(([x]) => x as string).filter((x) => x === t ? on : art.targets.includes(x))
                          })} />
                      )
                    })}
                  </fieldset>
                  <Field label="Release asset link" value={a.download_url}
                    placeholder={`https://github.com/${state.owner || "owner"}/${state.repo || "repo"}/releases/download/v1.0.0/Mod.dll`}
                    onChange={(v) => edit((s) => { s.artifacts[i].download_url = v.trim() })} />
                  <div className="flex flex-wrap items-end gap-2">
                    <Field label="SHA-256" mono className="flex-[1_1_18rem]" value={a.sha256}
                      onChange={(v) => edit((s) => { s.artifacts[i].sha256 = v.trim() })} />
                    <HashButton what={`build ${i + 1}`} onHash={(sha) => edit((s) => { s.artifacts[i].sha256 = sha })} />
                  </div>
                  <Hint>Libraries: third-party or native DLLs installed to UserLibs/</Hint>
                  {a.library_dependencies.map((lib, j) => {
                    const what = `build ${i + 1}, library ${j + 1}`
                    const setLib = (fn: (l: State["artifacts"][number]["library_dependencies"][number]) => void) =>
                      edit((s) => fn(s.artifacts[i].library_dependencies[j]))
                    return (
                      <Item key={j} title={`Library ${j + 1}`} className="bg-card"
                        action={<RemoveButton what={what} onClick={() => edit((s) => { s.artifacts[i].library_dependencies.splice(j, 1) })} />}>
                        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,14rem),1fr))] gap-4">
                          <Field label="Name" value={lib.name} placeholder="ExampleLib" onChange={(v) => setLib((l) => { l.name = v })} />
                          <Field label="File name in UserLibs/" value={lib.filename} placeholder="from the link"
                            onChange={(v) => setLib((l) => { l.filename = v })} />
                        </div>
                        <Field label="Download link (any https://)" value={lib.download_url} placeholder="https://…/ExampleLib.dll"
                          onChange={(v) => setLib((l) => { l.download_url = v })} />
                        <div className="flex flex-wrap items-end gap-2">
                          <Field label="SHA-256" mono className="flex-[1_1_18rem]" value={lib.sha256}
                            onChange={(v) => setLib((l) => { l.sha256 = v.trim() })} />
                          <HashButton what={what} onHash={(sha) => setLib((l) => { l.sha256 = sha })} />
                        </div>
                      </Item>
                    )
                  })}
                  <AddButton onClick={() => edit((s) => { s.artifacts[i].library_dependencies.push(blankLibrary()) })}>
                    Add library<span className="sr-only"> to build {i + 1}</span>
                  </AddButton>
                </Item>
              ))}
              {!TARGETS.every(([t]) => t in targetOwner) && (
                <AddButton onClick={() => edit((s) => { s.artifacts.push(blankArtifact()) })}>Add build</AddButton>
              )}
            </Section>

            <Section title="Dependencies" hint="Other mods this one needs, by id and minimum version. Shared DLLs belong under a build's libraries instead.">
              {state.dependencies.map((d, i) => {
                const versionsId = `${ids.mods}-dep-${i}`
                return (
                  <div key={i} className="flex flex-wrap items-end gap-2">
                    <Field label="Mod id" className="flex-[2_1_14rem]" value={d.id} list={ids.mods} placeholder="SomeDev.UtilKit"
                      onChange={(v) => edit((s) => {
                        // Picking a published mod fills in its latest version, if none is set yet.
                        const dep = s.dependencies[i]
                        dep.id = v.trim()
                        const latest = publishedOf(indexMods, dep.id)[0]
                        if (latest && !dep.version) dep.version = latest
                      })} />
                    <Field label="Minimum version" className="flex-[1_1_9rem]" value={d.version} list={versionsId} placeholder="1.0.0"
                      onChange={(v) => edit((s) => { s.dependencies[i].version = v.trim() })} />
                    <datalist id={versionsId}>{publishedOf(indexMods, d.id).map((v) => <option key={v} value={v} />)}</datalist>
                    <RemoveButton what={`dependency ${i + 1}`} onClick={() => edit((s) => { s.dependencies.splice(i, 1) })} />
                  </div>
                )
              })}
              <AddButton onClick={() => edit((s) => { s.dependencies.push({ id: "", version: "" }) })}>Add dependency</AddButton>
            </Section>

            <Section title="Screenshots" hint="Optional, up to 4, shown on the mod page. A release asset of your repo, or a raw.githubusercontent.com link pinned to a commit; .png, .jpg, .webp or .gif.">
              {state.screenshots.map((shot, i) => (
                <div key={i} className="flex flex-wrap items-end gap-2">
                  <Field label={`Image link ${i + 1}`} className="flex-[1_1_18rem]" value={shot}
                    onChange={(v) => edit((s) => { s.screenshots[i] = v.trim() })} />
                  <RemoveButton what={`screenshot ${i + 1}`} onClick={() => edit((s) => { s.screenshots.splice(i, 1) })} />
                </div>
              ))}
              <AddButton disabled={state.screenshots.length >= 4} onClick={() => edit((s) => { s.screenshots.push("") })}>
                Add screenshot
              </AddButton>
            </Section>
          </div>

          <aside aria-labelledby="out-title" className="lg:sticky lg:top-4">
            <Card className="text-base">
              <CardHeader>
                <CardTitle>
                  <h2 id="out-title" className="text-xl font-bold text-primary">Your manifest</h2>
                </CardTitle>
              </CardHeader>
              <CardContent className="grid gap-4">
                <div>
                  <Hint>Submit it as</Hint>
                  <code className="text-sm break-all text-info">{path}</code>
                </div>
                {issues.length ? (
                  <Alert variant="destructive" role={undefined} className="text-base">
                    <CircleAlertIcon aria-hidden />
                    <AlertTitle aria-live="polite" className="text-base">
                      Not ready: {issues.length} thing{issues.length === 1 ? "" : "s"} to fix
                    </AlertTitle>
                    <ul className="col-start-2 mt-1 grid list-disc gap-1 pl-5 text-sm text-foreground">
                      {issues.map((p) => <li key={p}>{p}</li>)}
                    </ul>
                  </Alert>
                ) : (
                  <Alert role={undefined} className="border-success text-success">
                    <CircleCheckIcon aria-hidden />
                    <AlertTitle aria-live="polite" className="text-base">Ready to submit.</AlertTitle>
                    <AlertDescription className="text-foreground">
                      The automated checks still download every file and compare the hashes.
                    </AlertDescription>
                  </Alert>
                )}
                <Field label="Your GitHub username" value={submitterInput} placeholder="defaults to the owner"
                  onChange={(v) => { setSubmitterInput(v); store("builder-submitter", v.trim()) }} />
                <ol className="grid list-decimal gap-1 pl-5">
                  <li>
                    <a href={FORK} target="_blank" rel="noopener" className="text-primary underline underline-offset-4">Fork the index</a>{" "}
                    on GitHub, once. Only maintainers can add files to it directly.
                  </li>
                  <li>
                    Press <strong>Add to your fork</strong>. In GitHub's commit dialog, pick <em>Create a new branch</em>, then{" "}
                    <strong>Propose changes</strong> and <strong>Create pull request</strong>.
                  </li>
                </ol>
                <div className="flex flex-wrap gap-2">
                  <Button type="button" disabled={!canSubmit} onClick={openPr}>Add to your fork</Button>
                  <Button type="button" variant="outline" onClick={download}>Download</Button>
                  <Button type="button" variant="outline" onClick={copy}>Copy</Button>
                </div>
                {!canSubmit && (
                  <Hint>
                    {issues.length ? "Add to your fork works once the list above is empty." : "Add to your fork needs a valid GitHub username."}
                  </Hint>
                )}
                <Status className="min-h-0">{outStatus}</Status>
                <pre
                  tabIndex={0}
                  aria-label="Manifest JSON"
                  className="max-h-[26rem] overflow-auto rounded-lg border bg-background p-3 text-sm leading-relaxed"
                >
                  {json}
                </pre>
              </CardContent>
            </Card>
          </aside>
        </div>
      </main>
    </>
  )
}
