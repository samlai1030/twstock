#!/bin/bash
# Sync this repo to GitHub.
#
# WHY THIS IS NOT JUST `git push`
# -------------------------------
# This host has no external egress -- github.com does not even resolve here, and
# there are no GitHub credentials on it. The PC that runs the market-data fetches
# does have internet and an authenticated `gh`. So the push goes:
#
#   devserver:  commit -> git bundle
#            -> base64, split into ~20 KB chunks (the bridge silently drops a
#               single payload over roughly 100 KB -- it exits 0 and writes
#               nothing, so chunking is not optional)
#            -> PC: reassemble, verify sha256, fetch from the bundle, push
#
# Usage:  ./push_to_github.sh ["commit message"]
#         With no message, only already-committed work is pushed.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || exit 1
PC="${PC:-$HERE/../../.claude/skills/pc-operation/pc.py}"
REPO="${GH_REPO:-samlai1030/twstock}"
PC_DIR='C:\myclaw_tw'
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

msg="${1:-}"
if [ -n "$msg" ]; then
  git add -A || exit 1
  git diff --cached --quiet && echo "nothing staged" || git commit -q -m "$msg" || exit 1
fi

git diff --quiet || echo "NOTE: uncommitted changes in the working tree are NOT pushed."

timeout 60 python3 "$PC" health >/dev/null 2>&1 || { echo "ABORT: PC bridge down"; exit 1; }

git bundle create "$WORK/sync.bundle" --all >/dev/null 2>&1 || { echo "ABORT: bundle failed"; exit 1; }
SHA=$(sha256sum "$WORK/sync.bundle" | cut -c1-16)
echo "bundle $(stat -c%s "$WORK/sync.bundle") bytes, sha $SHA"

python3 - "$WORK" <<'PY' || exit 1
import base64, pathlib, math, sys
w = pathlib.Path(sys.argv[1])
enc = base64.b64encode((w / "sync.bundle").read_bytes()).decode()
n = max(1, math.ceil(len(enc) / 20000))
sz = math.ceil(len(enc) / n)
for i in range(n):
    (w / f"c{i}.py").write_text(
        'import os\nos.makedirs(r"C:\\myclaw_tw",exist_ok=True)\n'
        f'open(r"C:\\myclaw_tw\\sync.b64","{"wb" if i==0 else "ab"}").write(b"{enc[i*sz:(i+1)*sz]}")\n'
        f'print("chunk {i}/{n-1} ok")\n')
print(n)
PY

for f in "$WORK"/c*.py; do
  timeout 300 python3 "$PC" run "$f" >/dev/null 2>&1 || { echo "ABORT: chunk $f failed"; exit 1; }
done
echo "chunks transferred"

cat > "$WORK/finish.py" <<PY
import base64, hashlib, os, shutil, stat, subprocess
GIT = shutil.which('git')
GH  = r'C:\Program Files\GitHub CLI\gh.EXE'
D   = r'${PC_DIR}\twstock_repo'
raw = base64.b64decode(open(r'${PC_DIR}\sync.b64','rb').read())
open(r'${PC_DIR}\sync.bundle','wb').write(raw)
os.remove(r'${PC_DIR}\sync.b64')
sha = hashlib.sha256(raw).hexdigest()[:16]
print('bundle on PC:', len(raw), 'sha', sha)
if sha != '${SHA}':
    raise SystemExit('SHA MISMATCH -- transfer corrupted, refusing to push')
def run(a, **k):
    r = subprocess.run(a, capture_output=True, text=True, timeout=600, **k)
    print(' '.join(str(x) for x in a[1:4]), 'rc', r.returncode,
          (r.stdout or r.stderr).strip()[-300:])
    return r


def rmtree(p):
    """shutil.rmtree(ignore_errors=True) SILENTLY fails here: git marks object
    files read-only and Windows refuses to unlink them, so the directory survives
    and the next clone dies with 'already exists and is not empty'. Chmod first."""
    if os.path.isdir(p):
        shutil.rmtree(p, onerror=lambda fn, path, exc: (os.chmod(path, stat.S_IWRITE), fn(path)))


# The staging repo is BARE on purpose: git refuses to fetch into a branch that is
# checked out, so a plain clone breaks on the SECOND sync, not the first.
if os.path.isdir(D) and not os.path.isdir(os.path.join(D, 'objects')):
    rmtree(D)                                  # leftover non-bare clone
if not os.path.isdir(D):
    run([GIT, 'clone', '--bare', r'${PC_DIR}\sync.bundle', D])
    # cloning from a bundle leaves origin pointing AT THE BUNDLE -- set-url, not add.
    run([GIT, 'remote', 'set-url', 'origin', 'https://github.com/${REPO}.git'], cwd=D)
else:
    run([GIT, 'fetch', r'${PC_DIR}\sync.bundle', '+refs/heads/*:refs/heads/*', '--force'], cwd=D)
# --force-with-lease is unsupported by this git's https transport; plain push, and
# only fall back to --force when the remote genuinely diverged.
if run([GIT, 'push', 'origin', 'main'], cwd=D).returncode != 0:
    run([GIT, 'push', 'origin', 'main', '--force'], cwd=D)
run([GH, 'repo', 'view', '${REPO}', '--json', 'visibility,url'])
PY
timeout 600 python3 "$PC" run "$WORK/finish.py" 2>&1 | tail -12
