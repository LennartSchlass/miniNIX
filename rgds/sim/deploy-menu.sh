#!/bin/bash
# Copies the DS menu to the RG DS and runs it there in place of EmulationStation, without
# rebuilding the image. A reboot restores the installed UI.
# usage: deploy-menu.sh <host> [start|stop|log]
set -e
cd "$(dirname "$0")/../../projects/ROCKNIX/packages/ui/nds-menu/sources"
H=root@${1:?host}
case "${2:-start}" in
  start)
    ssh -o BatchMode=yes "$H" 'mkdir -p /storage/nds-menu'
    scp -q -o BatchMode=yes -r main.py sdl2.py fonts "$H:/storage/nds-menu/"
    ssh -o BatchMode=yes "$H" '. /etc/profile; export SWAYSOCK=/var/run/0-runtime-dir/sway-ipc.0.sock;
      systemctl stop essway; pkill -f "[p]ython3 /storage/nds-menu/main.py" || true; sleep 1; cd /storage;
      setsid nohup python3 /storage/nds-menu/main.py >/storage/nds-menu.log 2>&1 </dev/null & sleep 3;
      swaymsg -t get_tree | jq -r ".. | objects | select(.app_id? == \"ndsmenu\") | \"ndsmenu window: \(.type) \(.rect.x),\(.rect.y) \(.rect.width)x\(.rect.height) fullscreen=\(.fullscreen_mode)\"";
      tail -5 /storage/nds-menu.log'
    ;;
  stop)
    ssh -o BatchMode=yes "$H" 'pkill -f "[p]ython3 /storage/nds-menu/main.py" || true; systemctl start essway'
    ;;
  log)
    ssh -o BatchMode=yes "$H" 'tail -40 /storage/nds-menu.log'
    ;;
esac
