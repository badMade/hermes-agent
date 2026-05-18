#!/bin/sh
git log -3 --oneline 2>/dev/null > /tmp/git_log.txt
cat /tmp/git_log.txt
