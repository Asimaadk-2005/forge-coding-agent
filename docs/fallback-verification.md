# Optional fallback backup

## Version 2 correction

The real user run SpaceFractions_5nlfafyp wrote a versioned score envelope but
load_scores accepted only a plain list. Its score existed on disk but was discarded
when reloaded; model repairs had incorrectly targeted the controller. The shared
contract adapter now unwraps a scores envelope when the generated writer and raw
reader reveal this exact mismatch, preserving legacy plain lists and existing
records. Future repair evidence names Store.load_scores and the observed disk schema.
Missing Session.total_attempts() aliases also map to the existing attempted field.
The generation contract describes these boundaries explicitly.

Version 2 adds Choose path (a browser-only folder chooser) and Build saved project
without an API key. The failed real project was rebuilt through /api/build, passed
source/packaged gameplay and score-persistence checks, and produced SpaceFractions.exe.
Its actual EXE download was hash-checked against the built file. Its usage ledger
was unchanged: zero new model requests. Optional generated editor tests remain
warnings (34 passed, two failed).

136 guarded offline tests passed. HTTP tests include authenticated folder listing.
Browser inspection verified Choose path, folder navigation and Use this folder
setting D:\\ForgeTests; the completed real-game download remained enabled with warnings.
Evidence is under prototype-tests/fallback-v2. The original desktop ZIP is unchanged.

Release: Forge-Web-Backup-v2-Windows-x64.zip. Restart the old backend before opening
the updated package on the default port; running Python processes do not hot-reload.

Task1-EN.docx states: "[Fallback requirement]: If you encounter intractable
engineering obstacles when building the Windows desktop .exe, you may submit a
CLIlaunched webbased version as alternative." It adds that users interact through
the browser after command-line startup and that partial engineering points are
deducted for this fallback. The working desktop Forge package remains primary.

The separate Forge-Web backup provides an HTTP browser UI over the existing
CodeAgent.worker. It does not contain a second model pipeline or prewritten game.
It includes official DeepSeek/OpenRouter key entry, model selection, Markdown input
selection, task, output directory, activity/token/cost display, stop, and EXE/source
downloads. The bundled runtime and original local builder produce a desktop game.

## Verification on October 26, 2026

- 131 root agent tests passed with network and saved-key reads forbidden.
- Local HTTP tests exercised session token, Host/origin checks, generation-worker
  delegation, completion/warnings, cancellation and download filtering.
- Those HTTP generation/download tests explicitly used a mocked worker and
  placeholder artifacts. They were not a real model generation or real game EXE.
- The packaged command launcher --help and packaged backend HTTP/state routes
  passed with Windows-only PATH using the included runtime.
- The actual browser page loaded its controls and polled Ready. Provider switching
  changed the model between the official and OpenRouter IDs correctly. No key was
  entered or model request made during browser review. The IAB viewport was narrow;
  this was control/transport verification rather than full desktop visual approval.
- Provider requests and saved-key reads for fallback verification: zero. No new
  paid game generation was performed for the fallback update.
- The tested desktop ZIP was not changed. This is an optional separate backup.
- A clean Python-free OS/VM is still unavailable; Windows-only PATH is narrower.

Evidence: prototype-tests/fallback/http-verification.json, portable-smoke.json and
release.json. Local access is loopback-only, with per-process browser tokens and
same-origin checks. Keys are held in memory and not written to files/browser storage.
Generated-code execution is still ordinary local execution, not an OS sandbox.
