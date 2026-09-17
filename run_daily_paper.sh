#!/bin/bash
# Daily advance of the paper account. Run after the TWSE close (13:30 Taipei);
# margin balances post later in the evening, so 20:00 is the safe slot.
#
# Order of operations mirrors reality: pull today's session -> fill yesterday's
# staged orders at today's open -> mark to market -> run the daily derisk checks
# -> (Fridays) rebalance -> stage tomorrow's orders.
#
# Fails CLOSED: if the PC bridge is down or the data looks short, it exits without
# touching paper_state.json or republishing. A stale-but-correct account beats one
# advanced on partial data.
set -uo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/bin

# Host paths and the publish target live in config.sh (gitignored) -- see
# config.example.sh. Defaults below keep the script runnable without one.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$HERE"
[ -f "$HERE/config.sh" ] && . "$HERE/config.sh"
DIR="${DIR:-$HERE}"
PC="${PC:-$HERE/../../.claude/skills/pc-operation/pc.py}"
LOG="$DIR/paper.log"
cd "$DIR" || exit 1
say(){ echo "[$(date '+%Y-%m-%d %H:%M')] $*" >> "$LOG"; }
say "===== daily paper run ====="

timeout 60 python3 "$PC" health >/dev/null 2>&1 || { say "ABORT: PC bridge down"; exit 1; }

TODAY=$(date +%Y%m%d)
timeout 900 python3 "$PC" exec "
import urllib.request,json,ssl,gzip,os,time
CTX=ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
F={'mi_index':'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json',
   't86':'https://www.twse.com.tw/rwd/zh/fund/T86?date={d}&selectType=ALLBUT0999&response=json',
   'margin':'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={d}&selectType=ALL&response=json'}
ds='$TODAY'
for n,t in F.items():
    p=r'C:\myclaw_tw\raw\%s_%s.json.gz'%(n,ds)
    if os.path.exists(p): continue
    try:
        r=urllib.request.urlopen(urllib.request.Request(t.format(d=ds),headers=UA),timeout=70,context=CTX)
        j=json.loads(r.read().decode('utf-8'))
        if j.get('stat')=='OK':
            gzip.open(p,'wt',encoding='utf-8').write(json.dumps(j,ensure_ascii=False))
            print(n,'saved')
        else: print(n,'no data (holiday / not yet published)')
    except Exception as e: print(n,'FAIL',type(e).__name__)
    time.sleep(3)
" >> "$LOG" 2>&1

# copy back only the new files, then rebuild
timeout 600 python3 "$PC" exec "
import zipfile,glob,os
fs=[f for f in glob.glob(r'C:\myclaw_tw\raw\*_$TODAY.json.gz')]
with zipfile.ZipFile(r'C:\myclaw_tw\today.zip','w',zipfile.ZIP_STORED) as z:
    for f in fs: z.write(f,os.path.basename(f))
print('zipped',len(fs))" >> "$LOG" 2>&1
timeout 600 python3 "$PC" download "C:\\myclaw_tw\\today.zip" "$DIR/today.zip" >> "$LOG" 2>&1 \
  && unzip -oq "$DIR/today.zip" -d "$DIR/raw"
timeout 600 python3 "$PC" exec "
import subprocess,sys
subprocess.run([sys.executable, r'C:\myclaw_tw\fetch_news_pc.py'],capture_output=True,timeout=280)
print('news refreshed')" >> "$LOG" 2>&1
timeout 300 python3 "$PC" download "C:\\myclaw_tw\\news.json.gz" "$DIR/news.json.gz" >> "$LOG" 2>&1

# 集保股權分散表. FAIL-OPEN on purpose -- it is display-only, so a TDCC outage must
# never stop the account advancing. Runs daily although the data is weekly: the feed
# serves only the newest snapshot with no history endpoint, so a missed week is gone
# for good, and five consecutive failures would be needed to actually lose one.
# Writes to tdcc.db, NOT twstock.db -- the latter is recreated from scratch below.
timeout 600 python3 tdcc.py fetch >> "$LOG" 2>&1 || say "WARN: tdcc fetch failed (display-only, continuing)"

python3 build_db.py raw twstock_new.db >> "$LOG" 2>&1 || { say "ABORT: build_db failed"; exit 1; }
NP=$(python3 -c "import sqlite3;print(sqlite3.connect('twstock_new.db').execute('select count(*) from price').fetchone()[0])")
[ "$NP" -lt 500000 ] && { say "ABORT: only $NP price rows"; exit 1; }
mv twstock_new.db twstock.db

# Look-ahead sentinel. Self-skips unless strategy.py changed or it is Friday, so
# the cost is only paid when it can actually tell us something. A FAIL means the
# honest backtest drifted toward a known-cheating variant -> the rules started
# reading the future. Do not advance or publish on a leaky engine.
python3 sentinel.py >> "$LOG" 2>&1
SENT=$?
if [ "$SENT" -ne 0 ]; then
  say "ABORT: LOOK-AHEAD SENTINEL FAILED - engine may be reading future data."
  say "       see sentinel_last.json; account NOT advanced, dashboard NOT republished."
  exit 1
fi

python3 paper.py step        >> "$LOG" 2>&1 || { say "ABORT: step failed"; exit 1; }
# advance the passive 0050 CORE sleeve too (new NT$1M large-cap allocation, Sam 2026-08-31)
python3 merge_report.py step-core >> "$LOG" 2>&1 || { say "WARN: core step-core failed"; }
# merged two-sleeve report (active + core, TWR contribution accounting)
python3 merge_report.py report --news news.json.gz --out paper_result.json >> "$LOG" 2>&1 || exit 1
python3 make_dashboard.py --data paper_result.json --out paper_dashboard.html >> "$LOG" 2>&1 || exit 1

if declare -F publish >/dev/null; then
  say "updated: $(publish "$DIR/paper_dashboard.html" "paper $(date +%F)" "${PAPER_URL:-}")"
else
  say "dashboard written to $DIR/paper_dashboard.html (no publish target configured)"
fi
python3 paper.py orders >> "$LOG" 2>&1
say "===== done ====="
