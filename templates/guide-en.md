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
2. **Open the project.** Double click `{{FILE_3MF}}` (or File, Open Project). If Bambu
   Studio asks whether to load the project's settings too, answer **yes**.
3. **Check the colours.** In the left column press the **sync** icon next to the
   filaments: the list takes the real AMS colours. Look at the part on the plate: each
   part must have the colour in the table. If one is wrong, select it in the Objects list
   and change its filament number.
4. **Check the plate.** The plate type shown must be the one on the printer (Textured PEI
   out of the box).
5. **Slice.** Press **Slice plate** at the top right.
6. **Look at the preview.** In the **Preview** tab, move up through the layers and check
   the filament panel: time, grams and colour changes should be close to the numbers
   above. Much more means a colour ended up on the wrong nozzle.
7. **Send it.** Press **Print plate**. In the dialog, check line by line that every
   filament points to the right AMS slot or to the external spool (left and right
   nozzle). Leave bed levelling and flow calibration on Auto. Press **Send**.
8. **Stay at the printer for the first layer** (5 to 10 minutes). If the plastic does not
   stick or the nozzle drags, stop the print from the screen or the Device tab.
9. **When it is done**, wait until the plate is cold, take it out, flex it gently and the
   part comes off. Remove the prime tower and purge line, put the plate back against its
   stops.

Never leave the printer running alone for hours, and never overnight in an empty building.
