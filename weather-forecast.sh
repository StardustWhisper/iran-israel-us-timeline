#!/usr/bin/env bash
set -euo pipefail

# Simple daily weather forecast output for cron logs
# Location can be overridden: WEATHER_LOCATION="Shanghai"
LOCATION="${WEATHER_LOCATION:-Shanghai}"

TS="$(date '+%F %T %Z')"
echo "[$TS] Weather forecast for ${LOCATION}"

# wttr.in returns plaintext by default in this format
# format: condition, temp, feels-like, humidity, wind
curl -fsSL "https://wttr.in/${LOCATION}?format=3"
