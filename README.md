# 🏠 Hamburg Apartment Alert Monitor

A **100% free** monitor that pings your phone the moment a new sub-650 € apartment
appears on Kleinanzeigen or SAGA Hamburg.

- ✅ Both regular & WBS-eligible apartments
- ✅ Filters out apartment swaps, senior housing, holiday/short-term lets
- ✅ Push notifications with one-tap link to the listing
- ✅ No duplicate alerts (state stored in `seen.json`)
- ✅ No paid services, no subscriptions, no API keys
- ✅ Runs by itself in the cloud — your phone doesn't have to do anything

---

## How it works

```
┌─────────────────────────────┐    ┌────────────────────┐    ┌──────────────┐
│  GitHub Actions (free)      │    │   ntfy.sh (free)   │    │  Your phone  │
│  runs monitor.py every 10m  │───▶│   push relay       │───▶│  ntfy app    │
│  scrapes Kleinanzeigen+SAGA │    │   (no account)     │    │  buzzes 🔔   │
└─────────────────────────────┘    └────────────────────┘    └──────────────┘
            │
            ▼
        seen.json    (stored in your repo, prevents duplicates)
```

---

## ⚡ Setup — 7 steps, ~10 minutes

### 1. Install the **ntfy** app on your phone
- **Android:** [F-Droid](https://f-droid.org/en/packages/io.heckel.ntfy/) or [Play Store](https://play.google.com/store/apps/details?id=io.heckel.ntfy)
- **iOS:** [App Store](https://apps.apple.com/us/app/ntfy/id1625396347)

No account or signup. Just install.

### 2. Pick a **secret topic name**
A topic on ntfy.sh is essentially a public channel — anyone who knows the name can
read messages. So choose something **long and unguessable**, e.g.:

```
hh-apt-alerts-7g9k2x4j-vbnm
```

Open the ntfy app → "+" → paste your topic → Subscribe.
Send yourself a test from a browser:
```
https://ntfy.sh/hh-apt-alerts-7g9k2x4j-vbnm
```
You should get a push. ✅

### 3. Create a free **GitHub account** (skip if you have one)
[github.com/signup](https://github.com/signup)

### 4. Create a new **public repository**
- Name: anything, e.g. `hh-apt-monitor`
- Visibility: **Public** ← important, free unlimited Actions minutes on public repos
- Initialize with README: no (we'll upload our own files)
- Click **Create repository**

### 5. Upload these files
Either:
- Click "uploading an existing file" on the empty repo page and drag the whole folder, **or**
- Click "Add file → Create new file" and paste each file one by one:
  - `monitor.py`
  - `requirements.txt`
  - `Dockerfile` (only if you'll run locally)
  - `.gitignore`
  - `.github/workflows/monitor.yml`  *(create folders by typing them in the filename — GitHub auto-creates them)*

Then rename `seen.json.example` to `seen.json` (or just create an empty file
called `seen.json` containing only `{}`).

### 6. Add your ntfy topic as a **repository secret**
- In your repo: **Settings → Secrets and variables → Actions → New repository secret**
- Name: `NTFY_TOPIC`
- Value: your secret topic name (e.g. `hh-apt-alerts-7g9k2x4j-vbnm`)
- **Add secret**

### 7. Enable Actions and run it once
- Go to the **Actions** tab — GitHub may ask "I understand my workflows, go ahead and enable them" → click it
- Click **Apartment Monitor** in the left sidebar → **Run workflow** → **Run workflow**
- The first run takes ~30s. It builds your **baseline** — it records all current
  listings but **does not send notifications** for them. From the next run onward,
  only new listings trigger a ping.

🎉 Done. From now on, GitHub will run the monitor every 10 minutes, 24/7, forever, free.

---

## 📲 What a notification looks like

```
🔔 🏠 Kleinanzeigen • 540 €
   Helle 1-Zimmer-Wohnung in Wandsbek, 45 m²
   📍 22041 Hamburg-Wandsbek
   📐 45 m² · 1 Zi.
   [tap to open listing →]
```

Tap the notification and Kleinanzeigen/SAGA opens directly to the listing.

---

## 🛠️ Customisation

All settings are at the top of `monitor.py`:

| Variable          | Default | Meaning                                |
|-------------------|---------|----------------------------------------|
| `MAX_RENT`        | `650`   | EUR ceiling (warm or cold — site decides which they show) |
| `RETENTION_DAYS`  | `30`    | How long to remember seen listings     |

To make filters stricter or looser, edit the `EXCLUDE_PATTERNS` list.

### Run more / less often
Edit `.github/workflows/monitor.yml`:
```yaml
- cron: '*/10 * * * *'   # every 10 minutes — sweet spot
- cron: '*/5 * * * *'    # every 5 min  (uses more minutes)
- cron: '*/15 * * * *'   # every 15 min (chill)
```
GitHub's cron is best-effort and may delay 1-5 min during peak load.

---

## 🆘 Troubleshooting

### "Job runs but I never get notifications"
1. Check the Actions log — does the script say `Total fetched: 0`? Then the scraping is being blocked (see next item).
2. Open ntfy.sh in a browser → `https://ntfy.sh/YOUR-TOPIC` → it should show messages. If empty, the secret name doesn't match the app.
3. Make sure ntfy app battery optimisation is **off** for the app, or Android will silence it.

### "The Actions log says `403 Forbidden`"
This means the GitHub Actions IP got flagged by the site's bot protection.
GitHub Actions runs on Azure IPs that are sometimes blocked.

**Workarounds, in order of effort:**

1. **Wait & retry** — IP blocks rotate. Often clears within a day.
2. **Switch to local run** — see the next section. Your home IP is never blocked.

### Run it locally instead of GitHub Actions

Two free options:

**Option A — Docker on any always-on machine (Mac/PC/NAS):**
```bash
git clone https://github.com/YOUR-USER/hh-apt-monitor.git
cd hh-apt-monitor
docker build -t apt-monitor .
docker run -d --name apt-monitor --restart unless-stopped \
   -e NTFY_TOPIC=your-topic-here \
   -v "$(pwd)/seen.json:/app/seen.json" \
   apt-monitor
```
That's it. Check logs with `docker logs -f apt-monitor`.

**Option B — Old Android phone with Termux:**
```bash
pkg install python git
git clone https://github.com/YOUR-USER/hh-apt-monitor.git
cd hh-apt-monitor
pip install -r requirements.txt
# Then in Termux:Boot or with termux-job-scheduler, run every 10 min:
NTFY_TOPIC=your-topic-here python monitor.py
```

Either way, the script is the same — only the host changes.

---

## 🧩 What this monitor does **not** cover (and what to do about it)

Some sources are best handled by their own built-in alert features. Set these up
once and the emails will arrive automatically — combined with this monitor, you
have full coverage:

1. **SAGA — register at Immomio** (essential!)
   👉 [www.saga.hamburg/immobiliensuche](https://www.saga.hamburg/immobiliensuche)
   Most SAGA apartments are allocated via Immomio. Register your preferred districts, household size, and WBS info there. They'll email you when something matches.

2. **ImmobilienScout24 free Suchauftrag** (search alert)
   👉 [immobilienscout24.de](https://www.immobilienscout24.de) → search Hamburg, max 650 €, set up "Suchauftrag" with your email. Free.

3. **Immowelt / Immonet free Suchabo**
   👉 [immowelt.de](https://www.immowelt.de) → same idea, free.

4. **Kleinanzeigen "Suchauftrag"**
   👉 As a backup, log in and save the same search query — they'll email you. This is redundant with our monitor but useful if the scraper ever breaks.

5. **Hamburg housing co-ops (Genossenschaften)** — every one is a separate
   waiting list. Register at each:
   - [Altoba](https://www.altoba.de)
   - [Bauverein der Elbgemeinden](https://www.bve.de)
   - [Schiffszimmerer-Genossenschaft](https://www.schiffszimmerer.de)
   - [Hansa Baugenossenschaft](https://www.hansa-baugenossenschaft.de)
   - [Lehrer-Bau eG](https://www.lehrer-bau.de)
   - [Bergedorf-Bille](https://www.bergedorf-bille.de)
   - [Gartenstadt Wandsbek](https://www.gartenstadt-wandsbek.de)
   - Most charge a small one-time member share (~50–500 €), but no monthly fee. Many have apartments well under 650 € warm.

6. **fördern & wohnen** — Hamburg's social housing arm:
   👉 [foerdernundwohnen.de](https://www.foerdernundwohnen.de)

7. **Hamburger Wohnen / Vonovia / GWG Hamburg** — register directly on their sites.

Pro tip: when you apply, **mention your WBS upfront** with the §-paragraph
(usually §5 or §6, depending on your income bracket) and validity date.
Landlords love this — it means they can rent the apartment immediately to a
qualifying tenant. Many SAGA / Genossenschaft apartments are §5/§6-bound and
WILL be rejected from non-WBS applicants.

---

## 📝 Notes on the filter

What gets **automatically excluded**:

| Category | Keywords matched (case-insensitive) |
|----------|--------------------------------------|
| Apartment swap | Wohnungstausch, Tauschwohnung, Tauschangebot, „Nur Tausch", „gegen 2-Zimmer", „im Tausch" |
| Senior housing | Seniorenwohnung, Altenwohnung, betreutes Wohnen, Seniorenresidenz, „50+/60+/65+", „ab 60 Jahre", Service-Wohnen |
| Holiday / short-term | Ferienwohnung, Urlaubswohnung, Monteur, Zwischenmiete, „auf Zeit", temporär, „für 1–5 Monate" |

It deliberately does **not** filter on `möbliert` (furnished) alone or `befristet`
(time-limited) alone — many normal long-term rentals carry these flags. If you'd
like to filter them too, just add them to `EXCLUDE_PATTERNS` in `monitor.py`.

---

## ❤️ License & disclaimer

This is a personal-use tool. Be polite to the sources (10-min interval is fine,
don't lower it to 1-minute). The script obeys public listing pages only. If a
site changes its HTML, the relevant scraper might need updating — open the
Actions log to see what broke, then adjust the selectors.

Good luck with the apartment search! 🤞
