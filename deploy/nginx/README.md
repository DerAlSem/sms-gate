# nginx, both ends

The gateway is reached over a tunnel from `mprz.ru`, which publishes `sms.deralsem.ru`. Two
server blocks make that work and they live on two different machines, so neither of them is
obvious from the other.

| File | Machine | Role |
|---|---|---|
| `mprz-sms.deralsem.ru.conf` | `mprz.ru` | Terminates TLS, proxies over the tunnel |
| `home-sms-gate-tunnel.conf` | the house | Answers on the tunnel address, proxies to uvicorn |

## These are copies, and nothing keeps them in step

Installing them is manual, and a deploy does not touch them. The same is true of
`deploy/sms-gate.service`, and it has already cost this project once: a change to that unit
was committed, deployed, tested and inert at the same time, because the installed unit is a
copy rather than a link. Assume the same of these until something enforces otherwise —
`openspec/changes/reach-the-gateway-on-any-uplink/tasks.md` names it as work.

```sh
# on mprz.ru
sudo install -m 644 mprz-sms.deralsem.ru.conf /etc/nginx/sites-available/sms.deralsem.ru
sudo ln -sfn /etc/nginx/sites-available/sms.deralsem.ru /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# on the house
sudo install -m 644 home-sms-gate-tunnel.conf /etc/nginx/sites-available/sms-gate-tunnel
sudo ln -sfn /etc/nginx/sites-available/sms-gate-tunnel /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` as its own step, before the reload. On `mprz.ru` a broken configuration takes
eleven live sites down, not one.

## The caller's address

Only `mprz.ru` sees it. It sets `X-Forwarded-For` from the peer; the house passes that
through **unchanged**, and uvicorn — started with `--proxy-headers` and trusting the loopback
— reads it.

The mistake to avoid is `$proxy_add_x_forwarded_for` on the house. It appends the house's own
view of its peer, which is the far end's tunnel address, and uvicorn reads the last entry: the
caller's address is replaced by a number that is identical on every request. The log looks
populated and carries nothing, which is worse than it looking empty.
