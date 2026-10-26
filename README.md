# Forge — Desktop Coding Agent

Forge reads architecture Markdown and UML views, uses DeepSeek to generate a
Space Fractions desktop game, checks basic gameplay, and builds a standalone
Windows executable. It supports official DeepSeek and OpenRouter API keys.

## Run the Windows package

Download **Forge.zip** from this repository's Releases page. This is the runnable
package; GitHub's automatically generated source-code ZIP contains development
source instead.

1. Extract the complete Forge folder and run **Forge.exe**. Keep runtime beside it.
2. Select the provider and enter your own API key. Remember key is optional and
   uses encryption tied to the current Windows account.
3. Attach both Markdown files from the packaged inputs folder and select a writable
   output directory.
4. Generate the game. After basic checks and packaging, **Play game** becomes available.
5. Run **SpaceFractions.exe** directly inside the generated project folder, or use
   Play game. The generated EXE runs offline independently of Forge.

No Python installation is needed to use the complete Windows x64 package or the
generated game. Forge bundles its local build runtime; the game embeds its runtime.
Generation needs internet and API credit. A clean Windows VM was unavailable;
runtime independence was checked on the development PC with Windows-only PATH.

## Demonstration

Demonstration video: add the final unlisted YouTube link here before submission.

## Design and attribution

The supplied web/microservices architecture is adapted into one desktop process.
The model generates domain logic, fraction questions and answers, storage, the
controller, tests and documentation. Forge supplies an attributed graphical
component library: space scenery, operand diagrams, progress graphics and controls.
Local API adapters enforce declared data types and documented member names; they
do not supply a question bank or scoring algorithm. Original Markdown inputs are
preserved under input/.

The game uses basic fractions and whole-number answers with exact Fraction equality.
Basic launch, visible questions, scoring, progression, results, replay and saving
are checked in source and the EXE. Help/editor checks and model-written tests are
advisory; their warnings remain logged and do not cause paid repair loops. Confirmed
gameplay/build failures receive at most two repair rounds within the existing budget.
The default maximum per-run guard is $0.95; displayed estimates are not provider bills.

## Source layout

- main.py: desktop agent, providers, generation/checkpoints and local packaging.
- game_blueprint.py and legacy_blueprint.py: versioned generation contracts.
- foundation/: reusable graphical components.
- acceptance_gate.py and validation_runner.py: gameplay and advisory test reporting.
- repair_engine.py and repair_protocol.py: observed-failure repairs and history.
- keyvault.py: optional Windows account-encrypted key storage.
- tests/: offline agent regressions and recorded response fixtures.
- input/: original architecture Markdown and UML views.
- scripts/: offline tests and portable release assembly.

## Development

Use Python 3.12 on Windows for source development:

```powershell
python -m pip install -r requirements.txt
python scripts/verify_offline_repairs.py
python main.py
python main.py --package-agent
```

Portable assembly additionally needs a complete provisioned Python 3.12 runtime
with Tkinter, PyInstaller and pytest. Use scripts/assemble_release.py with that
runtime and a new output directory. The published Forge.zip already contains it.
The repository excludes binaries, runtime files, generated games and API keys.

## Recorded validation

The final Basic Play update passed 123 guarded offline agent tests with no network
or saved-key access. One fresh official generation completed in 11 requests with
zero model repairs, at approximately US$0.148 configured estimated cost. Its basic
source/frozen gameplay and optional control-based editor checks passed. One generated
editor test remained an advisory warning. Manual EXE play confirmed visible questions,
operand diagrams, correct feedback, scoring and Next. These results do not guarantee
every later model response or constitute clean-OS testing.

See docs/known-limitations.md for execution and environment limitations.

## Optional browser backup

The working Windows desktop package is the primary submission. Task 1 permits a
CLI-launched browser alternative for intractable desktop-build obstacles, with a
partial engineering-point deduction. A separate portable backup is available as
Forge-Web-Backup-Windows-x64.zip. See [fallback instructions](fallback/README.md)
and [offline verification](docs/fallback-verification.md). From development source,
run `python fallback/web_agent.py`; the portable backup includes its own runtime.
Fallback verification made no provider requests; mocked downloads are explicitly
labeled as test fixtures. The expanded guarded agent suite passed 131 tests.
