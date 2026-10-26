# Optional command-line / browser fallback

Task 1 permits a CLI-launched web application if the Windows desktop EXE encounters
intractable engineering obstacles, with a partial engineering-point deduction.
The working Forge desktop package remains the primary submission. This is a
separate backup, not a replacement or an extra evaluation requirement.

## Portable Windows backup

1. Extract the complete Forge-Web folder.
2. In Command Prompt, change to that folder and run `Forge-Web.cmd`.
3. Keep the terminal open and visit `http://127.0.0.1:8765/` in a browser.
4. Enter a provider key, select the two Markdown files from inputs, enter the task
   and output directory, and click Generate game.
5. Download the generated game EXE/source ZIP in the browser. The original EXE and
   sources also remain in the output project folder. The game itself is desktop.
6. Press Ctrl+C in the terminal when finished.

The portable backup includes its own runtime; no Python installation is needed.
From source, development Python 3.12 and requirements.txt are needed:

```powershell
python fallback/web_agent.py
```

If port 8765 is occupied, use `python fallback/web_agent.py --port 8766` (or the
portable runtime's python.exe with that script). This backend is loopback-only.
Keys are held in memory, not saved in the browser or project. The same generator,
cost guard, local builder and basic/advisory policy are reused; there is no second
game implementation or bank of prewritten game answers.

Generation requires internet/API credit. Local generated-code execution is not
an operating-system sandbox. Close the terminal after use. Source ZIP downloads
omit build-control logs, caches and executables. Download game EXE for the actual
runnable Windows artifact.
