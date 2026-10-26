# nginx hardening for Zenith

The backend already limits the sign-in, sign-up and email endpoints itself (`backend/ratelimit.py`) and adds
`X-Content-Type-Options`, `X-Frame-Options` and a `frame-ancestors` policy to every API response. The snippets below
add a second, coarser layer in nginx (it stops floods before they reach Python) and the security headers for the
website itself.

The backend only believes `X-Real-IP` / `X-Forwarded-For` when the request comes from `127.0.0.1`, i.e. from nginx on
the same server. So keep proxying to `127.0.0.1:8000` (not the public IP) and pass the headers shown below, otherwise
every visitor shares one rate-limit bucket.

## 1. In the `http { }` block (`/etc/nginx/nginx.conf`)

```nginx
# Don't print the nginx version on error pages or in the Server header
server_tokens off;

# Up to 10 requests a minute per IP to the auth endpoints, with short bursts allowed (see "location /auth/" below)
limit_req_zone $binary_remote_addr zone=zenith_auth:10m rate=10r/m;
# A generous general limit for the rest of the API
limit_req_zone $binary_remote_addr zone=zenith_api:10m rate=10r/s;
limit_req_status 429;
```

## 2. API server block (`api.zenithwalletracker.ca`)

```nginx
server {
    server_name api.zenithwalletracker.ca;
    # ... your existing listen 443 ssl / certificate lines stay as they are ...

    # nosniff, X-Frame-Options, frame-ancestors and Referrer-Policy come from the backend itself
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # CSV imports send up to 2 MB (everything else is small JSON). `bash deploy/deploy.sh --setup-nginx` sets this.
    client_max_body_size 3m;

    location /auth/ {
        limit_req zone=zenith_auth burst=10 nodelay;
        include /etc/nginx/snippets/zenith-proxy.conf;
    }

    location / {
        limit_req zone=zenith_api burst=40 nodelay;
        include /etc/nginx/snippets/zenith-proxy.conf;
    }
}
```

`/etc/nginx/snippets/zenith-proxy.conf`:

```nginx
proxy_pass http://127.0.0.1:8000;
proxy_set_header Host $host;
# the backend reads these only because the request comes from 127.0.0.1
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

Google sign-in (`/auth/google/start` and `/auth/google/callback`) also lives under `/auth/`; 10 a minute with a burst
of 10 is far more than one person needs, so it isn't affected in practice.

## 3. Website server block (`zenithwalletracker.ca`)

```nginx
server {
    server_name zenithwalletracker.ca www.zenithwalletracker.ca;
    # ... existing listen / ssl lines ...

    # served straight from the build folder: deploy/deploy.sh builds into dist-next and swaps it in with a rename,
    # so nothing is copied and the site is never half-updated
    root /home/deploy/walletapp/frontend/dist;
    index index.html;

    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Content-Security-Policy "frame-ancestors 'none'" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        try_files $uri /index.html;
    }
}
```

Note: nginx only inherits `add_header` lines into a `location` that has no `add_header` of its own. If a `location`
adds headers (e.g. `Cache-Control` for `/assets/`), repeat the security headers there.

Only turn on `includeSubDomains` (or add `preload`) if every subdomain is served over HTTPS; the API and the website
both are today.

## 4. Apply

```bash
sudo nginx -t && sudo systemctl reload nginx
curl -sI https://api.zenithwalletracker.ca/auth/providers | grep -iE 'strict|nosniff|frame|server'
curl -sI https://zenithwalletracker.ca | grep -iE 'strict|nosniff|frame|server'
```

`nginx -t` checks the config before reloading, so a typo can't take the site down.

## 4. Access logs: 14 days, no tokens

The privacy policy and Apple's privacy manifest promise request logs are kept for at most 14 days. Emailed links
(`/verify?token=…`, `/reset-password?token=…`) put live one-time tokens in the website's query string, so the website
log drops query strings on those two pages.

In the `http { }` block:

```nginx
# $request with the query string removed, for the pages whose links carry one-time tokens
map $request_uri $zenith_logged_uri {
    ~^(?<zenith_path>/(verify|reset-password))\?  $zenith_path?[removed];
    default                                        $request_uri;
}
log_format zenith '$remote_addr - [$time_local] "$request_method $zenith_logged_uri $server_protocol" '
                  '$status $body_bytes_sent "$http_user_agent" $request_time';
```

In both server blocks: `access_log /var/log/nginx/zenith.access.log zenith;`

`/etc/logrotate.d/nginx` (the stock file rotates weekly and keeps 52): set it to rotate daily and keep 14:

```
/var/log/nginx/*.log {
    daily
    rotate 14
    missingok
    compress
    delaycompress
    notifempty
    create 0640 www-data adm
    sharedscripts
    postrotate
        invoke-rc.d nginx rotate >/dev/null 2>&1
    endscript
}
```

The API's own uvicorn access log is switched off (`--no-access-log` in `deploy/walletapp-backend.service`) and the
journal is capped at 14 days (`deploy/journald-zenith.conf`).

## 5. Website Content-Security-Policy (optional, test first)

The website keeps the login token in localStorage, so a script injected into the page could read it; a CSP that
only allows the site's own scripts closes that off. Start with `Content-Security-Policy-Report-Only`, click through
every page (including the price charts, coin logos and Google sign-in) with the browser console open, then switch
to the enforcing header:

```nginx
add_header Content-Security-Policy-Report-Only "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://coin-images.coingecko.com https://assets.coingecko.com; connect-src 'self' https://api.zenithwalletracker.ca; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://api.zenithwalletracker.ca" always;
```
