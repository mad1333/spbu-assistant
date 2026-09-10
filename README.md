# SPbU Assistant

A self-hosted timetable service for SPbU students. The current milestone provides:

- a first-party SPbU timetable API client;
- normalized lessons, cancellations, delivery modes, teachers, and locations;
- persistent snapshots and lesson revisions in PostgreSQL;
- change detection suitable for Telegram and calendar notifications;
- a Russian Telegram webhook interface with day, month, week, and lesson screens;
- a “next class” action that skips cancelled lessons;
- per-user display settings, digest switches, group changes, and English subgroup choice;
- on-demand refresh when a user opens a day or week;
- Telegram change alerts that also edit an already-sent daily timetable;
- configurable morning and evening timetable digests;
- teacher semester screens backed by official SPbU educator pages;
- revocable Apple and Google Calendar subscriptions split by lesson type and cancellation status;
- incoming student-mail text notifications and an SMTP compose flow in Telegram;
- Docker Compose deployment for a single VPS.

Student-mail notifications use a separate, time-limited HTTPS setup link. The service connects to
VK WorkSpace over IMAP/TLS, converts plain or HTML message bodies to safe readable Telegram text,
does not download attachments, and never marks messages as read. Message bodies are cleared from the
database after Telegram delivery. Short mail is delivered as one Markdown message; long mail is
delivered as one text-file message instead of being split or shortened. Sending uses SMTP/TLS and a
three-step recipient, subject, and body confirmation flow. Credentials are encrypted with a dedicated
server secret. Disconnecting mail in the bot removes the encrypted credential and notification
metadata.

## Development

Python 3.12+ is required.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest
```

Fetch a live timetable without writing to the database:

```bash
spbu-assistant fetch --group 474999 --from-date 2026-08-31 --to-date 2026-09-13
```

Run the local Docker stack:

```bash
docker compose -f compose.yaml -f compose.development.yaml up --build
```

The API health endpoint is then available at `http://localhost:8000/health`.

Apple and Google Calendar use separate subscribed calendars for lectures, practicals, seminars,
laboratories, other lessons, and cancellations. This lets users assign a color to every lesson type.
Revoking access in the bot immediately invalidates the private feed URLs. Calendar clients control
their own feed refresh frequency and require the user to remove an existing subscription on-device.

## Production

1. Point the domain's A/AAAA records at the VPS.
2. Copy `.env.example` to `.env` and set a strong database password.
3. Create all files documented in `secrets/README.md`.
4. Apply migrations.
5. Start the stack with `docker compose up -d --build`.

The `migrate` container applies migrations automatically before the API and worker start. The manual
migration step is useful for reviewing production output, but is not required by Compose.

The Telegram bot token and webhook secret belong in Docker secret files documented in
`secrets/README.md`; never commit them or paste them into Telegram messages.

After the containers start, register the production webhook:

```bash
curl -X POST "https://api.telegram.org/bot<token>/setWebhook" \
  -d "url=https://<domain>/telegram/webhook" \
  -d "secret_token=<webhook-secret>"
```

Do not provide SPbU unified-account passwords to the Telegram bot. Mail integration must use a dedicated HTTPS setup flow and the safest authorization method available for the university domain.

For student mail, prefer a dedicated external-application password created in VK WorkSpace. The
current SPbU configuration may also accept the unified mail password, but storing a dedicated,
revocable credential is safer. Existing inbox messages are used only to establish the initial cursor;
notifications begin with messages received after setup.

## Contributing

Development and pull-request guidelines are available in [CONTRIBUTING.md](CONTRIBUTING.md).

## Telegram administration

Set `TELEGRAM_ADMIN_IDS` to a comma-separated list of trusted Telegram IDs.
Authorized users open the private panel with `/admin`. The panel shows usage
totals, recent activity, group distribution, mail connections, and calendar setup
requests without exposing passwords or mail contents.

## License

SPbU Assistant is distributed under the [MIT License](LICENSE).
