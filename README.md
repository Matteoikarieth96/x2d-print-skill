# x2d-print

A Claude Code skill that takes your STL parts to a **ready-to-print Bambu Studio project
(.3mf) for the Bambu Lab X2D**: every part on the right colour and nozzle, settings from
your own Bambu Studio, checked by slicing it locally. Then it walks you, even if you have
never printed before, through opening the file, checking the colours, slicing and sending
the print.

It also applies multicolour best practices so you do not throw away more plastic than you
print: dominant colour on its own nozzle, accent colours in few layers, one plate per
group of objects that would keep swapping colours.

> Independent project, not affiliated with or endorsed by Bambu Lab. "Bambu Lab",
> "Bambu Studio" and "X2D" are names of their owner, used here only to say what this
> works with.

## What you get

- `out/<name>.3mf`: open it from Bambu Studio (File, Open project) and it comes with
  printer, plate, colours, nozzles and process already set. Do not double-click it if
  another slicer is installed: see [When things go wrong](#when-things-go-wrong).
- A short guide in your language with the filament table, the expected time and grams,
  and the steps: sync AMS colours, check, slice, send, stay for the first layer.
- A check report: estimated time, colour changes per layer, grams of model and purge per
  colour, and plain advice when the colour plan wastes filament.

## The intake questions

Before building anything, Claude asks what is still missing: which STL files and which
colour each one is, how much you have printed before, whether Bambu Studio is installed
and linked to the printer, and what is loaded in the AMS.

## Requirements

- [Claude Code](https://claude.com/claude-code)
- Python 3.9 or later (standard library only)
- Bambu Studio 2.9 or later, from Bambu Lab's site or
  [its GitHub releases](https://github.com/bambulab/BambuStudio/releases), opened at
  least once
- A Bambu Lab X2D. Templates and projects for any other printer are refused.

## Install

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/Matteoikarieth96/x2d-print-skill.git
ln -s "$PWD/x2d-print-skill" ~/.claude/skills/x2d-print
```

Then ask Claude Code something like "I want to print these STLs on my X2D" or
"preparami il 3mf per la stampante".

## How to use

1. Save a template once: in Bambu Studio select the X2D, your plate, press Sync for the
   AMS colours, add any shape, File, Save Project As `x2d-template.3mf`.
2. Give Claude your STL files (one per colour) and say which colour each one is.
3. Claude writes a `job.json`, builds and checks the project, and gives you the `.3mf`
   and the guide.

Directly, without Claude:

```bash
python3 scripts/bambu_project.py studio              # where Bambu Studio is
python3 scripts/bambu_project.py templates           # recent projects usable as template
python3 scripts/bambu_project.py build job.json --check
python3 scripts/bambu_project.py check out/name.3mf
```

Job format: [templates/job.example.json](templates/job.example.json). Details:
[references/how-it-works.md](references/how-it-works.md).

## Security

- It never talks to the printer: no network calls, no access code, no Bambu login, no
  starting or stopping prints. You press Print in Bambu Studio.
- It never copies Bambu's printer profiles: it reads them from your own Bambu Studio.
- It never trusts G-code inside a `.3mf` you give it: every G-code field is replaced
  with the official value from your install, and a template or job that changes the
  printer's limits, motion settings or temperatures beyond the official presets is
  refused.
- It writes only the `.3mf` inside the job's folder, and replaces an existing file only
  when asked (`--force`).
- The only program it runs is your local Bambu Studio, to slice the project in a
  temporary folder for the check.

Threat model and how to report a problem: [SECURITY.md](SECURITY.md).

## When things go wrong

- **Bambu Studio shows another printer, or crashes when you press Print.** The `.3mf`
  was probably opened with a double click in another slicer (QIDI Studio, OrcaSlicer
  and other Bambu Studio forks open `.3mf` files too) and saved there, which converts it
  to that slicer's printer. Close it without saving, rebuild it
  (`build job.json --force --check`) and open the new file from Bambu Studio with File,
  Open project. `check` and `templates` refuse such a file and say so, and `studio`
  lists the other slicers installed.
- The script's error messages say what to fix; [SKILL.md](SKILL.md) lists the common ones.

## Limitations

- One plate per project. For several plates, make one job and one `.3mf` per plate.
- One STL per colour. A single multicolour STL must be split first, or painted by hand
  in Bambu Studio.
- Tested on the X2D with Bambu Studio 2.9.1 on macOS. The Windows and Linux paths follow
  Bambu Studio's default install folders but were not tried.
- The colour advice comes from rules of thumb (see
  [references/colour-best-practices.md](references/colour-best-practices.md)), not from
  measurements on your printer.
- 3D printing involves hot parts and moving machinery. Use this at your own risk, follow
  Bambu Lab's safety instructions, and stay by the printer for the first layer.

## Tests

```bash
python3 -m unittest discover -s tests
```

They need no Bambu Studio. CI runs them on every push and pull request. The slicing check
was validated by hand with Bambu Studio 2.9.1 against the same project set up in the
Bambu Studio window.

## More skills

- [3d-print-design](https://github.com/Matteoikarieth96/3d-print-design-skill): parametric parts for FDM 3D printing, checked before export
- [breadboard-wiring-guide](https://github.com/Matteoikarieth96/breadboard-wiring-guide-skill): step-by-step breadboard wiring for Arduino UNO, with a diagram and a USB call on every step
- [whiteboard-video](https://github.com/Matteoikarieth96/whiteboard-video-skill): hand-drawn whiteboard explainer videos with voice-over
- [evm-dd](https://github.com/Matteoikarieth96/evm-dd-skill): investor-angle due diligence on crypto and EVM projects, with a scored report and an A4 one-pager
- [hiring-prep](https://github.com/Matteoikarieth96/hiring-prep-skill): an interview prep page from a company, a role and your resume, with an interactive test
- [skill-release](https://github.com/Matteoikarieth96/skill-release-skill): publish a skill as a public GitHub repo without leaking anything, with an automated scan and independent review
- [adversarial-review](https://github.com/Matteoikarieth96/adversarial-review-skill): a panel of independent reviewer agents challenges finished work and returns one verdict
- [token-checkup](https://github.com/Matteoikarieth96/token-checkup-skill): a weekly token checkup for Claude Code: session size, what loads at session start, memory kept true
- [portfolio-report](https://github.com/Matteoikarieth96/portfolio-report-skill): an English portfolio report and A4 one-pager from a Fineco export, with a switch to hide the amounts
- [cartoon-shorts](https://github.com/Matteoikarieth96/cartoon-shorts-skill): animated cartoon shorts (9:16) for YouTube Shorts, TikTok and Reels, interview first, rendered locally
- [beer-can-label](https://github.com/Matteoikarieth96/beer-can-label-skill): a print-ready beer can label with a 3D can preview
- [claude-time-is-relative](https://github.com/Matteoikarieth96/claude-time-is-relative): time estimates for Claude Code tasks, learned from your own past sessions
- [ai-privacy-check](https://github.com/Matteoikarieth96/ai-privacy-check-skill): a first privacy and AI rules check for a concrete use case in Italy and the EU (in Italian)

## Licence

MIT, see [LICENSE](LICENSE). Bambu Studio and its profiles are AGPL-3.0 and are not
included here.
