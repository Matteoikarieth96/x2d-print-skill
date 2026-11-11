# Security

## Threat model

What the skill reads, runs and writes, and what could be hostile:

- **Inputs**: STL files, the job file (`job.json`) and the settings template (a `.3mf`)
  are untrusted. The template should be saved by the person's own Bambu Studio, but it
  could be a project downloaded from the internet, with altered G-code or settings.
- **Instructions hidden in inputs** (names inside an STL or a `.3mf`, text in a project
  file, tool output) are data, not commands.
- **Commands** the skill runs: only the local Bambu Studio executable, as
  `BambuStudio --slice 1 --outputdir <temp folder> <copy of the project>`, with an
  argument list (no shell) and a 600 s timeout.
- **Network**: none. The script makes no network calls and never contacts the printer.
  The person sends the print from Bambu Studio themselves.
- **Outputs**: the `.3mf` named in the job (default next to the job file). The check
  slices in a temporary folder that is deleted afterwards.
- **Bambu Studio's own config** (`BambuStudio.conf`) also holds account data and printer
  access codes. Only two keys are read from it: the recent project list and the backup
  path.

## Mitigations

| Risk | Mitigation | File |
| --- | --- | --- |
| Altered G-code in a downloaded template | Every code key (`*_gcode`, `post_process`, `filename_format`, `gcode_flavor`) is replaced with the value of the official preset installed on this computer; the build stops if it cannot | `scripts/bambu_project.py` (`official_code_values`, `build_project`) |
| A template that points at unofficial presets | Presets are looked up only in Bambu Studio's own `system/BBL` index; unknown names stop the build | `scripts/bambu_project.py` (`_Presets`) |
| Unsafe printer limits, motion or temperatures in a template or job | Checked on the final settings, after the job's overrides: plate area and height, nozzle, z offset, clearances, the printer's maximum speeds and accelerations, and the retraction, z hop and flow limits of each filament must match the official presets; each filament's nozzle temperature must be a plain number in that filament's official range, bed and chamber within 10 C of its official value; otherwise the build stops. Missing printer limits are filled from the preset | `scripts/bambu_project.py` (`safety_problems`) |
| A downloaded project passed to `check` | `check` refuses a project whose G-code fields differ from the official presets, or whose limits fail the same safety check, before Bambu Studio is started; only the entries `build` writes are passed to Bambu Studio (custom per-layer G-code and embedded configs are dropped) | `scripts/bambu_project.py` (`check_project`) |
| Print host address or API key carried by a template | The host address, port, user, password, API key and certificate settings (`print_host`, `printhost_apikey` and similar) are cleared in every project written | `scripts/bambu_project.py` (`build_project`) |
| G-code set through the job file | Code keys in `settings` are refused; other keys must exist in the template with the same type | `scripts/bambu_project.py` (`build_project`) |
| Oversized inputs (zip bombs, huge STL) | 200 MB limit per STL, 64 MB per entry read from a `.3mf` | `scripts/bambu_project.py` |
| XML injection through part or object names | Names are escaped; every XML file is parsed before the `.3mf` is written | `scripts/bambu_project.py` (`build_project`) |
| Overwriting other files | The output must end in `.3mf`, stay inside the job's folder after resolving symlinks, differ from the template (also through a hard link or a different letter case), and replace an existing file only with `--force`; a symlink as output is refused | `scripts/bambu_project.py` (`output_path`) |
| Malformed inputs | Non-finite STL coordinates, objects taller than the printer and malformed job files stop with a plain error | `scripts/bambu_project.py` |
| Leaking printer access codes | Only `recent_projects` and `app.last_backup_path` are read from `BambuStudio.conf`; nothing else is printed | `scripts/bambu_project.py` (`candidate_templates`) |
| Shell injection | Bambu Studio is started with an argument list, never through a shell | `scripts/bambu_project.py` (`_run_studio`) |

Tests for these cases: `tests/test_bambu_project.py`.

## Residual risks

- Process settings that are not printer limits (speeds, infill, walls, supports) come
  from the template as they are. Save the template from your own Bambu Studio with system
  presets, as the guide says; never use a downloaded project as the template.
- `check` slices with the Bambu Studio installed on your computer. A bug in Bambu Studio
  itself is outside this project.
- The `.3mf` is a regular project file: anyone who edits it afterwards can change it.
  Open it in Bambu Studio and look at the preview before you print.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: open the repository's
**Security** tab and choose **Report a vulnerability**. Do not open a public
issue for security problems.
