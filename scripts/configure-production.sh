#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
secrets_dir="$project_dir/secrets"
env_file="$project_dir/.env"

mkdir -p "$secrets_dir"
chmod 700 "$secrets_dir"

printf "Домен без https:// (например schedule.example.ru): "
IFS= read -r app_domain
case "$app_domain" in
  ''|*[!A-Za-z0-9.-]*)
    printf 'Некорректный домен. Используйте только имя хоста без протокола и пути.\n' >&2
    exit 1
    ;;
esac
printf "Токен Telegram-бота (ввод скрыт): "
restore_echo() {
  stty echo 2>/dev/null || true
}
trap restore_echo EXIT INT TERM
stty -echo
IFS= read -r bot_token
stty echo
trap - EXIT INT TERM
printf "\n"

postgres_password=$(openssl rand -hex 32)
webhook_secret=$(openssl rand -hex 32)
token_signing_key=$(openssl rand -base64 48 | tr -d '\n')
mail_credentials_key=$(openssl rand -base64 48 | tr -d '\n')

umask 077
printf 'APP_DOMAIN=%s\nPOSTGRES_PASSWORD=%s\nINITIAL_GROUP_IDS=474999\n' \
  "$app_domain" "$postgres_password" > "$env_file"
printf '%s' "$bot_token" > "$secrets_dir/telegram_bot_token.txt"
printf '%s' "$webhook_secret" > "$secrets_dir/telegram_webhook_secret.txt"
printf '%s' "$token_signing_key" > "$secrets_dir/token_signing_key.txt"
printf '%s' "$mail_credentials_key" > "$secrets_dir/mail_credentials_key.txt"
bot_token=''

chmod 700 "$secrets_dir"
chmod 600 "$env_file" "$secrets_dir"/*.txt
if [ "$(id -u)" -eq 0 ]; then
  chown 0:0 "$secrets_dir" "$env_file"
  chown 100:101 "$secrets_dir"/*.txt
fi

printf 'Готово. Секреты записаны локально и не выводились на экран.\n'
