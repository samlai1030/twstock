# Site-specific configuration for run_daily_paper.sh / run_weekly.sh.
#
# Copy to `config.sh` (which is gitignored) and edit. Everything here is about
# WHERE this particular installation lives and WHERE it publishes -- none of it is
# strategy logic, so none of it belongs in version control.
#
#   cp config.example.sh config.sh

# Project directory. Defaults to the directory the script itself lives in, which is
# usually right; set it explicitly only if you run the scripts from a symlink.
# DIR="/path/to/twstock"

# Path to the PC-operation bridge (pc.py). This host has no external egress, so every
# TWSE / TDCC / RSS fetch is executed on a Windows box that does. Without this the
# scripts cannot pull market data at all.
PC="${PC:-$DIR/../../.claude/skills/pc-operation/pc.py}"

# publish <html-file> <description>
#
# Called after each dashboard build. Leave it undefined and the scripts just log
# "no publish target configured" and carry on -- the HTML is still written to disk,
# which is all a local user needs.
#
# The reference installation updates one long-lived internal post in place so the URL
# stays stable day to day, instead of minting a new link every run. Swap in whatever
# your host needs: scp, `gh release upload`, netlify deploy, or plain `cp` to a
# web root.
#
# publish(){
#   local file="$1" desc="$2"
#   cp "$file" /var/www/html/twstock/"$(basename "$file")"
# }

# Which dashboard each script updates, if `publish` reads these.
# PAPER_URL="https://example.invalid/paper-dashboard"
# BT_URL="https://example.invalid/backtest-dashboard"
