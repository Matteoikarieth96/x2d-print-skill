# Come stampare {{NOME}} sulla Bambu Lab X2D

File da aprire: `{{FILE_3MF}}`

## I colori

| Filamento in Bambu Studio | Colore | Dove sta in macchina | Ugello | Parte |
|---|---|---|---|---|
{{RIGHE_FILAMENTI}}

Il controllo fatto affettando il progetto ha dato: **{{TEMPO}}**, **{{GRAMMI_TOTALI}} g** di
filamento, di cui {{GRAMMI_SPURGO}} g di spurgo, **{{CAMBI}} cambi colore**.
{{NOTE_COLORI}}

## Prima volta? Prima di tutto

- Bambu Studio va scaricato solo dal sito di Bambu Lab o dalla pagina GitHub ufficiale.
- La stampante deve comparire nella scheda **Device** di Bambu Studio. Se non c'è, prima
  va collegata (account Bambu, oppure LAN Only con IP e codice di accesso letti sullo
  schermo della stampante). Il codice di accesso lo scrivi tu, non lo dai a nessuno.
- Ugello e piatto arrivano a 300 °C e 120 °C: mani lontane da testina e piatto mentre
  lavora.

## Passo per passo

1. **Bobine.** Controlla che nell'AMS e sul supporto esterno ci siano i colori della
   tabella, ognuno nel posto giusto.
2. **Apri il progetto da Bambu Studio.** Avvia Bambu Studio, poi **File, Apri progetto**
   e scegli `{{FILE_3MF}}`. Mai doppio clic sul file: se sul computer c'è un altro slicer
   (QIDI Studio, OrcaSlicer e altri), il file può aprirsi lì, e quel programma lo
   riscrive per la sua stampante. Se Bambu Studio chiede se caricare anche le
   impostazioni del progetto, rispondi **sì**. In alto a sinistra la stampante deve
   essere **Bambu Lab X2D**; se ne vedi un'altra, chiudi il progetto **senza salvare** e
   fai ricreare il file.
3. **Controlla i colori.** Nella colonna di sinistra premi l'icona di **sincronizzazione**
   accanto ai filamenti: la lista prende i colori veri dell'AMS. Guarda il pezzo sul
   piatto: ogni parte deve avere il colore della tabella. Se una parte è sbagliata,
   selezionala nella lista degli oggetti e cambia il numero del filamento.
4. **Controlla il piatto.** Il tipo di piatto indicato deve essere quello montato in
   macchina (di serie, Textured PEI).
5. **Affetta.** Premi **Affetta piatto** (Slice plate) in alto a destra.
6. **Guarda l'anteprima.** Nella scheda **Anteprima** scorri gli strati dal basso e
   controlla i numeri del pannello dei filamenti: tempo, grammi e cambi colore devono
   essere vicini a quelli scritti sopra. Molto di più vuol dire che un colore è finito
   sull'ugello sbagliato.
7. **Manda in stampa.** Premi **Stampa piatto**. Nella finestra che si apre controlla
   riga per riga che ogni filamento punti allo slot giusto dell'AMS o alla bobina esterna
   (ugello sinistro e destro). Lascia livellamento del piatto e calibrazione del flusso su
   Auto. Premi **Invia**.
8. **Resta davanti alla stampante per il primo strato** (5-10 minuti). Se il filo non
   attacca o l'ugello trascina, ferma la stampa dallo schermo o dalla scheda Device.
9. **A fine stampa** aspetta che il piatto sia freddo, toglilo, flettilo piano e il pezzo
   si stacca. Togli torre di spurgo e linea di spurgo, rimetti il piatto contro i suoi
   fermi.

Mai lasciare la stampante a lavorare da sola per ore, e mai di notte con l'edificio vuoto.
