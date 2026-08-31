#!/bin/bash

WEBHOOK_URL="ТВОЙ_DISCORD_WEBHOOK_URL"

# Читаем лог в реальном времени и ловим только ошибки и предупреждения
tail -F /var/log/asterisk/messages | grep --line-buffered -E "ERROR|WARNING" | while read -r line ; do
    # Экранируем кавычки для JSON
    clean_line=$(echo "$line" | sed 's/"/\\"/g')

    # Формируем JSON payload
    json_payload="{\"content\": \"⚠️ **Asterisk Alert:** \`$clean_line\`\"}"

    # Отправляем в Discord
    curl -s -H "Content-Type: application/json" -X POST -d "$json_payload" $WEBHOOK_URL
done