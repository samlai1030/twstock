#!/bin/bash
# Weekly refresh of the Taiwan-stock strategy dashboard.
#
# The devserver has no external egress, so the market pull runs on Sam's PC via
# the pc-operation bridge and the results are copied back here. If the PC is off
# this exits non-zero WITHOUT touching the published dashboard -- stale-but-correct
# beats fresh-but-partial (the CMT dashboard outage taught us that one).
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin

# Host paths and the publish target live in config.sh (gitignored) -- see
# config.example.sh. Defaults below keep the script runnable without one.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HERE"
[ -f "$HERE/config.sh" ] && . "$HERE/config.sh"
DIR="${DIR:-$HERE}"
PC="${PC:-$HERE/../../.claude/skills/pc-operation/pc.py}"
LOG="$DIR/weekly.log"
cd "$DIR" || exit 1

say(){ echo "[$(date '+%Y-%m-%d %H:%M')] $*" >> "$LOG"; }
say "===== weekly run start ====="

if ! timeout 60 python3 "$PC" health >/dev/null 2>&1; then
  say "ABORT: PC bridge down -- dashboard left untouched"; exit 1
fi

# 1. incremental market pull (script skips dates already on disk)
timeout 5400 python3 "$PC" exec "
import subprocess,sys
r=subprocess.run([sys.executable, r'C:\myclaw_tw\fetch_pc.py'],capture_output=True,text=True,timeout=5100)
print('fetch rc',r.returncode)
" >> "$LOG" 2>&1
timeout 600 python3 "$PC" exec "
import subprocess,sys
for s in ['fetch_extra_pc.py','fetch_news_pc.py']:
    r=subprocess.run([sys.executable, r'C:\myclaw_tw\\'+s],capture_output=True,text=True,timeout=280)
    print(s,'rc',r.returncode)
" >> "$LOG" 2>&1

# 2. bundle + copy back
timeout 600 python3 "$PC" exec "
import zipfile,glob,os
fs=glob.glob(r'C:\myclaw_tw\raw\*.json.gz')
with zipfile.ZipFile(r'C:\myclaw_tw\raw_all.zip','w',zipfile.ZIP_STORED) as z:
    for f in fs: z.write(f,os.path.basename(f))
print('zipped',len(fs))
" >> "$LOG" 2>&1
timeout 900 python3 "$PC" download "C:\\myclaw_tw\\raw_all.zip" "$DIR/raw_all.zip" >> "$LOG" 2>&1 || { say "ABORT: download failed"; exit 1; }
timeout 600 python3 "$PC" download "C:\\myclaw_tw\\news.json.gz" "$DIR/news.json.gz" >> "$LOG" 2>&1

unzip -oq "$DIR/raw_all.zip" -d "$DIR/raw" || { say "ABORT: unzip failed"; exit 1; }
NFILE=$(ls "$DIR/raw" | wc -l)
say "raw files: $NFILE"

# 3. rebuild + backtest + dashboard, into temp names first
python3 build_db.py raw twstock_new.db >> "$LOG" 2>&1 || { say "ABORT: build_db failed"; exit 1; }
NPRICE=$(python3 -c "import sqlite3;print(sqlite3.connect('twstock_new.db').execute('select count(*) from price').fetchone()[0])")
if [ "$NPRICE" -lt 100000 ]; then say "ABORT: only $NPRICE price rows, refusing to publish"; exit 1; fi
mv twstock_new.db twstock.db

END=$(python3 -c "import sqlite3;print(sqlite3.connect('twstock.db').execute('select max(date) from price').fetchone()[0])")
START=$(python3 -c "
import datetime as d;print((d.date.fromisoformat('$END')-d.timedelta(days=365)).isoformat())")
say "backtest window $START -> $END"

python3 report.py --db twstock.db --start "$START" --end "$END" \
   --news news.json.gz --holdings holdings.json --json-out result.json >> "$LOG" 2>&1 \
   || { say "ABORT: report failed"; exit 1; }
python3 make_dashboard.py --data result.json --out tw_dashboard.html >> "$LOG" 2>&1 \
   || { say "ABORT: dashboard build failed"; exit 1; }

# 4. publish -- update the SAME post in place (stable URL), don't mint a new one each week
if declare -F publish >/dev/null; then
  say "publish: $(publish "$DIR/tw_dashboard.html" "weekly $(date +%F)" "${BT_URL:-}")"
else
  say "dashboard written to $DIR/tw_dashboard.html (no publish target configured)"
fi
say "===== weekly run done ====="
