# How to print {{NAME}} on the Bambu Lab X2D

File to open: `{{FILE_3MF}}`

## Colours

| Filament in Bambu Studio | Colour | Where it is loaded | Nozzle | Part |
|---|---|---|---|---|
{{FILAMENT_ROWS}}

Slicing the project as a check gave: **{{TIME}}**, **{{TOTAL_GRAMS}} g** of filament, of
which {{PURGE_GRAMS}} g is purge, **{{CHANGES}} colour changes**.
{{COLOUR_NOTES}}

## First time? Read this first

- Download Bambu Studio only from Bambu Lab's site or its official GitHub page.
- The printer must appear in Bambu Studio's **Device** tab. If it does not, connect it
  first (Bambu account, or LAN Only with the IP and access code shown on the printer
  screen). You type the access code yourself; do not give it to anyone.
- The nozzle reaches 300 °C and the bed 120 °C: keep hands away from the toolhead and the
  bed while it runs.

## Step by step

1. **Spools.** Check the AMS and the external holder hold the colours in the table, each
   in the right place.
2. **Open the project from Bambu Studio.** Start Bambu Studio, then **File, Open Project**
   and pick `{{FILE_3MF}}`. Never double-click the file: if another slicer is installed
   (QIDI Studio, OrcaSlicer and others), the computer may open it there, and that program
   rewrites it for its own printer. If Bambu Studio asks whether to load the project's
   settings too, answer **yes**. The printer at the top left must read **Bambu Lab X2D**;
   if it shows another printer, close the project **without saving** and have the file
   built again.
3. **Check the colours.** In the left column press the **sync** icon next to the
   filaments: the list takes the real AMS colours. Look at the part on the plate: each
   part must have the colour in the table. If one is wrong, select it in the Objects list
   and change its filament number.
4. **Check the plate.** The plate type shown must be the one on the printer (Textured PEI
   out of the box).
5. **More copies? (optional)** Select the object, add copies with the `+` key, then press
   **Arrange** (`A` key): the copies spread out on their own, clear of the prime tower.
   Copies share the same colour changes, so the waste per part drops; time and grams will
   be higher than the numbers above.
6. **Slice.** Press **Slice plate** at the top right.
7. **Look at the preview.** In the **Preview** tab, move up through the layers and check
   the filament panel: time, grams and colour changes should be close to the numbers
   above (higher if you added copies). Much more means a colour ended up on the wrong
   nozzle.
8. **Send it.** Press **Print plate**. In the dialog, check line by line that every
   filament points to the right AMS slot or to the external spool (left and right
   nozzle). Leave bed levelling and flow calibration on Auto. Press **Send**: the print
   starts right away. To start it from the printer screen instead, use the arrow next to
   **Print plate**, then **Send**: the file goes to the printer's storage without
   starting, and you start it on the screen, checking the colours there.
9. **Stay at the printer for the first layer** (5 to 10 minutes, see below). If the plastic does not
   stick or the nozzle drags, stop the print from the screen or the Device tab.
10. **When it is done**, wait until the plate is cold, take it out, flex it gently and the
   part comes off. Remove the prime tower and purge line, put the plate back against its
   stops.

## What you will see

- **Nothing seems to happen for a while.** Before the first line the X2D heats the bed
  and the nozzles, cleans the nozzle, measures the bed (levelling) and runs its
  calibrations. This often takes 5 to 15 minutes and is normal. The time above includes
  it.
- **A thin line at the front edge of the plate:** the purge line, which primes the
  nozzle. Small blobs of plastic dropping out at the back are the purges between colours.
- **A good first layer** is flat and slightly squashed: the lines touch each other with
  no gaps, they stick to the plate, and the corners stay down. **A bad one** has round,
  loose strings, gaps between lines, plastic curling up or piling on the nozzle, or lines
  that move with the nozzle. Then stop (below).
- **A small square tower** beside the part is the prime tower: it is there on purpose
  with several colours.

## If it fails

1. **Stop** the print on the printer screen (or in Bambu Studio's Device tab).
2. **Read the screen.** If it shows an error with a code, write the code down and look
   it up on Bambu Lab's wiki (wiki.bambulab.com); the screen often shows a link or QR code
   to the right page.
3. **Let it cool** until the plate is at room temperature. Do not touch the nozzle.
4. **Clear the plate:** take it out and remove all the plastic. Never scrape near your
   fingers.
5. **Wash the plate** with warm water and dish soap, rinse, dry it, and do not touch the
   print surface with your fingers again. Put it back against its stops.
6. **Check the plate type:** the plate chosen in Bambu Studio must be the plate on the
   printer.
7. Try again. If it fails the same way twice, ask for help before a third try.

## Words you will meet

- **Slice:** turn the 3D model into the printer's instructions (layers and moves).
- **Purge and prime tower:** plastic pushed out to clean the nozzle when the colour changes; the tower beside the part takes part of it.
- **AMS:** the box that holds up to four spools and feeds them to the left nozzle on its own.
- **External spool, Bowden:** a spool on the holder outside the AMS; it reaches the right nozzle through a long tube (Bowden).
- **Walls and infill:** walls are the solid outer shells of the part; infill is the light grid inside.

Never leave the printer running alone for hours, and never overnight in an empty building.
