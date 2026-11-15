# Setup: Bambu Studio and the connection to the X2D

Walk the person through this one step at a time. Menu names come from Bambu Studio 2.9
and Bambu's published manuals; labels can move between releases, so if a label differs,
describe what to look for rather than insisting on the exact word. Sources at the end.

## 1. Install Bambu Studio

- **Where:** only from Bambu Lab's download page (bambulab.com, Download, Bambu Studio)
  or the official GitHub releases page (github.com/bambulab/BambuStudio/releases, also
  the place for Linux). Never from a mirror, a forum attachment or a "free download" site.
- **Needs:** Windows 10 or later, or macOS 10.15 or later; 4 GB RAM (8 GB is better);
  2 GB free disk; OpenGL 2.0.
- **macOS:** drag the app to Applications, open it from there.
- **First-run wizard:**
  1. Region: choose the same region as the Bambu account (Europe, North America, ...).
  2. Customer Experience program: their choice; saying no changes nothing for printing.
  3. Printer selection: tick **Bambu Lab X2D** with the **0.4 mm** nozzle (the one it
     ships with).
  4. Filaments: leave the defaults ticked (the Bambu and Generic PLA presets are there).
  5. **Bambu Network plug-in:** tick install. Without it Bambu Studio can still slice and
     export to a USB stick, but cannot send prints over Wi-Fi or show the printer.
- Check: the top bar shows the tabs **Prepare**, **Preview**, **Device**.

## 2. Choose how the computer talks to the printer

Ask which applies; if unsure, recommend the account route for a home or a shared space
where several people print, and LAN only where cloud accounts are not wanted.

**A shared printer** (a lab's or a makerspace's X2D) is already set up by someone: do not
change its LAN Only mode or its account binding, which would cut off everyone else. Ask
the person who manages the printer how to connect (which account to log in with, or the
IP and access code they hand out), then go to the Device tab check.

| Route | Good for | What it needs | What you lose |
|---|---|---|---|
| **Bambu account (cloud)** | most people; phone app too | a Bambu account, internet | nothing |
| **LAN only** | no cloud, same network | printer IP and 8-character access code | phone app, remote view, print history, firmware offers through the app |
| **USB stick** | no network at all | a USB stick, FAT32 or exFAT | everything live; you start the print on the printer screen |

**Who knows the access code:** it is like a key to the printer. The person types it
into Bambu Studio themselves. You never ask for it, read it or type it.

### Route A: Bambu account

1. Printer on and on Wi-Fi (the touchscreen's network settings). Same region as the
   account.
2. Bind it once: in the Bambu Handy phone app, Devices, Bind printer, then scan the QR
   code shown on the printer screen. (If someone in the space has already bound it to a
   shared account, log in with that account instead.)
3. In Bambu Studio, log in (top right) with the same account.
4. Open the **Device** tab: the X2D appears with its temperatures, camera and AMS.

### Route B: LAN only

Only on a printer that is yours, or with the agreement of whoever manages it: on a shared
printer, do not turn LAN Only on or off, and do not unbind or rebind its account.

1. On the printer screen: Settings, then **LAN Only** (on the X2D it is in the settings
   / network area of the touchscreen). Turn it on. The same page shows the **IP** and
   the **Access Code**.
2. Computer and printer on the **same network**. Guest Wi-Fi or a separate network for
   devices can hide the printer.
3. In Bambu Studio, Device tab (or the printer drop-down in Prepare): add a printer with
   **access code**; type the IP and the code read on the screen.
4. Check: the Device tab shows the X2D.

**macOS, both routes:** if the printer is not found, open System Settings, Privacy &
Security, **Local Network**, and turn it on for Bambu Studio, then reopen Bambu Studio.
Some Bambu Studio releases had known LAN problems on new macOS versions; if LAN only
fails and the account route works, use the account route and check the release notes.

### Route C: USB stick

1. Stick formatted FAT32 or exFAT (the printer can format it: Settings, USB storage).
2. In Bambu Studio, after slicing: the arrow next to Print, **Export plate sliced file**,
   save it on the stick.
3. Stick into the printer's USB port, pick the file on the touchscreen, check the colours
   it shows, start.

## 3. Load the spools and sync the colours

The full click path, with what appears after each click, is in SKILL.md Step 3 (3a
which colour goes where and how to load the external spool, 3b the template). In short:

1. **Plan first:** with a job from 3d-print-design, `design.suggested_nozzles` says
   which colour prints on the right nozzle. In the usual Combo setup that colour goes on
   the **external spool holder** and every other colour in the **AMS**.
2. **Load:** AMS spools in their slots, the end of the filament pushed in until the AMS
   pulls it. External spool: end pushed into the right nozzle's feed tube, then on the
   touchscreen the filament screen, the external slot (Ext), edit, material and colour,
   **Load**. A spool without a Bambu RFID tag, or any spool on the external holder,
   needs its material and colour set by hand on that screen (or in Bambu Studio's
   Device tab by clicking the slot).
3. **Check the connection:** Bambu Studio's **Device** tab shows the X2D and its AMS.
   **Sync only works when it does.**
4. **Sync:** Prepare tab, Filament section, the **Sync** icon next to the word Filament,
   confirm the window. The list now has one numbered row per loaded spool, with its
   colour and material. This list is what the template captures. It does not record
   which AMS slot each row came from: note it while syncing.
5. **No connection?** Add the rows by hand: **+** (Add Filament) once per spool, then
   for each row the colour square (pick the colour) and the drop-down (a system preset
   ending in `@BBL X2D`, such as `Generic PLA @BBL X2D`). Remove extra rows with **-**.

## 4. Opening the project and printing

The person does this, with you explaining:

1. **Open** the `.3mf` from Bambu Studio with **File, Open Project**, never with a
   double click: if another slicer is installed (QIDI Studio, OrcaSlicer, ...), the
   computer may open the file there, and saving it there rewrites it for another printer
   (incident 2026-11-12: Bambu Studio then crashed on Print). The printer at the top left
   must read **Bambu Lab X2D**; otherwise close without saving and rebuild. If Bambu
   Studio asks whether to load the project's settings or presets, answer **yes**. If it
   says the file is "not from Bambu Lab, load geometry only", the file is not ours: stop
   and check.
2. **Check the colours:** the filament list on the left shows the colours; each part in
   the Objects list shows its filament number. Press Sync if the AMS changed. The colour
   of each part on the plate must be the one you planned. To fill the plate (or to add
   the copies the build could not place), select the object, add copies with `+` and
   press **Arrange** (`A`).
3. **Plate type:** the plate shown at the top of the filament area must be the one really
   on the printer (Textured PEI by default on the X2D).
4. **Slice plate** (top right).
5. **Preview** tab: drag the layer slider to the first layers; check the colour panel
   (grams per colour, purge, number of changes, time) against the numbers in the guide.
   A much bigger purge or more changes than the guide says means a colour moved.
6. **Prepare the printer**: open the door and look at the plate. It must be empty (no
   parts or strings left by someone else), clean, and sitting against its stops at the
   back. On a shared printer, ask before removing someone else's print.
7. **Print plate**. In the send dialog: check that every filament points to the right
   AMS slot or to the external spool (left and right nozzle), leave bed levelling and
   flow calibration on Auto, timelapse as they like, then **Send**: the print starts
   right away. To start it from the printer screen instead (for example when the
   computer is in another room), the arrow next to **Print plate** offers **Send**,
   which only uploads the file to the printer's storage; the person starts it on the
   touchscreen, standing at the printer, after checking the colours it shows.
8. **Stay by the printer for the first layer** (the first 5 to 10 minutes). If the first
   layer does not stick or the nozzle drags, stop from the screen or the Device tab.

## Sources

- Bambu Studio repository and releases, licence AGPL-3.0: https://github.com/bambulab/BambuStudio
- Bambu Studio quick start (wiki): https://wiki.bambulab.com/en/software/bambu-studio/studio-quick-start
- Printer binding guide (wiki): https://wiki.bambulab.com/en/knowledge-sharing/printer-account-binding-guide
- LAN only mode (wiki): https://wiki.bambulab.com/en/knowledge-sharing/enable-lan-mode
- Bambu Handy quick start (wiki): https://wiki.bambulab.com/en/studio-handy/handy/bambu-handy-quick-start
- Dual nozzle filament grouping (wiki): https://wiki.bambulab.com/en/software/bambu-studio/manual/dual-nozzles-slicing-filament-grouping
- Forum, how a print gets from the computer to the printer: https://forum.bambulab.com/t/how-does-a-print-get-from-my-pc-to-my-3d-printer/252216
- Forum, macOS local network permission: https://forum.bambulab.com/t/allow-bambustudio-to-find-devices-on-local-networks/167205
- X2D launch post: https://blog.bambulab.com/xcellence-made-simple-bambu-lab-presents-the-x2d/
