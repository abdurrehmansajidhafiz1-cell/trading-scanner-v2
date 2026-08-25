# Trading Scanner System — Deployment Guide

Yeh guide tumhe step-by-step le kar chalegi taake tum poora system GitHub Actions
pe deploy kar sako, bina kisi confusion ke.

## Step 1: GitHub Repository Banao

1. GitHub.com pe login karo, naya **private repository** banao (jaise `trading-scanner`)
2. Is poori project ki saari files (jo tumhe di gayi hain) us repo mein upload karo —
   folder structure exactly aisi honi chahiye:
   ```
   trading-scanner/
   ├── .github/workflows/scan.yml
   ├── config.py
   ├── database.py
   ├── timezone_utils.py
   ├── logging_setup.py
   ├── exchange_manager.py
   ├── indicators.py
   ├── pivot_detection.py
   ├── signal_engine.py
   ├── coin_universe.py
   ├── data_fetcher.py
   ├── scanner.py
   ├── screener.py
   ├── reporting.py
   ├── email_sender.py
   ├── main.py
   ├── requirements.txt
   └── test_offline.py
   ```

## Step 2: Gmail Se Email Bhejne Ke Liye "App Password" Banao

Gmail ka normal password directly kaam nahi karega (Google security ki wajah se).
Tumhe ek **App Password** banana hoga:

1. Google Account settings mein jao → **Security**
2. "2-Step Verification" **ON** karo (agar pehle se nahi hai) — App Password ke liye zaroori hai
3. Security page pe "App passwords" dhoondo (search bar mein "App passwords" likh sakte ho)
4. Naya app password generate karo, naam do jaise "Trading Scanner"
5. Jo 16-character password milega, usay **copy kar ke rakh lo** — yeh sirf ek baar dikhega

Agar Gmail use nahi karna chahte, koi bhi SMTP-supporting email service chalega
(Outlook, Yahoo, ya apna custom domain email) — bas SMTP host/port badalna hoga.

## Step 3: GitHub Secrets Set Karo

Yeh sensitive values hain (password, email) jo code mein directly nahi likhni
chahiye — GitHub ka "Secrets" feature use karo:

1. Apne repo mein jao → **Settings** → **Secrets and variables** → **Actions**
2. **New repository secret** pe click karke yeh sab add karo:

| Secret Name | Value | Example |
|---|---|---|
| `SMTP_USER` | Tumhara email address | `yourname@gmail.com` |
| `SMTP_PASSWORD` | Step 2 wala App Password | `abcd efgh ijkl mnop` |
| `REPORT_EMAIL_TO` | Jahan report bhejni hai (khud ka bhi ho sakta hai) | `yourname@gmail.com` |
| `SMTP_HOST` | Email provider ka SMTP server | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `MIN_RR` | Minimum Risk:Reward filter | `1.2` |
| `SYSTEM_START_DATETIME` | System kab se tracking shuru kare (Pakistan Time) | `2026-08-07 06:00:00` |

**Zaroori note on `SYSTEM_START_DATETIME`**: Agar tum yeh khaali chhod do, system
apni **pehli run ke waqt ko khud** start-date maan lega — matlab jab bhi tum
pehli baar workflow chalao, wahi se tracking shuru ho jayegi. Agar tum specific
date/time chahte ho (jaisa tumne pehle discuss kiya tha), yahan likh do.

## Step 4: GitHub Actions Ko Enable Karo

1. Repo mein **Actions** tab pe jao
2. Agar koi message aaye "workflows aren't enabled", enable kar do
3. `Trading Scanner` naam ka workflow dikhna chahiye left sidebar mein

## Step 5: Repo Ko Push Permission Do (Database Persist Karne Ke Liye)

Workflow database file (`trading_system.db`) ko repo mein commit karti hai taake
agli run pe purani state (locked zones, config) yaad rahe. Iske liye:

1. Repo **Settings** → **Actions** → **General** mein jao
2. "Workflow permissions" section mein **"Read and write permissions"** select karo
3. Save karo

## Step 6: Test Karo — Manually Chalao

Deploy hone ke baad, pehle **manually** chala kar dekho ke sab sahi kaam kar raha hai:

1. Repo mein **Actions** tab → **Trading Scanner** workflow select karo
2. Right side mein **"Run workflow"** button dabao → **"Run workflow"** confirm karo
3. Kuch second baad ek naya run dikhega — usay click kar ke **live logs** dekho
4. Agar sab sahi gaya, "Scan run complete" wala message dikhega
5. Repo mein wapas jao, ek nayi file `trading_system.db` create ho chuki hogi (commit history mein)

## Step 7: Confirm — Manual "Fresh Check" Kaise Karna Hai

Jaisa humne discuss kiya tha, tumhare paas **do tareeqe** hain kabhi bhi "abhi
kya ho raha hai" dekhne ke liye:

**Tareeqa A — GitHub Se (bina apne computer ke)**
Step 6 wala process repeat karo — "Run workflow" button dabao, aur "Actions"
tab ke logs mein dekho console output mein qualifying coins ki list print hogi.

**Tareeqa B — Apne Computer Pe (agar Python installed hai)**
```bash
git clone <tumhara-repo-url>
cd trading-scanner
pip install -r requirements.txt
python screener.py
```
Yeh turant tumhe abhi ke qualifying coins dikha dega, terminal mein.

Dono tareeqe **live, fresh data** use karte hain — koi purana cached result nahi.

## Step 8: Automatic Schedule Confirm Karo

Workflow **har 30 minute** apne aap chalegi (`cron: "*/30 * * * *"`) — koi extra
kaam nahi karna. GitHub Actions free tier mein private repo ke liye **~2000
minutes/month** milte hain.

**Zaroori warning**: Yeh free tier limit se **zyada** ban sakta hai agar 50
coins x 3 timeframes fetch karne mein zyada waqt laga. Agar aisa ho:
- Public repo bana lo (unlimited free minutes milte hain public repos pe), ya
- Coin count kam karo (`config.py` mein `UNIVERSE_SIZE`), ya
- Cron interval barhao (jaise har 30 ki jagah har 60 minute)

**Pehle 2-3 din chala kar dekho Actions tab mein "Usage" check karo**, agar
limit ke qareeb aa rahe ho tab adjust kar lena.

## Step 8.5: Reliable Scheduling — cron-job.org Se Extra Backup Trigger (Recommended)

**Zaroori context**: GitHub ka apna native `schedule:` cron **guarantee nahi
deta** ke exact 30-minute interval pe chalega — GitHub ki apni documentation
mein likha hai ke high-load periods mein significant delay ho sakta hai
(kabhi 1 ghante se zyada bhi). Isliye ek external, zyada reliable trigger
add karna better hai — bilkul jaisa purane crypto bot mein tha.

**Yeh setup karne ka tareeqa:**

1. **GitHub Personal Access Token (PAT) banao**:
   - GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens
   - "Generate new token" → naam do (jaise "Trading Scanner Trigger")
   - Repository access: sirf apna `trading-scanner` repo select karo
   - Permissions: **"Actions"** ko **"Read and write"** do
   - Generate karo, token copy kar ke rakh lo (yeh sirf ek baar dikhega)

2. **cron-job.org pe free account banao** ([cron-job.org](https://cron-job.org))

3. **Naya cronjob banao** in settings ke sath:
   - **URL**: `https://api.github.com/repos/<username>/<repo-name>/actions/workflows/scan.yml/dispatches`
   - **Request method**: `POST`
   - **Headers**:
     ```
     Authorization: Bearer <tumhara-PAT-token>
     Accept: application/vnd.github+json
     ```
   - **Request body** (JSON):
     ```json
     {"ref": "main"}
     ```
   - **Schedule**: Har 30 minute (`*/30 * * * *`)

4. Save karo — ab cron-job.org **directly GitHub API se workflow trigger karega**, GitHub ke apne (kabhi unreliable) internal scheduler pe depend kiye bina.

**Zaroori baat**: `.github/workflows/scan.yml` ka apna `schedule:` trigger
**hata mat dena** — usay wahin rehne do as **backup**. Dono triggers
(GitHub ka apna cron + cron-job.org) completely independent hain, ek dusre
ko disturb nahi karte — sirf redundancy milti hai, jo achi baat hai.

## Step 9: Reports Kab Aayengi

**Pehli baar** jab system chale, sirf ek **"System Started"** confirmation
email aayegi (5 khaali reports ek sath nahi) — is se confirm ho jata hai ke
sab kuch sahi connect ho gaya hai.

Uske baad, koi extra setup nahi chahiye — system khud track karta hai ke
kaunsi report "due" hai:
- **Daily**: har roz subah **6:30 AM PKT**
- **Half-Day**: har roz shaam **6:30 PM PKT** (Daily Report jitni hi complete/detailed)
- **3-din**: har 3 din baad
- **15-din**: har 15 din baad
- **Monthly**: har 30 din baad

Daily aur Half-Day reports ek doosre se **chained** hain — Half-Day Report
pichli Daily Report ke end se lekar 6:30 PM tak ka data cover karti hai,
aur agli Daily Report us Half-Day Report ke end se lekar agli 6:30 AM tak
ka data — is tarah din ka koi hissa miss ya duplicate nahi hota.

Sab timestamps reports mein **Pakistan Time (PKT) aur UTC dono** mein dikhengi.

## Step 10: Timezone (PKT) Ke Baare Mein

`SYSTEM_START_DATETIME` secret ko **Pakistan Time** maana jayega — matlab
agar tum `2026-08-07 06:00:00` likhte ho, system isay **"7 August, subah 6
baje Pakistan Time"** samjhega (khud UTC mein internally convert kar lega
calculations ke liye). Reports mein bhi har timestamp PKT mein dikhega.

## Multi-Exchange Fallback (Automatic)

System pehle **Binance** try karta hai. Agar Binance accessible na ho
(jaisa GitHub Actions ke servers se kabhi geo-block ho sakta hai — HTTP 451
error), system automatically **KuCoin → OKX → Bybit → Gate → MEXC** try
karta hai jab tak koi kaam na kar jaye. Yeh sab automatic hai, kuch configure
nahi karna — sirf `config.py` mein `EXCHANGE_PRIORITY` list se order badal
sakte ho agar chaho.



## Troubleshooting

| Masla | Wajah / Fix |
|---|---|
| Email nahi aa rahi | Secrets sahi se set hain? App Password use kiya (normal password nahi)? |
| Workflow fail ho rahi hai | Actions tab ke logs dekho — exact error line milegi |
| "Rate limited" error Binance se | Bohot zyada requests ja rahi hain — coin count ya frequency kam karo |
| Database commit fail ho raha | Step 5 wali "Read and write permissions" check karo |

---

Agar kahin bhi error aaye deployment ke doraan, exact error message (Actions
tab ke logs se) copy kar ke bhej dena — turant fix kar denge.
