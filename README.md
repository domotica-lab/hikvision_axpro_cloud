# Hikvision AX PRO (Cloud) for Home Assistant

[![hacs](https://img.shields.io/badge/HACS-custom-orange.svg)](https://hacs.xyz)

Control a **Hikvision AX PRO** alarm panel from Home Assistant **through the
Hik-Connect cloud** — no local network access to the panel needed.

Made for panels that are reachable **only via the cloud** (e.g. SIM/4G only, or on
a network you can't reach), and for panels **shared with your Hik-Connect
account** (you don't need to be the owner). Existing integrations only work on the
local network.

🇮🇹 [Versione italiana più sotto](#italiano)

## Features

- An **alarm panel** entity for every enabled area: arm away, disarm and
  (optionally) arm stay. Usable in automations.
- Instant feedback after a command (optimistic state, like the app), then
  confirmed by polling.
- Optional **PIN** asked by Home Assistant before disarming (arming never needs it).
- **Diagnostic sensors**: battery, mobile signal, SIM operator, data usage,
  number of faults; **binary sensors**: mains power, tamper, cloud and mobile
  connection (when the panel reports them).
- Several panels on one account: pick the one to add, repeat to add more.
- Automatic session renewal, re-authentication if the password changes,
  downloadable diagnostics (credentials redacted).

## Supported devices

Tested on **DS-PWA96-M-WE** (firmware V1.2.9 build 240621). It should work with
other AX PRO models (DS-PWA32/64/96…) and probably AX Hybrid PRO, since they share
the same ISAPI commands. **Please open an issue** with your model and firmware,
whether it works or not.

## Installation

### HACS (recommended)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/domotica-lab/hikvision_axpro_cloud`,
   category **Integration**.
2. Install **Hikvision AX PRO (Cloud)** and restart Home Assistant.

### Manual
Copy `custom_components/hikvision_axpro_cloud` into your
`config/custom_components/` folder and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → "Hikvision AX PRO (Cloud)"**,
then enter your Hik-Connect email (or username) and password — the same you use in
the app. If the account has several devices you will be asked which one to add.

**Options** (Configure button): update interval (10–300 s, default 30), PIN for
disarming, and Stay arming on/off.

### Requirements and tips
- Your Hik-Connect user must be allowed to arm/disarm the panel in the app.
- Use a **dedicated Hik-Connect account** for Home Assistant (share the panel with
  it from the app): this way logging in from Home Assistant never interferes with
  your phone.
- If login fails with a device/terminal verification error, disable that check
  for the account in the Hik-Connect app.

## How it works

Hik-Connect login → the cloud provides the panel's digest credential for your user
(`/ISAPI/Security/CloudUserManage/users`, field `userNameSessionAuthInfo`) →
digest authentication → ISAPI commands (`/ISAPI/SecurityCP/control/arm|disarm`,
`/ISAPI/SecurityCP/status/host`) sent through the cloud tunnel
`/v3/userdevices/v1/isapi`. It is the same mechanism used by the official app.

## Limitations

- **Unofficial API**, reverse-engineered from the app: Hikvision may change it at
  any time.
- Cloud polling: state updates arrive every *N* seconds, not instantly. Each poll
  uses a little mobile data on SIM-only panels — raise the interval if needed.
- Panel firmware updates may change the behaviour.

## Disclaimer

Community project, **not affiliated with Hikvision**. It controls a security
system: always check the real state in the app or on the panel. Use at your own
risk. Licensed under the [MIT license](LICENSE).

---

## Italiano

Integrazione Home Assistant per comandare una centrale **Hikvision AX PRO**
**tramite il cloud Hik-Connect**, senza bisogno di raggiungerla in rete locale.
Pensata per centrali solo cloud (ad es. solo SIM) e per centrali **condivise** con
il tuo account (non serve esserne proprietario).

**Funzioni:** pannello allarme per ogni area attiva (inserimento totale,
disinserimento e, se abilitato, inserimento parziale), PIN opzionale solo per il
disinserimento, sensori diagnostici (batteria, segnale, operatore SIM, consumo
dati, guasti, alimentazione, manomissione, connessioni), più centrali sullo stesso
account.

**Installazione:** HACS → ⋮ → *Repository personalizzati* →
`https://github.com/domotica-lab/hikvision_axpro_cloud` (categoria *Integration*),
installa e riavvia. Oppure copia `custom_components/hikvision_axpro_cloud` in
`config/custom_components/`.

**Configurazione:** *Impostazioni → Dispositivi e servizi → Aggiungi integrazione →
"Hikvision AX PRO (Cloud)"* con email e password Hik-Connect. Nelle *Opzioni*:
intervallo di aggiornamento, PIN per disinserire, inserimento parziale.

**Consigli:** usa un account Hik-Connect dedicato a Home Assistant, con la centrale
condivisa dall'app. L'utente deve avere il permesso di inserire e disinserire.

API non ufficiale e progetto non affiliato a Hikvision: verifica sempre lo stato
reale nell'app. Licenza MIT.
