#!/usr/bin/env bash
set -euo pipefail

wifi=wlan0
hotspot=${ORANGEPI_HOTSPOT_PROFILE:?Set ORANGEPI_HOTSPOT_PROFILE to the board hotspot profile name}
nm=org.freedesktop.NetworkManager
nm_path=/org/freedesktop/NetworkManager
rollback_seconds=180
radio_disabled=no

nm_call() {
    busctl --timeout=6s call "$nm" "$nm_path" "$nm" "$@"
}

wifi_profile() {
    nmcli -t -f UUID,DEVICE connection show --active |
        awk -F: -v wifi="$wifi" '$2 == wifi {print $1; exit}'
}

wifi_connected() {
    [[ "$(wifi_profile)" == "$1" && "$(nmcli -g GENERAL.STATE device show "$wifi")" == '100 '* ]] &&
        iw dev "$wifi" link | grep -q '^Connected to '
}

wait_for_wifi() {
    local profile=$1 deadline=$((SECONDS + $2))
    until wifi_connected "$profile"; do
        if (( SECONDS >= deadline )); then return 1; fi
        sleep 2
    done
}

checkpoint_directory() {
    [[ "$1" =~ ^/org/freedesktop/NetworkManager/Checkpoint/[0-9]+$ ]] || return 1
    printf '%s/orangepi-camera-network-%s\n' "${XDG_RUNTIME_DIR:?}" "${1##*/}"
}

start_hotspot() {
    local profile device checkpoint directory
    profile=$(wifi_profile)
    if [[ -z "$profile" ]] || ! wifi_connected "$profile"; then
        echo 'A connected Wi-Fi client profile is required' >&2
        return 1
    fi
    if [[ "$(loginctl show-user "$(id -u)" -p Linger --value)" != yes ]]; then
        echo 'Enable lingering for the Orange Pi user before switching Wi-Fi' >&2
        return 1
    fi

    device=$(nmcli -g GENERAL.DBUS-PATH device show "$wifi")
    checkpoint=$(nm_call CheckpointCreate aouu 1 "$device" "$rollback_seconds" 0 | cut -d'"' -f2)
    directory=$(checkpoint_directory "$checkpoint")
    if ! mkdir -m 700 -- "$directory"; then
        nm_call CheckpointDestroy o "$checkpoint" >/dev/null
        return 1
    fi
    if ! systemd-run --user --on-active=3s --collect \
        --unit="orangepi-camera-network-${checkpoint##*/}" --property=RuntimeMaxSec=335s \
        --setenv="ORANGEPI_HOTSPOT_PROFILE=$hotspot" \
        /bin/bash "$0" monitor "$checkpoint" "$profile" >&2; then
        nm_call CheckpointDestroy o "$checkpoint" >/dev/null
        rmdir -- "$directory"
        return 1
    fi
    printf '%s\n' "$checkpoint"
}

confirm_hotspot() {
    local checkpoint=$1 directory
    directory=$(checkpoint_directory "$checkpoint")
    (
        flock -x 9
        nm_call CheckpointDestroy o "$checkpoint" >/dev/null
        touch -- "$directory/confirmed"
    ) 9>"$directory/lock"
}

finish_monitor() {
    if [[ "$radio_disabled" == yes ]]; then
        nmcli -w 6 radio wifi on || true
    fi
    rm -f -- "$monitor_directory/confirmed" "$monitor_directory/lock"
    rmdir -- "$monitor_directory"
}

monitor_hotspot() {
    local checkpoint=$1 profile=$2 checkpoints deadline
    monitor_directory=$(checkpoint_directory "$checkpoint")
    trap finish_monitor EXIT
    trap 'exit 143' TERM INT
    printf 'HOTSPOT_SWITCH_START %s\n' "$checkpoint"
    if nmcli -w 30 connection up "$hotspot" ifname "$wifi"; then
        echo HOTSPOT_ACTIVE
    else
        echo HOTSPOT_ACTIVATION_FAILED
        nm_call CheckpointRollback o "$checkpoint" >/dev/null || true
    fi

    deadline=$((SECONDS + rollback_seconds + 10))
    while :; do
        if checkpoints=$(busctl --timeout=5s get-property "$nm" "$nm_path" "$nm" Checkpoints) &&
            [[ "$checkpoints" != *"\"$checkpoint\""* ]]; then
            break
        fi
        if (( SECONDS >= deadline )); then
            echo HOTSPOT_CHECKPOINT_STATUS_TIMEOUT >&2
            return 1
        fi
        sleep 2
    done
    (
        flock -x 9
        [[ -e "$monitor_directory/confirmed" ]]
    ) 9>"$monitor_directory/lock" && { echo HOTSPOT_CONFIRMED; return 0; }

    echo HOTSPOT_ROLLED_BACK
    if wait_for_wifi "$profile" 60; then
        echo WIFI_RECONNECTED_WITHOUT_RESET
        return 0
    fi

    echo WIFI_RADIO_RESET
    radio_disabled=yes
    nmcli -w 6 radio wifi off
    sleep 4
    nmcli -w 6 radio wifi on
    radio_disabled=no
    if wait_for_wifi "$profile" 12 ||
        { nmcli -w 30 connection up uuid "$profile" ifname "$wifi" && wait_for_wifi "$profile" 10; }; then
        echo WIFI_RECONNECTED_AFTER_RESET
        return 0
    fi
    echo WIFI_RECONNECT_FAILED >&2
    return 1
}

case "${1:-}" in
    start) start_hotspot ;;
    monitor) monitor_hotspot "$2" "$3" ;;
    confirm) confirm_hotspot "$2" ;;
    *) exit 2 ;;
esac
