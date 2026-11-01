#!/bin/bash
# stop the whole chain (its own process group) if available RAM < 4 GB or a game starts; no retry
G=$1
while kill -0 -- -$G 2>/dev/null; do
  a=$(awk "/MemAvailable/{print int(\$2/1024)}" /proc/meminfo)
  g=$(pgrep -i "^(reaper|wineserver|.*\.exe)$" | head -1)
  if [ "$a" -lt 4096 ] || [ -n "$g" ]; then
    echo "$(date "+%-I:%M %p") STOP avail=${a}MB game=$g group=$G" >> ~/cast-pilot/xray/d4/chain.log
    kill -- -$G; exit
  fi
  sleep 30
done
echo "$(date "+%-I:%M %p") watch: chain ended" >> ~/cast-pilot/xray/d4/chain.log
