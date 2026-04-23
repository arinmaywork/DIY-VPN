# 01 — Hosting: Getting your free server

## Primary plan: Oracle Cloud Always Free (Ampere A1 ARM)

### What you're claiming

Oracle's "Always Free" tier includes:
- Up to **4 Ampere A1 cores** and **24 GB of RAM** in total, which you can allocate to 1 big VM or split across up to 4 smaller ones.
- **200 GB** of block storage (plenty for our use).
- **10 TB** outbound bandwidth per month (this is the killer feature — more than you will use).
- **1 public IPv4** + IPv6.
- No 12-month timer. It's free forever, as long as you log in every so often.

We'll allocate **all 4 cores and 24 GB RAM to a single VM** for the VPN.

---

### Step 1 — Sign up

1. Go to **https://www.oracle.com/cloud/free/** → *Start for free*.
2. You'll need:
   - A valid **email** (use a fresh one if you want)
   - A **phone number** (used for SMS verification)
   - A **credit or debit card** (verification only — no charge, you will NOT be auto-upgraded to paid without explicit consent). Virtual cards from Revolut / Wise often work. Prepaid cards usually don't.
3. **Home region** — this choice is permanent. Pick carefully:

   | Region | Latency from China | Notes |
   |---|---|---|
   | **ap-seoul-1** (Seoul) | Very low | Often crowded, signups may fail |
   | **ap-chuncheon-1** (Chuncheon, Korea) | Low | Newer, often has capacity |
   | **ap-tokyo-1** (Tokyo) | Low | Sometimes IP ranges are dirty for China |
   | **ap-osaka-1** (Osaka) | Low | Good alternative to Tokyo |
   | **ap-singapore-1** (Singapore) | Medium | Stable, good capacity |
   | **us-phoenix-1** / **us-sanjose-1** | Higher | Good if you're primarily in US or need western content |
   | **eu-amsterdam-1** / **eu-frankfurt-1** | High from China | Great if you're in Europe |

   **Recommendation for China:** try **Chuncheon** first, then **Osaka**, then **Singapore**. If none have capacity, try **us-sanjose-1** (still usable from China via decent routes).

4. Verify via SMS, verify the card (a small auth-hold appears and is released). Wait for the account-ready email (can take minutes to a few hours).

---

### Step 2 — Generate your SSH keypair (do this BEFORE creating the VM)

On your local computer (Mac / Windows / Linux):

**macOS / Linux:**
```bash
ssh-keygen -t ed25519 -f ~/.ssh/diyvpn_ed25519 -C "diyvpn"
# Press enter twice for no passphrase (or set one — safer)
cat ~/.ssh/diyvpn_ed25519.pub   # this is what you paste into Oracle
```

**Windows (PowerShell):**
```powershell
ssh-keygen -t ed25519 -f $HOME\.ssh\diyvpn_ed25519 -C "diyvpn"
Get-Content $HOME\.ssh\diyvpn_ed25519.pub
```

Save the **public key** (`.pub` file contents) — you'll paste it in the next step. Keep the **private key** secret; it's how you log into your server.

---

### Step 3 — Create the Ampere A1 VM

1. In the Oracle console, go to **Compute → Instances → Create instance**.
2. **Name:** `diyvpn` (anything you want)
3. **Image:** Click *Change image* → **Canonical Ubuntu 22.04** (ARM64 / aarch64 build). *(Ubuntu 24.04 also works — the installer supports both.)*
4. **Shape:** Click *Change shape* → **Ampere** → **VM.Standard.A1.Flex**
   - OCPUs: **4**
   - Memory: **24 GB**
   - If you get "Out of capacity", retry every few hours, or try a different availability domain, or lower to 1 OCPU / 6 GB (still plenty).
5. **Networking:**
   - *Primary network* → Create new VCN (default settings are fine)
   - *Subnet* → Create new public subnet
   - **Public IPv4 address:** Assign public IPv4 — **yes**
6. **SSH keys:** Paste the **public** key you generated above.
7. **Boot volume:** 100 GB is fine (free tier allows up to 200 GB across all volumes).
8. Click **Create**.

After ~1 minute, you'll see a **public IP** on the instance details page. **Copy this.** You'll use it constantly.

---

### Step 4 — Open the firewall (CRITICAL — most people miss this)

Oracle has **two** firewall layers. You must configure **both**, or nothing will connect.

#### 4a — Oracle VCN Security List (cloud-side firewall)

1. In the console: **Networking → Virtual Cloud Networks → [your VCN] → Security Lists → Default Security List**.
2. **Add these Ingress Rules** (all with Source CIDR `0.0.0.0/0`):

   | Stateless | Protocol | Source Port | Destination Port | Purpose |
   |---|---|---|---|---|
   | No | TCP | All | **22** (or your custom SSH port) | SSH |
   | No | TCP | All | **443** | Reality (VLESS TCP) |
   | No | UDP | All | **443** | Hysteria2 (primary) |
   | No | UDP | All | **20000-50000** | Hysteria2 port hopping |

   *(If you prefer to move SSH off 22 — which I recommend — open your custom port here too. Example: port `62022`.)*

3. Click **Add Ingress Rules** to save.

#### 4b — Linux iptables/netfilter (host-side firewall)

Oracle's Ubuntu image ships with `iptables` that **drops most inbound traffic by default** — even what you allowed in the VCN. The install script handles this automatically, but if you're doing it manually see [02-SERVER-SETUP.md](02-SERVER-SETUP.md).

---

### Step 5 — Test SSH

```bash
ssh -i ~/.ssh/diyvpn_ed25519 ubuntu@<YOUR_PUBLIC_IP>
```

If this works, **you are ready**. Continue to [02-SERVER-SETUP.md](02-SERVER-SETUP.md).

If it hangs or times out → you missed a firewall step. Check both 4a and 4b.
If "permission denied" → you pasted the wrong key or are using the wrong private key file (`-i` flag).
If "host unreachable" → wait 2 minutes and retry; instance may still be initializing.

---

## Fallback plans

### Plan B — Google Cloud e2-micro (Always Free, but tiny)

- 1 vCPU, 1 GB RAM, 30 GB disk
- **1 GB egress/month to most regions** (painfully small — only good for light browsing)
- Free forever in US regions: us-west1 (Oregon), us-central1 (Iowa), us-east1 (S. Carolina)
- Requires card verification

Use this only if Oracle is completely unavailable to you. The protocols in this repo all work on it; you'll just hit the bandwidth cap fast.

### Plan C — Fly.io

- Up to 3 shared-cpu-1x 256 MB VMs (free)
- 160 GB outbound bandwidth / month (shared across all apps)
- No card required for small accounts
- Deployment is different (Docker-based) — I can give you a Fly-specific setup if you need it.

### Plan D — AWS / Azure (12-month free)

Both work but expire after 12 months, then you pay. Not recommended for a long-term free setup.

### Plan E — Buy a cheap VPS

If none of the above pan out, **Hetzner Cloud** has `CX22` at ~€4.5/month with 20 TB bandwidth included and excellent network quality. Not free but hard to beat the value. Locations: Germany, Finland, US. (Hetzner routes to China are generally decent.)

Other good cheap providers: **RackNerd** (~$12/year deals), **BandwagonHost** (CN2 GIA routes — premium to China, ~$50/year).

---

## Which region for China specifically?

A lot depends on the exact ISP the user is on in China (Telecom / Unicom / Mobile each have different international routes):

- **China Telecom users** → prefer **Japan (Tokyo)**, **Los Angeles**, **San Jose**
- **China Unicom users** → prefer **Japan (Osaka)**, **San Jose**, **Hong Kong** (Oracle doesn't offer HK free tier though)
- **China Mobile users** → prefer **Singapore**, **Frankfurt**, **London**

If you know which ISP you'll be using, factor that in. If you don't — **Korea (Chuncheon)** or **Japan** are safe defaults for most Chinese users.

---

Next step → [02-SERVER-SETUP.md](02-SERVER-SETUP.md)
