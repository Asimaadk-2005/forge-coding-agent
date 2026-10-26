# Known limitations

- A clean Windows machine has not been tested. This host is Windows Home without Sandbox or an available VM. Removing Python from PATH is a narrower check.
- Local generation tests and builds execute generated code as the current Windows user. Protected acceptance and hash receipts are verification measures, not an operating-system security sandbox.
- LLM generation is stochastic. Basic checks cover visible gameplay and saving, not every input or visual state. A confirmed gameplay failure stops verified EXE delivery and preserves source. Play game is enabled after basic checks/packaging. Help/editor and generated-test failures are reported as warnings without paid repair requests.
- Model repairs for confirmed gameplay/build failures are bounded by two rounds and the existing per-run budget. Generated-test warnings do not trigger model requests. The independent checker is excluded from model edits.
- Advanced numeric inputs, exact question wording, exhaustive storage recovery and visual item counts are outside the essential delivery gate. Arbitrary prose arithmetic that cannot be parsed is reported as a warning rather than rejected.
- The $0.95 guard is per run/checkpoint. Unreported interrupted usage retains a conservative reservation. Configured prices are editable and should match the selected provider’s current pricing; the dashboard is authoritative for billing.
- Reviewed graphics are supplied scaffolding. The model generates the game controller, domain, content, persistence and tests. This attribution is explicit in the generated plan and documentation.
- Legacy projects do not gain the new component contract on Resume. Rebuilding one reports gameplay as unverified; use a fresh generation to exercise the new approach.
- The question editor is local and has no authentication. User-created questions require a valid numeric answer but their educational correctness is not independently inferred from arbitrary prose.
- Visual review remains distinct from automated gameplay checks. Successful packaging reports it as pending.
- One-file executables extract their embedded runtime at launch and can start slowly. No code signing is configured.
- Portable runtime assembly currently reuses the provisioned Python 3.12 environment. Fully reproducible upstream runtime provisioning and a clean Windows test remain release follow-ups.
- Cloud export creates files locally and uploads nothing. A Windows runner still has its own usage allowance and is not a clean end-user OS test.
- The student still needs to record the demonstration video.
