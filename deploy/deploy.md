# VPS Deployment Guide — Order-Flow Agent (Continuous, Static-IP)

Ye guide follow karo apne VPS provider (DigitalOcean / Hetzner / AWS
Lightsail — koi bhi chalega) pe server lene ke baad. Har command copy-paste
karo apne server ke terminal me (SSH ke through).

## Step 1 — VPS lo (tumhare end se)

1. Kisi bhi provider pe account banao:
   - **DigitalOcean**: digitalocean.com — sabse simple UI, ~$4-6/month
   - **Hetzner**: hetzner.com — sabse sasta, ~€4/month
   - **AWS Lightsail**: sasta aur reliable, ~$5/month
2. Naya **Droplet/Instance** banao:
   - OS: **Ubuntu 22.04** (ya latest LTS)
   - Plan: sabse basic/cheapest wala (1 vCPU, 1GB RAM kaafi hai)
   - Region: **Mumbai/Bangalore** (India) agar option ho, warna Singapore
3. Server ban jaane ke baad, tumhe uska **IP address** milega (jaise `123.45.67.89`) — ye
   IP **fixed/static** rahega, kabhi nahi badlega. **Ye IP note kar lo.**
4. Provider tumhe ek **root password** ya **SSH key** dega login ke liye.

## Step 2 — Server se connect karo

Windows pe **PowerShell** kholo (jaisa pehle Groww test ke liye kiya tha), aur:

```powershell
ssh root@<TUMHARA_SERVER_IP>
```

Password/key se login karo jab pucha jaye.

## Step 3 — Server pe zaroori software install karo

Server ke terminal me ye sab ek-ek karke paste karo:

```bash
apt update && apt upgrade -y
apt install -y python3 python3-pip git
```

## Step 4 — Agent code laao

```bash
mkdir -p /opt/order-flow-agent
cd /opt/order-flow-agent
git clone https://github.com/sumitd8292-blip/Trading.git .
pip3 install --break-system-packages requests pynacl
```

## Step 5 — Secrets fill karo

```bash
nano /etc/systemd/system/order-flow-agent.service
```

(Pehle service file ko copy karna hoga — Step 6 me bataya hai.)

## Step 6 — Systemd service file daalo

```bash
cp /opt/order-flow-agent/deploy/order-flow-agent.service /etc/systemd/system/
nano /etc/systemd/system/order-flow-agent.service
```

Is file me 4 jagah `REPLACE_ME` likha milega — inhe apne actual values se replace karo:
- `TELEGRAM_BOT_TOKEN` — jo pehle GitHub Secrets me daala tha
- `TELEGRAM_CHAT_ID` — `953932948`
- `GROWW_API_KEY` — aaj wali fresh key (yaad rakhna: **roz subah 6 baje reset hoti hai**, isliye roz update karni padegi — Step 9 dekho)
- `GROWW_API_SECRET` — wahi secret jo pehle diya tha

Save karne ke liye: `Ctrl+O`, phir `Enter`, phir `Ctrl+X`.

## Step 7 — Service start karo

```bash
systemctl daemon-reload
systemctl enable order-flow-agent
systemctl start order-flow-agent
systemctl status order-flow-agent
```

Agar sab sahi hai to "active (running)" green me dikhega.

## Step 8 — Logs check karo

```bash
tail -f /var/log/order-flow-agent.log
```

(`Ctrl+C` se bahar aao)

## Step 9 — Static IP ko Groww me register karo

1. `curl ifconfig.me` chalao server pe — apna IP confirm karo
2. Groww dashboard → **groww.in/trade-api/api-keys** → **"Add static IP"** button pe click karo
3. Wahi IP daal do
4. Save karo

## Step 10 — Roz subah token update karna (jab tak auto-refresh na bane)

Groww ka access token roz 6 AM ko expire hota hai. Roz subah:
1. Naya key generate karo Groww dashboard se ("order-flow-agent" wali row se)
2. Server pe:
```bash
nano /etc/systemd/system/order-flow-agent.service
```
3. `GROWW_API_KEY=` wali line update karo naye token se
4. Save karke:
```bash
systemctl daemon-reload
systemctl restart order-flow-agent
```

**Future improvement (not yet built):** Ye daily manual step automate karne
ke liye Groww ke TOTP-based refresh flow ko investigate karna hoga — tab
tak ye ek roz ka 2-minute manual kaam rahega.
