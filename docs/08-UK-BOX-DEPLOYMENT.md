# 08 — UK box deployment (second Oracle Always Free account)

This walks you through bringing up a second VPN box in **eu-london-1** under
a separate Oracle Always Free account, then wiring it into the existing
Telegram bot alongside the Toronto box.

The bot will treat the two boxes as independent endpoints — each user gets
**different credentials per box** (separate UUID + Hy2 password), so you'll
have two profiles in your client and can `/switch` between them.

---

## Prereqs (on your laptop)

- Access to your second Oracle Cloud account, **home region = UK South (London)**.
- The bot host (sentistack GCP VM) is already running. We won't touch it
  until the very end.

> **Why a second account?** Oracle's Always Free quota is per-tenancy, not
> per-region. Same account = same 4 cores + 24 GB pool, and you can't run
> two AMD micros from one tenancy. A second account doubles the free pool.

---

## Step 1 — Pick the shape

Two options for an Always Free instance:

| Shape | Arch | What you get | Recommended? |
|---|---|---|---|
| **VM.Standard.E2.1.Micro** | AMD x86_64 | 1 OCPU, 1 GB RAM | ✅ Available in every region, never out of capacity |
| **VM.Standard.A1.Flex (Ampere)** | ARM64 | up to 4 OCPU, 24 GB RAM | ⚠️ UK Ampere capacity is famously scarce — expect retries |

Toronto is already running an `A1.Flex` (24 GB) — for redundancy, run UK
on **`E2.1.Micro` (AMD)**. Less RAM, but Hy2 + Xray idle around 60 MB so
1 GB is more than enough. AMD micros also have zero capacity issues.

If you specifically want A1 in UK, keep the existing A1 retry loop running
on the side; in the meantime, get an `E2.1.Micro` up immediately so the box
is operational.

---

## Step 2 — Sign in + confirm region

1. Sign in at <https://cloud.oracle.com/> with the **second** account.
2. Top-right region selector should already say **UK South (London)** —
   that's the home region you picked at signup. Don't change it.

---

## Step 3 — Reuse the existing SSH key

You already have `diyvpn-oracle` (private key on sentistack at
`~/.ssh/diyvpn-oracle`). Reuse it — one less key to track.

On sentistack:

```bash
cat ~/.ssh/diyvpn-oracle.pub
# ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAA... diyvpn-oracle
```

Copy that single line. You'll paste it into the Oracle console at instance
creation.

---

## Step 4 — Networking: VCN + Internet Gateway + Security List

Before launching the instance, give it a place to live.

1. Console → ☰ **Networking** → **Virtual Cloud Networks** → **Start VCN
   Wizard** → **Create VCN with Internet Connectivity**.
2. Name it `diyvpn-vcn-uk`. Accept default CIDRs (`10.0.0.0/16`).
3. Wizard creates the VCN, public subnet, internet gateway, and route table
   with a `0.0.0.0/0 → IGW` rule. Good.
4. Open the **public subnet's Default Security List**. Click **Add Ingress
   Rules** and add these three (one rule per row):

| Source | IP Protocol | Source Port | Destination Port |
|---|---|---|---|
| `0.0.0.0/0` | TCP | (any) | `443` |
| `0.0.0.0/0` | UDP | (any) | `443` |
| `0.0.0.0/0` | UDP | (any) | `20000-50000` |

> SSH (`22/tcp`) is already open by the wizard — leave it alone.
> The `20000-50000/udp` range is for Hysteria2's port-hopping (optional but
> useful for evading per-port blocking).

---

## Step 5 — Launch the compute instance

1. Console → ☰ **Compute** → **Instances** → **Create instance**.
2. Name: `diyvpn-london`.
3. **Image**: change to **Canonical Ubuntu 22.04** (or 24.04 — both work).
4. **Shape**: change to **VM.Standard.E2.1.Micro** (AMD, Always Free).
5. **Networking**:
   - VCN: `diyvpn-vcn-uk`
   - Subnet: the public one the wizard made (`Public Subnet-diyvpn-vcn-uk`)
   - **Assign a public IPv4 address**: ✅ yes
6. **SSH keys**: paste the public key contents from Step 3 into
   *Paste public keys*.
7. **Boot volume**: leave at default 47 GB.
8. **Create**. Provisioning takes ~30 s.
9. Once the instance shows **Running**, copy the **Public IP address** from
   its details page. You'll need it in Step 7.

If you get *Out of capacity* on E2.1.Micro: that's rare but does happen.
Wait 5 min and retry — same shape always reappears within minutes in UK.

---

## Step 6 — First SSH from sentistack

```bash
ssh -i ~/.ssh/diyvpn-oracle ubuntu@<UK_PUBLIC_IP> uname -a
```

First connect prompts for host-key fingerprint — type `yes`. You should see
`Linux diyvpn-london ... aarch64` (or `x86_64` for E2). If this works,
networking is good.

If the connect hangs: re-check the security list ingress rule for
`22/tcp` and the public-IP assignment.

---

## Step 7 — Run the end-to-end installer on the UK box

```bash
ssh -i ~/.ssh/diyvpn-oracle ubuntu@<UK_PUBLIC_IP>

# On the UK box:
sudo apt-get update -y && sudo apt-get install -y git
git clone https://github.com/<your-handle>/DIY-VPN.git
cd DIY-VPN/server-box
sudo BOX_NAME=london ./install.sh
```

The installer (~3 min on E2 micro) will:

- Install Xray + Hysteria2, generate fresh Reality keys + Hy2 password.
- Open iptables, enable BBR, harden SSH, run fail2ban.
- Create the dedicated `xray` system user + hardening drop-in.
- Install the multi-user scaffolding (`/data/users.json`,
  `/data/credentials.env`, `diyvpn-render`, `diyvpn-auth`).
- Print the **UK public IP** + a ready-to-paste line for the bot's env.

When it finishes, copy the printed `VPN_BOXES=...` snippet — you'll need it
in Step 8.

---

## Step 8 — Wire the UK box into the Telegram bot

> **Note**: this assumes Task #17 (multi-box bot refactor) is done. If the
> bot still uses single-`VPN_HOST`, complete that refactor first or
> temporarily point `VPN_HOST` at whichever box you want to operate on.

On sentistack:

```bash
ssh sentistack
sudo -u arinmay_work -i
cd ~/DIY-VPN/telegram-bot

# Edit .env — replace VPN_HOST with VPN_BOXES (multi-box format).
# Format: <name>:<ip>,<name>:<ip>
# Example:
#   VPN_BOXES=toronto:40.233.120.150,london:<UK_PUBLIC_IP>
nano .env

# Restart the bot to pick up the new env:
sudo systemctl restart diyvpn-bot
sudo systemctl status diyvpn-bot --no-pager
```

Then in Telegram:

```
/boxes              # should list both: toronto, london (active marked)
/switch london      # set london as active for subsequent commands
/adduser default    # creates a `default` user on london (separate UUID)
/links default      # vless:// + hysteria2:// for the london box
```

You now have two independent profiles in your client. If one box goes
down, switch profile in the client → traffic uses the other box.

---

## Step 9 — Sanity checklist

From the bot host:

```bash
# Both boxes responding?
for ip in 40.233.120.150 <UK_PUBLIC_IP>; do
  echo "── $ip ──"
  ssh -i ~/.ssh/diyvpn-oracle ubuntu@$ip \
    sudo systemctl is-active diyvpn-auth hysteria-server xray
done
```

Expected: three `active` lines per box.

Or just `/status` in Telegram on each box (after `/switch`).

---

## Why "different credentials per box"?

If a share-link leaks for one box, you `/rotate <name>` on that box only —
the other box's link keeps working. If the link were shared between boxes,
a single leak would force a rotation on both, kicking every device.

This is the operational tradeoff for the convenience of "one user, one
password everywhere": we chose isolation. Worth it.
