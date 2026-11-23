#!/usr/bin/env bash
# Keeps the board reachable: if wlan0 stays off the campus network, reset Wi-Fi.
# Verified recovery path: radio off -> 4s -> radio on -> reconnect.
set -u

wifi=wlan0
campus=${ORANGEPI_WIFI_PROFILE:?Set ORANGEPI_WIFI_PROFILE to the board Wi-Fi profile name}
failures=0

log() { logger -t orangepi-wifi-watchdog "$*"; }

campus_connected() {
    [[ "$(nmcli -g GENERAL.CONNECTION device show "$wifi" 2>/dev/null)" == "$campus" ]] &&
        iw dev "$wifi" link 2>/dev/null | grep -q '^Connected to'
}

# Skip while the camera helper owns the radio (hotspot on purpose).
helper_active() {
    pgrep -f 'orangepi-camera-network\.sh' >/dev/null 2>&1 ||
        systemctl is-active --quiet orangepi-camera-network-2.service 2>/dev/null
}

log "watchdog started"

while true; do
    sleep 60

    if ! ip link show "$wifi" >/dev/null 2>&1; then
        failures=0
        continue
    fi
    if helper_active; then
        failures=0
        continue
    fi
    # An intentional hotspot keeps wlan0 in AP mode; never fight it.
    if ! iw dev "$wifi" info 2>/dev/null | grep -q 'type managed'; then
        failures=0
        continue
    fi
    if campus_connected; then
        failures=0
        continue
    fi

    failures=$((failures + 1))
    log "campus link missing (check $failures/2)"
    (( failures < 2 )) && continue

    log "resetting Wi-Fi"
    nmcli radio wifi off >/dev/null 2>&1 || true
    sleep 4
    nmcli radio wifi on >/dev/null 2>&1 || true
    for _ in $(seq 1 12); do
        sleep 3
        campus_connected && break
    done
    if ! campus_connected; then
        nmcli connection up "$campus" ifname "$wifi" >/dev/null 2>&1 || true
        sleep 6
    fi

    if campus_connected; then
        log "recovered by radio reset"
        failures=0
        continue
    fi

    log "radio reset failed; reloading bcmdhd"
    nmcli radio wifi off >/dev/null 2>&1 || true
    rmmod bcmdhd 2>/dev/null || true
    modprobe bcmdhd 2>/dev/null || true
    nmcli radio wifi on >/dev/null 2>&1 || true
    sleep 10
    nmcli connection up "$campus" ifname "$wifi" >/dev/null 2>&1 || true
    sleep 5
    if campus_connected; then
        log "recovered by bcmdhd reload"
    else
        log "campus still unreachable; backing off 5 minutes"
        sleep 300
    fi
    failures=0
done
