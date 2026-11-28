#!/usr/bin/env bash
# Publish audit data to the isolated research branch. Charts remain in the run artifact.
set -eu -o pipefail
branch=research/annual-backtest-runner
test "${GITHUB_REF_NAME:?}" = "$branch"
revision=${GITHUB_SHA:?}
repo_url="https://github.com/${GITHUB_REPOSITORY:?}"
out="$PWD/research-output"
dest=${RUNNER_TEMP:?}/research-result-tree
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git worktree add --detach "$dest" "$revision"
for attempt in 1 2 3; do
    git fetch --no-tags origin "refs/heads/$branch"
    head=$(git rev-parse FETCH_HEAD)
    git -C "$dest" checkout --detach --force "$head"
    dir="$dest/research/results/$revision"
    mkdir -p "$dir"
    cp "$out"/{summary.json,trades.csv,rejections.csv,entry-evidence.json,equity.csv} "$dir/"
    if [ -f "$out/validation.json" ]; then cp "$out/validation.json" "$dir/"; fi
    if git diff --quiet "$revision" "$head" -- research/runner research/baseline src/binance_vision_archive.py src/binance_futures_candles.py tests/test_research_runner.py .github/workflows/annual-backtest-runner.yml; then
        python - "$dest/research/results/latest.json" "$revision" "$repo_url/actions/runs/$GITHUB_RUN_ID" <<'PY'
import json,sys
from pathlib import Path
path,rev,url=sys.argv[1:]
Path(path).write_text(json.dumps(dict(input_commit=rev,summary=f"research/results/{rev}/summary.json",run_url=url),indent=2)+"\n")
PY
    fi
    git -C "$dest" add research/results
    if git -C "$dest" diff --cached --quiet; then exit 0; fi
    git -C "$dest" commit -m "research: record verified replay for ${revision:0:12}"
    if git -C "$dest" push origin "HEAD:refs/heads/$branch"; then exit 0; fi
done
echo "Research result push failed after three attempts; see run artifact." >&2
exit 1
