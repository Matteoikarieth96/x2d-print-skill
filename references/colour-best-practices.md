# Multicolour best practices (X2D and AMS)

Why it matters: every time the same nozzle changes colour, the printer cuts the filament,
loads the next one and pushes out ("flushes") the old colour before printing again. The
flushed plastic is waste. On a small multicolour part the waste can weigh more than the
part.

## The numbers

- A colour change on the same nozzle wastes roughly **0.35 to 0.5 g** with default flush
  volumes; dark to light costs more than light to dark.
- Bambu's wiki example: a 4-colour cube with **153 changes flushed about 80 g** for
  about 11 g of model.
- On the X2D a **nozzle switch** (left to right) needs no flush, only a short prime. In
  Notebookcheck's test the same multicolour Benchy wasted about 70 g with one nozzle and
  about 20 g with both.
- What this skill measured on a 78 x 24 x 3 mm plaque, black base on the right nozzle and
  four small symbols in the first 4 layers on the left nozzle: 12 changes, about 4.7 g of
  model, about 6.3 g of purge and prime tower, 44 minutes.

## Rules, most important first

1. **Count changes, not colours.** Waste grows with (layers that hold several colours on
   the same nozzle) x (colours per layer). Ask: in how many layers do the colours meet?
2. **Give the dominant colour its own nozzle.** Put the colour that runs through most
   layers (base, body) on one nozzle and the accents on the other: switching nozzle is
   free. On the X2D the AMS feeds the left nozzle, so the dominant colour usually goes on
   the external spool and the right nozzle, unless it is TPU (the right nozzle cannot
   print TPU) or a material the Bowden right side handles poorly.
3. **Keep accent colours in few layers.** Inlays face down on the plate (the first 3 to 5
   layers, and the face against the plate comes out smooth) or on top. A colour that
   runs the full height of a part on the same nozzle as another colour costs a change on
   every layer.
4. **Do not alternate colours on the same nozzle without need.** Two objects with
   different colours on one plate, sharing layers and the same nozzle, alternate on every
   layer. Print them on separate plates (one 3MF each), or put their colours on different
   nozzles.
5. **Group copies.** Several copies of the same multicolour part on one plate share each
   colour change: waste per part drops.
6. **Thicker layers, fewer changes.** 0.24 or 0.28 mm instead of 0.20 cuts the number of
   layers, and so the changes, for parts where detail is not critical.
7. **One material per print.** PLA with PETG (or other mixes) bond poorly and need
   different temperatures. Mixing is for experts (soluble or breakaway supports).
8. **Dark to light is the expensive change.** Going from black to white needs much more
   flush than white to black. Bambu Studio orders the colours inside each layer to save
   flush, but white or yellow details sharing a nozzle with a dark colour still cost the
   most: that pair is the first to split across the two nozzles.
9. **Leave the prime tower on** with several colours: it stabilises the nozzle after a
   change. **Flush into support** is on by default; **flush into infill** is fine only
   for opaque parts where the mixed colour hidden inside does not matter.
10. **Flush multiplier stays at 1.0.** 0.8 to 0.9 can be tested on a scrap print once the
    person knows what colour bleeding looks like; never on a first print.
11. **Zero flush option:** print each colour as a separate part and glue them.

## Flush volumes after opening a project

Bambu Studio recalculates flush volumes when the AMS is synced or a colour is changed, if
"Auto calculate flush volume" is on in Preferences (the default). After opening the 3MF
and pressing Sync, the flush table matches the loaded colours. If the person changed a
colour by hand, the "Flushing volumes" button next to the filament list has a
re-calculate option.

## Beginner traps

- **Wrong AMS slot mapping** in the send dialog: the print comes out in the wrong colours.
  Check every line before Send.
- **Wet filament** (crackling, stringing, rough surface): dry it; PLA left out for weeks
  in a humid room is enough.
- **Cardboard spools** in the AMS shed fibres and can slip: use a spool adapter or reel
  the filament onto a plastic spool.
- **TPU and carbon fibre (CF)**: not in the AMS 2 Pro for soft TPU; TPU never on the X2D
  right nozzle. Check Bambu's AMS FAQ before loading anything but PLA, PETG, ABS, ASA.
- **Parts that do not touch the plate**: each colour part must rest on the plate or on
  another part. A thin colour layer "floating" on top of nothing will fail.

## What the check's advice means

| Advice | Meaning | Usual fix |
|---|---|---|
| swaps on the same nozzle in N of M layers | colours alternate through much of the height | move the dominant colour to the other nozzle, keep accents in few layers, or split plates |
| purge more than the part | normal on small parts | fewer colours or colour layers, or several copies per plate |
| several objects share the plate | objects make each other change colour | one plate (one 3MF) per object group |
| different materials | poor bonding | one material |
| prime tower off | risky colour changes | turn it on |

## Sources

- Reduce waste during filament change (Bambu wiki): https://wiki.bambulab.com/en/software/bambu-studio/reduce-wasting-during-filament-change
- Prime tower (Bambu wiki): https://wiki.bambulab.com/en/software/bambu-studio/parameter/prime-tower
- Filament sequence for different layers (Bambu wiki): https://wiki.bambulab.com/en/software/bambu-studio/parameter/filament-sequence-for-different-layers
- Dual nozzle filament grouping (Bambu wiki): https://wiki.bambulab.com/en/software/bambu-studio/manual/dual-nozzles-slicing-filament-grouping
- View slicing information (Bambu wiki): https://wiki.bambulab.com/en/software/bambu-studio/view-slicing-information
- AMS notes and AMS 2 Pro / HT FAQ (Bambu wiki): https://wiki.bambulab.com/en/knowledge-sharing/notes-ams and https://wiki.bambulab.com/en/ams/manual/ams-2-pro-ams-ht-faq
- Notebookcheck, X2D dual nozzle and waste: https://www.notebookcheck.net/Bambu-Lab-X2D-in-detail-Dual-nozzle-halves-printing-time-and-drastically-reduces-waste.1319597.0.html
- Notebookcheck, X2D Combo review: https://www.notebookcheck.net/Bambu-Lab-X2D-Combo-review-Dual-nozzle-3D-printer-tested.1311491.0.html
- X2D direct drive and auxiliary extrusion (Bambu blog): https://blog.bambulab.com/two-extruders-one-purpose-what-is-x2d-direct-drive-extrusion-and-auxiliary-extrusion/
- UNBC Spark Lab, multicolour printing: https://sparklab.unbc.ca/?p=714
- Flushing volumes guide: https://www.3dprofilefix.com/guides/flushing-volumes-guide.html
- X2D Bambu Studio settings: https://printer-hub.ru/posts/bambu-lab-x2d-bambu-studio-settings
- Forum, flushing volume calibration: https://forum.bambulab.com/t/ams-flushing-volumes-calibration-purge-reduction/37062
- Bambu Studio issues on automatic grouping with two nozzles (why the script uses Manual mode): https://github.com/bambulab/BambuStudio/issues/13020 and https://github.com/bambulab/BambuStudio/issues/12915
