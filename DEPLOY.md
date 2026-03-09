# 🚀 Guida: Deploy su GitHub Pages

## Risultato finale
Avrai la dashboard disponibile all'indirizzo:
**`https://TUO-USERNAME.github.io/price-alert/`**
Protetta da password, accessibile solo da te, gratis per sempre.

---

## PASSO 1 — Crea il repository GitHub

1. Vai su → https://github.com/new
2. Imposta:
   - **Repository name**: `price-alert`
   - **Visibility**: ✅ **Private** (importante!)
   - Lascia tutto il resto invariato
3. Clicca **"Create repository"**

---

## PASSO 2 — Carica i file nel repo

Hai due opzioni:

### Opzione A — Da browser (più semplice)
1. Nel repo appena creato, clicca **"uploading an existing file"**
2. Trascina questi file/cartelle:
   ```
   scraper.py
   docs/
     index.html
   .github/
     workflows/
       price-alert.yml
   README.md
   ```
3. Clicca **"Commit changes"**

### Opzione B — Da terminale (se hai Git installato)
```bash
git clone https://github.com/TUO-USERNAME/price-alert.git
# copia i file nella cartella clonata
cd price-alert
git add .
git commit -m "Initial setup"
git push
```

---

## PASSO 3 — Cambia la password nella dashboard

1. Apri il file `docs/index.html`
2. Trova la riga (verso l'inizio del file):
   ```javascript
   const APP_PASSWORD = "cambiami123";
   ```
3. Sostituisci `cambiami123` con una password a tua scelta
4. Salva e fai commit del file modificato

> ⚠️ Fai questo PRIMA di attivare GitHub Pages, altrimenti chiunque potrebbe accedere.

---

## PASSO 4 — Attiva GitHub Pages

1. Nel tuo repo → **Settings** (in alto)
2. Nel menu a sinistra → **Pages**
3. Sotto **"Source"** seleziona:
   - Branch: `main`
   - Folder: `/docs`
4. Clicca **Save**
5. Aspetta 1-2 minuti

Vedrai apparire il link:
`https://TUO-USERNAME.github.io/price-alert/`

---

## PASSO 5 — Configura i Secrets per lo scraper

Nel repo → **Settings → Secrets and variables → Actions → New repository secret**:

| Secret           | Valore                                  |
|------------------|-----------------------------------------|
| `SEARCH_QUERY`   | (lascia vuoto, lo legge dal JSON)       |
| `PRICE_MIN`      | (lascia vuoto, lo legge dal JSON)       |
| `PRICE_MAX`      | (lascia vuoto, lo legge dal JSON)       |
| `EMAIL_FROM`     | tuaemail@gmail.com                      |
| `EMAIL_TO`       | tuaemail@gmail.com                      |
| `EMAIL_PASSWORD` | App Password Gmail (16 caratteri)       |
| `EBAY_APP_ID`    | Il tuo eBay Production App ID           |

---

## PASSO 6 — Collega la dashboard allo scraper

1. Apri la dashboard al tuo indirizzo GitHub Pages
2. Aggiungi le ricerche che vuoi
3. Clicca **"Esporta config JSON"**
4. Carica il file `price-alert-config.json` nella **root del repo**
5. Lo scraper lo leggerà automaticamente!

---

## ✅ Tutto pronto!

- **Dashboard**: `https://TUO-USERNAME.github.io/price-alert/`
- **Scraper**: gira automaticamente ogni 30 minuti via GitHub Actions
- **Notifiche**: arrivano via email quando trova annunci nuovi

---

## 🔒 Sicurezza

- Il repo è **privato** → il codice sorgente non è visibile
- GitHub Pages pubblica solo la cartella `docs/` → solo la UI è accessibile
- La password protegge l'accesso alla dashboard
- Le credenziali email/eBay sono nei Secrets → mai esposte

---

## ❓ FAQ

**Posso usarlo da telefono?**
Sì! L'indirizzo GitHub Pages funziona su qualsiasi dispositivo.

**Come cambio la password?**
Modifica `APP_PASSWORD` in `docs/index.html`, fai commit e aspetta 1-2 min.

**GitHub Pages è davvero gratis?**
Sì, per sempre, anche su repo privati (con account gratuito GitHub).

**Posso salvare l'indirizzo come segnalibro?**
Assolutamente sì, è un URL stabile che non cambia mai.
