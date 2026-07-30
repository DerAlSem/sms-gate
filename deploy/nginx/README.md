# nginx, both ends

The gateway is reached over a tunnel from `edge.example.com`, which publishes `gateway.example.com`. Two
server blocks make that work and they live on two different machines, so neither of them is
obvious from the other.

| File | Machine | Role |
|---|---|---|
| `mprz-gateway.example.com.conf` | `edge.example.com` | Terminates TLS, proxies over the tunnel |
| `house-gateway-tunnel.conf` | the house | Answers on the tunnel address, proxies to uvicorn |
| `edge-alert-relay.conf` | `edge.example.com` | Carries the house's alerts to Telegram when its own carrier cannot |

## These carry placeholder values — do not install them as they stand

`gateway.example.com`, `edge.example.com` and the `10.10.10.x` addresses are placeholders. This
repository is public, and publishing one installation's hostnames and origin address only
tells a stranger where to look; the shape is what generalises, and the shape is what is here.

**Substitute your own values before installing.** The live files on the machines hold the real
ones, so a straight `install` from this tree would replace a working configuration with an
example — which is why the commands below take a copy first.

## These are copies, and nothing keeps them in step

Installing them is manual, and a deploy does not touch them. The same is true of
`deploy/sms-gate.service`, and it has already cost this project once: a change to that unit
was committed, deployed, tested and inert at the same time, because the installed unit is a
copy rather than a link. Assume the same of these until something enforces otherwise —
`openspec/changes/reach-the-gateway-on-any-uplink/tasks.md` names it as work.

```sh
# on edge.example.com
sudo install -m 644 mprz-gateway.example.com.conf /etc/nginx/sites-available/gateway.example.com
sudo ln -sfn /etc/nginx/sites-available/gateway.example.com /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# on the house
sudo install -m 644 house-gateway-tunnel.conf /etc/nginx/sites-available/sms-gate-tunnel
sudo ln -sfn /etc/nginx/sites-available/sms-gate-tunnel /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` as its own step, before the reload. On the far end a broken configuration takes every live site there down, not one.

## Why the relay sits on port 80

The tunnel-facing ports permitted on `edge.example.com` are 22, 80 and 443; anything else is dropped
before nginx sees it, which cost an afternoon to discover because nginx was listening and
answering locally the whole time. `listen 10.10.10.1:80` is a more specific match than the
`listen 80` the public sites share, so it takes that address only and leaves them untouched.

## The caller's address

Only `edge.example.com` sees it. It sets `X-Forwarded-For` from the peer; the house passes that
through **unchanged**, and uvicorn — started with `--proxy-headers` and trusting the loopback
— reads it.

The mistake to avoid is `$proxy_add_x_forwarded_for` on the house. It appends the house's own
view of its peer, which is the far end's tunnel address, and uvicorn reads the last entry: the
caller's address is replaced by a number that is identical on every request. The log looks
populated and carries nothing, which is worse than it looking empty.
