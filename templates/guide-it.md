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
- **Stampante condivisa** (per esempio la X2D di un laboratorio): non cambiare la modalità
  LAN Only né l'account a cui è collegata. Chiedi a chi gestisce la stampante come
  collegarti.
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
5. **Più copie? (facoltativo)** Seleziona l'oggetto, aggiungi copie con il tasto `+`,
   poi premi **Disponi** (Arrange, tasto `A`): le copie si sistemano da sole lontano
   dalla torre di spurgo. Le copie si dividono gli stessi cambi colore, quindi lo spreco
   per pezzo scende; tempo e grammi però saranno più alti dei numeri scritti sopra.
6. **Affetta.** Premi **Affetta piatto** (Slice plate) in alto a destra.
7. **Guarda l'anteprima.** Nella scheda **Anteprima** scorri gli strati dal basso e
   controlla i numeri del pannello dei filamenti: tempo, grammi e cambi colore devono
   essere vicini a quelli scritti sopra (più alti se hai aggiunto copie). Molto di più
   vuol dire che un colore è finito sull'ugello sbagliato.
8. **Prepara la stampante.** Apri lo sportello e guarda il piatto: deve essere vuoto
   (nessun pezzo o filo lasciato da altri), pulito e appoggiato contro i suoi fermi in
   fondo. Se c'è ancora la stampa di qualcun altro, chiedi prima di toglierla.
9. **Manda in stampa.** Premi **Stampa piatto**. Nella finestra che si apre controlla
   riga per riga che ogni filamento punti allo slot giusto dell'AMS o alla bobina esterna
   (ugello sinistro e destro). Lascia livellamento del piatto e calibrazione del flusso su
   Auto. Premi **Invia**: la stampa parte subito. Se preferisci avviarla dallo schermo
   della stampante, usa invece la freccia accanto a **Stampa piatto**, poi **Invia**
   (Send): il file arriva nella memoria della stampante senza partire, e lo avvii dallo
   schermo, controllando lì i colori.
10. **Resta davanti alla stampante per il primo strato** (5-10 minuti, vedi sotto). Se il filo non
   attacca o l'ugello trascina, ferma la stampa dallo schermo o dalla scheda Device.
11. **A fine stampa** aspetta che il piatto sia freddo, toglilo, flettilo piano e il pezzo
   si stacca. Togli torre di spurgo e linea di spurgo, rimetti il piatto contro i suoi
   fermi.

## Cosa vedrai

- **Per un po' sembra non succedere niente.** Prima della prima linea la X2D scalda
  piatto e ugelli, pulisce l'ugello, misura il piatto (livellamento) e fa le sue
  calibrazioni. Spesso ci vogliono 5-15 minuti ed è normale. Il tempo scritto sopra li
  comprende.
- **Una linea sottile sul bordo davanti del piatto:** è la linea di spurgo, che prepara
  l'ugello. Le piccole palline di plastica che cadono dietro sono gli spurghi tra un
  colore e l'altro.
- **Un buon primo strato** è piatto e un po' schiacciato: le linee si toccano senza
  buchi, restano attaccate al piatto e gli angoli non si alzano. **Uno cattivo** ha fili
  tondi e staccati, buchi tra le linee, plastica che si arriccia o si accumula
  sull'ugello, linee che vengono trascinate dall'ugello. In quel caso ferma (sotto).
- **Una piccola torre quadrata** accanto al pezzo è la torre di spurgo: con più colori
  c'è apposta.

## Se qualcosa va storto

1. **Ferma** la stampa dallo schermo della stampante (o dalla scheda Device di Bambu
   Studio).
2. **Leggi lo schermo.** Se compare un errore con un codice, scrivilo e cercalo sulla
   wiki di Bambu Lab (wiki.bambulab.com); spesso lo schermo mostra un link o un QR code
   alla pagina giusta.
3. **Lascia raffreddare** finché il piatto è a temperatura ambiente. Non toccare
   l'ugello.
4. **Libera il piatto:** toglilo e stacca tutta la plastica. Mai raschiare vicino alle
   dita.
5. **Lava il piatto** con acqua tiepida e sapone per i piatti, sciacqua, asciuga e non
   toccare più la superficie di stampa con le dita. Rimettilo contro i suoi fermi.
6. **Controlla il tipo di piatto:** quello scelto in Bambu Studio deve essere quello
   montato in macchina.
7. Riprova. Se fallisce due volte allo stesso modo, chiedi aiuto prima del terzo
   tentativo.

## Parole che incontrerai

- **Affettare (slice):** trasformare il modello 3D nelle istruzioni per la stampante (strati e movimenti).
- **Spurgo e torre di spurgo:** plastica spinta fuori per pulire l'ugello quando cambia colore; la torre accanto al pezzo ne raccoglie una parte.
- **AMS:** la scatola che tiene fino a quattro bobine e le porta da sola all'ugello sinistro.
- **Bobina esterna, Bowden:** una bobina sul supporto fuori dall'AMS; arriva all'ugello destro attraverso un tubo lungo (Bowden).
- **Pareti e riempimento:** le pareti sono i gusci pieni esterni del pezzo; il riempimento (infill) è la griglia leggera dentro.

Mai lasciare la stampante a lavorare da sola per ore, e mai di notte con l'edificio vuoto.
