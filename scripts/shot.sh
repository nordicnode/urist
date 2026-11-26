#!/bin/bash
DISPLAY=:99 xwd -root -silent -out /tmp/shot.xwd && convert /tmp/shot.xwd "$1"
