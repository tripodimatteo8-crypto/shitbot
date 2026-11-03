#!/usr/bin/env bash
# Installa SolBot come servizio launchd dell'utente: parte al login e si riavvia dopo crash.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.solbot.agent"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$HOME/Library/LaunchAgents" logs
chmod +x scripts/start.sh

sed -e "s#__ROOT__#$ROOT#g" scripts/com.solbot.agent.plist.template > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

echo "Servizio installato: $PLIST"
echo "Log: $ROOT/logs/launchd.out.log e $ROOT/logs/solbot.log"
echo "Stato:   launchctl print gui/$(id -u)/$LABEL | head -20"
echo "Stop:    launchctl bootout gui/$(id -u)/$LABEL"
