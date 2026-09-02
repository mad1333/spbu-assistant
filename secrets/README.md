Create these files on the server and never commit them:

- `telegram_bot_token.txt`
- `telegram_webhook_secret.txt`
- `token_signing_key.txt`
- `mail_credentials_key.txt`

Use independent random values for `token_signing_key.txt` and `mail_credentials_key.txt`.
Each should contain at least 32 random characters. The mail key encrypts student-mail credentials;
losing it makes saved mail connections unreadable, while leaking it together with the database
exposes them.
