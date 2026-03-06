# Decidero Local Setup Guide

This guide is for anyone who wants to run Decidero locally for practice, testing, or exploration with the lowest possible setup effort.

## 0. Get The Code

### Actions

Clone the repository, then enter the project folder:

```bash
git clone https://github.com/JohnKruse/decidero_gdss_public.git
cd decidero_gdss_public
```

If you downloaded a ZIP instead, extract it and open a terminal in the extracted folder before continuing.

### Verify

```bash
ls README.md requirements.txt start_local.sh
```

## Quick Start (One-Time Setup)

From the project root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start_local.sh
```

Virtual environment convention: use `venv/` for this repository. Do not create `.venv/`; scripts and operational docs are standardized on `venv`.

Open: `http://localhost:8000`

## Windows (PowerShell)

`start_local.sh` is a Bash script, so on Windows use one of these:

- Use Git Bash/WSL and run the same commands as above, or
- Use PowerShell with the commands below.

One-time setup in PowerShell:

```powershell
py -3 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:DECIDERO_SECURE_COOKIES="false"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Daily use in PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
$env:DECIDERO_SECURE_COOKIES="false"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Daily Use (After First Setup)

From the project root:

```bash
source venv/bin/activate
./start_local.sh
```

## What `start_local.sh` Does

- Activates `venv` if it exists.
- Forces local HTTP-safe cookie mode (`DECIDERO_SECURE_COOKIES=false`).
- Starts the app at `http://127.0.0.1:8000`.

## Stop The App

Press `Ctrl+C` in the terminal running the server.

## Configuring AI Features (AI Meeting Designer)

After logging in as Admin, you can configure the AI Meeting Designer **without editing any files**:

1. Click **⚙ SETTINGS** on the right side of the Quick Actions bar on the Dashboard.
2. Go to the **AI Config** tab.
3. Select your provider, paste your API key, enter the model name.
4. Click **Test Connection**, then **Save AI Settings**.

The API key is stored **encrypted in the database** — more secure than putting it in `config.yaml`.

Do **not** store API keys in `config.yaml`. Keep keys in the Settings UI only.
`config.yaml` should only contain non-secret AI defaults (provider endpoints, HTTP timeouts, prompt template source).

For the full settings reference, see `docs/SETTINGS_GUIDE.md`.

## Common Issues

### `uvicorn: command not found`

Run:

```bash
source venv/bin/activate
pip install -r requirements.txt
```

### Port `8000` already in use

Stop the other process using port `8000`, then run `./start_local.sh` again.

On Windows PowerShell, you can stop the process with:

```powershell
Get-NetTCPConnection -LocalPort 8000 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### `.env` missing

Run:

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

### PowerShell says script execution is disabled

Run PowerShell as your normal user and execute:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## Scope Note

This local guide is for non-production use.

For internet-facing hosting, use:

- `docs/ADMIN_HOSTING_GUIDE.md`
- `docs/SERVER_HOSTING_GUIDE.md`
