# 🔔 Price Alert – Subito.it & eBay

Ricevi notifiche email automatiche quando vengono listati nuovi annunci nel range di prezzo che hai scelto.

---

## 🚀 Setup in 5 passi

### 1. Crea il repository su GitHub

1. Vai su [github.com/new](https://github.com/new)
2. Nome repo: `price-alert` (privato consigliato)
3. Clicca **Create repository**
4. Carica tutti i file di questo progetto

### 2. Ottieni le credenziali necessarie

#### 📧 Gmail App Password (obbligatoria)
1. Vai su [myaccount.google.com/security](https://myaccount.google.com/security)
2. Attiva la **Verifica in 2 passaggi** (se non attiva)
3. Cerca **"Password per le app"** → crea una nuova → copiala (16 caratteri)

#### 🛍️ eBay App ID (consigliato, gratuito)
1. Vai su [developer.ebay.com](https://developer.ebay.com/signin)
2. Registrati → **My Account → Application Access Keys**
3. Copia il **Production App ID (Client ID)**

### 3. Configura i Secrets su GitHub

1. Nel tuo repo → **Settings → Secrets and variables → Actions**
2. Clicca **New repository secret** per ognuno:

| Nome Secret      | Valore                                          |
|------------------|-------------------------------------------------|
| `SEARCH_QUERY`   | `macbook m1`                                    |
| `PRICE_MIN`      | `250`                                           |
| `PRICE_MAX`      | `350`                                           |
| `EMAIL_FROM`     | `tuaemail@gmail.com`                            |
| `EMAIL_TO`       | `tuaemail@gmail.com` (o un'altra email)         |
| `EMAIL_PASSWORD` | La App Password di Gmail (16 caratteri)         |
| `EBAY_APP_ID`    | Il tuo eBay Production App ID                   |

### 4. Attiva GitHub Actions

1. Vai su **Actions** nel tuo repo
2. Se richiesto, clicca **"I understand my workflows, go ahead and enable them"**
3. Vedrai il workflow **"Price Alert - Subito.it & eBay"**

### 5. Testa subito

1. Vai su **Actions → Price Alert**
2. Clicca **"Run workflow"** → **"Run workflow"**
3. Controlla i log per vedere se funziona

---

## ⚙️ Personalizzazione

### Cambiare la frequenza di controllo
Nel file `.github/workflows/price-alert.yml`, modifica la riga `cron`:

```yaml
# Ogni 30 minuti (default)
- cron: '*/30 * * * *'

# Ogni ora
- cron: '0 * * * *'

# Ogni 15 minuti
- cron: '*/15 * * * *'

# Solo nelle ore diurne (8:00-22:00 ora italiana = 6:00-20:00 UTC)
- cron: '*/30 6-20 * * *'
```

> ⚠️ GitHub Actions gratuito ha un limite di ~2.000 minuti/mese.
> Con ogni 30 minuti usi circa 30-60 min/giorno → ben sotto il limite.

### Cercare prodotti diversi
Cambia il valore del secret `SEARCH_QUERY` e il range `PRICE_MIN`/`PRICE_MAX`.

---

## 📬 Come funziona l'email

Riceverai un'email HTML con:
- Badge colorato (🔵 eBay / 🔴 Subito.it)
- Foto del prodotto
- Titolo e prezzo
- Pulsante diretto all'annuncio

Gli annunci già notificati non vengono mai ripetuti (vengono memorizzati nella cache di GitHub Actions).

---

## 🐛 Troubleshooting

**Non ricevo email?**
- Verifica che l'App Password sia corretta (non la password Gmail normale)
- Controlla i log su GitHub Actions per eventuali errori

**eBay non trova nulla?**
- Verifica che `EBAY_APP_ID` sia il **Production** App ID (non Sandbox)
- Prova a espandere il range di prezzo

**Subito.it non funziona?**
- Subito.it usa scraping, può avere interruzioni occasionali
- Controlla i log per il messaggio di errore specifico
