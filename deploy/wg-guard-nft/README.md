# nft guard rules for the wg-burns tunnel, both ends of the lifecycle

The house's tunnel carries inbound to sms.deralsem.ru. `wgguard.nft` is the
guard around it: only the far end may reach SSH and HTTP through the tunnel,
pings pass, everything else into the tunnel drops, and nothing forwards
through it at all. It used to load from `PostUp` in `/etc/wireguard/wg-burns.conf`.

## What broke, and why the shape changed

Ubuntu 26.04 ships an AppArmor profile for `wg-quick`. Its nested `nft`
sub-profile permits reading only `/usr/share/iproute2/{rt_realms,group}` —
no user ruleset, ever. After the 24.04 → 26.04 release upgrade (2026-10-04)
every tunnel start died at `PostUp = nft -f …` with `Permission denied` for
root, wg-quick tore the interface down, and the unit sat in a restart loop:
the edge answered TLS into a tunnel with nobody behind it.

`aa-disable` was the stopgap the day of the incident. The shape here is the
repair: the load moves out of PostUp into `wg-guard-nft.service`, which runs
unconfined (no profile exists for a standalone nft), and the stock profile —
whose confinement reached the last PostUp step successfully — goes back on.
Two files, both installed as copies:

| File | Machine | Role |
|---|---|---|
| `wg-guard-nft.service` | the house | Loads the ruleset with the tunnel, removes it without it |
| drop-in `guard.conf` (inline below) | the house | Makes the guard start, restart and stop with `wg-quick@wg-burns` |

Nothing changes on the far end.

## Install (on the house)

```sh
sudo install -m 644 wg-guard-nft.service /etc/systemd/system/
sudo mkdir -p /etc/systemd/system/wg-quick@wg-burns.service.d
sudo install -m 644 guard.conf /etc/systemd/system/wg-quick@wg-burns.service.d/guard.conf

# the two nft lines leave wg-burns.conf — the key line stays
sudo sed -i '/^PostUp = nft -f/d; /^PostDown = nft delete table inet wgguard/d' \
    /etc/wireguard/wg-burns.conf

# back to the stock profile, confined
sudo rm -f /etc/apparmor.d/disable/wg-quick
sudo apparmor_parser -r /etc/apparmor.d/wg-quick

sudo systemctl daemon-reload
sudo systemctl restart wg-quick@wg-burns
```

The restart blips the site for the few seconds the tunnel takes to re-handshake;
the edge's `proxy_read_timeout 60s` rides over it.

## Verify

```sh
systemctl is-active wg-quick@wg-burns wg-guard-nft
sudo nft list table inet wgguard | head      # rules present, one copy
journalctl -t kernel --since "-5 min" | grep -c "apparmor=\"DENIED\""   # 0
ping -c2 10.67.67.1                          # peer answers
```

Confined-but-working is the point: if the audit log shows denials from
`wg-quick` that did not stop it, that is upstream's profile being sloppy with
nss lookups and is fine; denials that stop the tunnel are not.

## These are copies, and nothing keeps them in step

Same standing warning as the nginx blocks: the live files on the machine are
copies installed by hand, and a deploy does not touch them. Assume they drift
until something enforces otherwise.
