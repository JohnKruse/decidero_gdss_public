# Decidero Local Setup Guide

This guide is for anyone who wants to run Decidero locally for practice, testing, or exploration with the lowest possible setup effort.

## Quick Start (One-Time Setup)

From the project root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
./start_local.sh
```

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
