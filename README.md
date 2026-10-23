# DMARC Visualizer

The DMARC reports the domains get, in charts: [parsedmarc](https://github.com/domainaware/parsedmarc)
reads aggregate, failure and SMTP TLS reports from a mailbox into OpenSearch, Grafana shows them, Caddy
keeps the certificate and the administrators' address list. Standalone on its own address, behind an
SNI proxy with the PROXY protocol like the other services, or only on an internal network.

Everything runs from the official images, nothing is built here. OpenSearch is on a network of its own
that leads nowhere, without its security plugin; only parsedmarc, Grafana and the retention reach it.

## Origin

A fork of [LukeCallaghan/dmarc-visualizer](https://github.com/LukeCallaghan/dmarc-visualizer), itself
built on the original from [Debricked](https://debricked.com/blog/2020/05/14/analyse-and-visualize-dmarc-results-using-open-source-tools/).
Little of it is left: Elasticsearch gave way to OpenSearch, the images built here to the official ones,
`parsedmarc.ini` to environment variables. The dashboard is parsedmarc's own
(`dashboards/grafana`, contributed by Bhozar), adapted to OpenSearch by `grafana/update-dashboard.py`.
Apache License 2.0, like both.

## Setup

```sh
cp .env.example .env    # fill it in
docker compose up -d
docker compose logs -f parsedmarc
```

OpenSearch runs as uid 1000 and Grafana as 472. The short-lived `permissions` service hands them their
directories before they start, they are created as root otherwise.

Grafana's administrator comes from `GRAFANA_ADMIN_*` on the first start only, so make the password a
throwaway one. Log in and change it, then remove `GRAFANA_ADMIN_PASSWORD` from `.env` and run
`docker compose up -d`: the container keeps it in its environment until it is recreated. A lost
password is reset with `docker compose exec grafana grafana cli admin reset-admin-password <new>`.
The login is limited to 10 attempts a minute per address by Caddy, on top of Grafana's own lockout.

### Login through Authentik

Grafana can take its users from Authentik over OpenID Connect instead of keeping its own. In
Authentik:

1. an OAuth2/OpenID provider: confidential client, redirect URI
   `https://<SERVER_NAME>/login/generic_oauth` (strict), the default scopes (`openid`, `profile`, which
   carries the groups, and `email`);
2. an application for it, such as with the slug `dmarc`, bound to the groups that may use it;
3. the groups: `Grafana Admins`, and `Grafana Viewers` if someone only looks (other names go to
   `OIDC_ADMIN_GROUP` and `OIDC_VIEWER_GROUP`).

Then `OIDC_ENABLED=true`, `OIDC_PROVIDER_URL`, `OIDC_CLIENT_ID` and `OIDC_CLIENT_SECRET` in `.env`
(`OIDC_LOGOUT_URL` to log out of Authentik too) and `docker compose up -d`. Grafana creates the user
at the first login and sets the role from the groups at every login. Someone in neither group is
refused, and so is a token without groups. The local administrator still logs in with the password:
keep it as the way in when Authentik is down. With `OIDC_AUTO_LOGIN=true` the login page is skipped,
the local login is then at `/login?disableAutoLogin`.

OpenSearch takes `OPENSEARCH_HEAP` (512 MB) for itself and the container about twice that. A few years
of reports for a handful of domains are a few hundred MB on disk.

## The mailbox

The domains' DMARC records send the reports to the mailbox in `IMAP_USER`
(`rua=mailto:…; ruf=mailto:…`), a TLS-RPT record (`_smtp._tls`, `v=TLSRPTv1; rua=mailto:…`) the
SMTP TLS reports. parsedmarc watches `REPORTS_FOLDER` and moves what it parsed to
`ARCHIVE_FOLDER/Aggregate`, `/Failure`, `/SMTP-TLS` or `/Invalid`. parsedmarc before 10.0 archived
failure reports in `/Forensic`, the first start moves them to `/Failure`.

Any other parsedmarc setting goes to `parsedmarc.env` (ignored by git) as
`PARSEDMARC_{SECTION}_{KEY}=value`, see the
[parsedmarc documentation](https://domainaware.github.io/parsedmarc/usage.html#configuration-file).

## How long reports are kept

The `retention` service deletes reports older than `RETENTION_AGGREGATE_DAYS` (365),
`RETENTION_SMTP_TLS_DAYS` (365) and `RETENTION_FAILURE_DAYS` (90), at start and then once a day; 0 keeps
them for good. A report's age is counted from the day it begins (aggregate, SMTP TLS) or the day the
message arrived (failure). An index whose whole month is past the limit goes at once, the oldest month
that is not report by report. It logs what it deleted:

```sh
docker compose logs retention
```

Failure reports carry the headers of real messages, with their senders and recipients, so they are
kept the shortest. The mailbox archive is not touched: what is to go from there, empty in the mailbox.

## Parsing the archive again

A new installation, or OpenSearch lost: `archive-import` parses a folder of the archive again without
moving anything. Reports already stored are skipped, so a run can be repeated. One folder per run, the
whole folder at once (thousands of reports take a while, mostly DNS lookups):

```sh
docker compose run --rm archive-import
docker compose run --rm -e PARSEDMARC_MAILBOX_REPORTS_FOLDER=Archive/Failure archive-import
docker compose run --rm -e PARSEDMARC_MAILBOX_REPORTS_FOLDER=Archive/SMTP-TLS archive-import
```

The first parses `Archive/Aggregate`. The retention then deletes what is older than its limits.

## The dashboard

`grafana/dashboards/dmarc-reports.json` is the home page. It is provisioned from the repository, so a
change made in Grafana cannot be saved over it: edit the panel, then copy the JSON model (dashboard
settings → JSON Model) into the file. Grafana reads it again within seconds, or on a restart.

The data sources are provisioned too: `dmarc-ag` for aggregate reports, `dmarc-fo` for failure reports,
`smtp-tls` for Explore. Their "Test" button reports "Index not found" because of the wildcard in the
index name; the plugin looks for the pattern itself among the indexes it finds. The queries work.

parsedmarc keeps improving its dashboard. To take a newer one:

```sh
python3 grafana/update-dashboard.py        # or a tag or commit of parsedmarc
```

It points the data source variables at OpenSearch, turns off the automatic refresh and fixes the
"Failure Samples" table, which groups by a column title instead of a field upstream. Name the
parsedmarc commit it prints in the commit message. Changes of our own to the dashboard would be lost by
this; make them in the script, like those.

## Trying it without a mailbox

`samples/` holds parsedmarc's sample reports. They are from the past, so set the time range to the last
15 years and the retention to 0:

```sh
docker compose up -d opensearch grafana caddy
docker compose run --rm samples
```

## Firewall

Standalone, Caddy obtains the certificate over port 80, which therefore has to be open from the
internet. Port 443 can be limited to `ADMIN_IPS` on the firewall as well. parsedmarc needs IMAP out to
the mailbox and DNS, Grafana HTTPS to grafana.com for its plugins.

Only on an internal network (`compose.internal.yaml`), nothing has to be open from the internet: Caddy
issues the certificate from its own CA, which lives in `DATA_DIR` with the rest. `SERVER_NAME` can be
the server's IP address. Browsers warn until they trust its root certificate,
`data/caddy/data/caddy/pki/authorities/local/root.crt`; on Windows
`certutil -addstore -user Root root.crt`.

## Backups

The reports can be parsed again from the mailbox archive (see above), so OpenSearch need not be backed
up. Grafana's database holds the users. Back up `DATA_DIR` without `opensearch/`.

## Updates

The services carry the label `com.centurylinklabs.watchtower.enable`, so a Watchtower running with
`WATCHTOWER_LABEL_ENABLE` on the host keeps them current. parsedmarc and Grafana follow `latest`, major
releases included, read their notes when one comes. OpenSearch stays on major version 3: indexes from
two majors back cannot be opened, so before the next one, parse the archive again into a new
installation. By hand:

```sh
docker compose pull && docker compose up -d && docker image prune -f
```
