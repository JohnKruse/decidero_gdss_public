# VPS Automation Scripts

<p align="center">
  <img src="../../app/static/assets/images/logo-360.png" alt="Decidero logo" width="220" />
</p>

Deploy Decidero on a fresh Ubuntu/Debian Linux server in a predictable, production-minded way without turning setup into a weekend project. These scripts automate the manual runbook in `docs/SERVER_HOSTING_GUIDE.md` so you get repeatability, safer defaults, and a cleaner path from "new server" to "live workshop."

## Hosting Scope

These instructions are not limited to VPS providers. They work on most single-node Linux hosts where you control the OS:

- Cloud VPS instances
- Dedicated/colo servers
- On-prem or homelab Linux machines
- Local VMs for staging or internal pilots

VPS is the default framing because it is the fastest path for most teams, but it is not a required platform choice.

## Why This Matters

Good decision systems do more than host forms and chat. They reduce coordination drag, help groups surface better options, and make high-stakes conversations more structured and transparent. Research in group decision support systems has consistently shown better outcomes when collaboration tooling is matched to task needs and used with clear process support.

Selected references:

- DeSanctis, G., & Gallupe, R. B. (1987). *A Foundation for the Study of Group Decision Support Systems*. Management Science, 33(5), 589-609. https://doi.org/10.1287/mnsc.33.5.589
- Dennis, A. R., Wixom, B. H., & Vandenberg, R. J. (2001). *Understanding Fit and Appropriation Effects in Group Support Systems via Meta-Analysis*. MIS Quarterly, 25(2), 167-193. https://aisel.aisnet.org/misq/vol25/iss2/2/

## Why This README Is Low-Hassle

- Scripts are idempotent where practical and map to standard Linux tooling (`systemd`, `Caddy`, `uvicorn`).
- The run order is explicit, so you can execute step-by-step with minimal guesswork.
- Environment overrides are documented up front for common customization needs.
- Generated production files are called out so review is straightforward before go-live.

## What They Do

- `bootstrap_ubuntu.sh`: base packages, app user, optional `ufw`.
- `deploy_decidero.sh`: clone/pull repo, create venv, install dependencies.
- `configure_systemd.sh`: write env file + service unit, enable/start service.
- `configure_caddy.sh`: write Caddyfile for domain, validate, reload.
- `install_backup_cron.sh`: install nightly SQLite backup cron entry.

## Recommended Run Order

1. `sudo bash scripts/vps/bootstrap_ubuntu.sh`
2. `sudo bash scripts/vps/deploy_decidero.sh <git_repo_url>`
3. `sudo DECIDERO_JWT_SECRET_KEY='<your_secret>' bash scripts/vps/configure_systemd.sh`
4. `sudo bash scripts/vps/configure_caddy.sh <your-domain>`
5. `sudo bash scripts/vps/install_backup_cron.sh`

## Useful Environment Overrides

- `DECIDERO_APP_USER` (default `decidero`)
- `DECIDERO_BASE_DIR` (default `/opt/decidero`)
- `DECIDERO_GIT_BRANCH` (default `main`)
- `DECIDERO_DOMAIN` (for caddy script)
- `DECIDERO_BLOCK_PUBLIC_REGISTER=true` (optional Caddy block on `/register`)
- `DECIDERO_BACKUP_CRON` (default `30 2 * * *`)

## Notes

- Scripts are intended for Ubuntu/Debian Linux servers (VPS or non-VPS).
- Run scripts as `root` unless noted otherwise.
- Review generated files before production rollout:
  - `/etc/decidero/decidero.env`
  - `/etc/systemd/system/decidero.service`
  - `/etc/caddy/Caddyfile`
