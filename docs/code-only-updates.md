# Code-Only Updates

How to update the Python application on the running VM **without reprovisioning any Azure infrastructure**.

---

## Option A — `make deploy` (SSH + git pull)

The fastest path. Pulls the latest code from the `main` branch and restarts the service.

**Requirements**: The VM must be running and reachable.

```bash
make deploy
```

Under the hood this runs `scripts/deploy.sh` which:

1. SSHes into the VM
2. `git pull` in `/opt/app`
3. `pip install -r requirements.txt` (picks up any new dependencies)
4. `systemctl restart app`
5. Confirms the service is active and prints the last 10 log lines

To deploy to a specific IP (useful when the Terraform state is not local):

```bash
./scripts/deploy.sh 20.1.2.3
./scripts/deploy.sh 20.1.2.3 azureuser ~/.ssh/id_rsa
```

---

## Option B — Manual SSH

Gives you full control; useful for debugging or staged rollouts.

```bash
make ssh
# or: ssh -i ~/.ssh/id_rsa azureuser@<public_ip>
```

Once inside:

```bash
cd /opt/app

# Pull latest code
sudo git pull

# Install any new dependencies
sudo /opt/app/.venv/bin/pip install -r requirements.txt

# Restart the service
sudo systemctl restart app

# Confirm it's running
systemctl is-active app
journalctl -u app -n 20 --no-pager
```

---

## Option C — GitHub Actions (automated CI/CD)

The `.github/workflows/deploy.yml` workflow triggers on every push to `main`.

### Setup

1. **Add repository secrets** in GitHub → Settings → Secrets and variables → Actions:

   | Secret | Value |
   |--------|-------|
   | `VM_HOST` | Public IP of the VM (from `make output`) |
   | `VM_USER` | `azureuser` |
   | `VM_SSH_KEY` | Content of `~/.ssh/id_rsa` (the private key) |

2. Push code to `main`:

   ```bash
   git add .
   git commit -m "feat: update app"
   git push origin main
   ```

3. GitHub Actions runs the deploy job automatically.

### Workflow steps

```
push to main
  → checkout
  → SSH into VM
  → git pull /opt/app
  → pip install -r requirements.txt
  → systemctl restart app
  → verify systemctl is-active app
```

See [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) for the full definition.

---

## Option D — Full Re-provisioning (`terraform taint`)

Destroys and recreates the VM from scratch. Use when:

- The VM is in an unrecoverable state
- You changed the cloud-init script (`scripts/cloud-init.yaml`)
- You want to update the OS or change the image

```bash
cd terraform
terraform taint azurerm_linux_virtual_machine.app_vm
make apply-auto
```

Terraform will destroy the VM, create a new one, and run cloud-init again with the latest `app_repo_url`. Any data stored on the OS disk is lost.

---

## Choosing the Right Option

| Scenario | Recommended option |
|----------|--------------------|
| Quick code fix in dev | `make deploy` (Option A) |
| Debugging a failing update | Manual SSH (Option B) |
| Team workflow, push to deploy | GitHub Actions (Option C) |
| OS update / cloud-init change | Taint + re-apply (Option D) |
| VM unrecoverable | Taint + re-apply (Option D) |

---

## Deployment Checklist

Before deploying:

- [ ] Code is pushed to the correct branch / tag
- [ ] `requirements.txt` is up to date
- [ ] No breaking environment variable changes (or `.env` has been updated on the VM)
- [ ] The service starts cleanly locally: `uvicorn main:app`

After deploying:

- [ ] `systemctl is-active app` returns `active`
- [ ] `GET /health` returns `{"status":"healthy"}`
- [ ] `make logs` shows no errors
