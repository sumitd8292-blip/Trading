"""
auto_sync_data.py — pushes VPS-generated data to GitHub automatically
------------------------------------------------------------------------------
21 Aug 2026: Saim's explicit request — he shouldn't have to copy-paste
large data dumps back to Claude (burns session length, forces waiting
for the next day). Solution: the VPS commits and pushes its own
generated data files (memory/*.jsonl trackers, paper trades, learning
logs) to the SAME GitHub repo Claude already reads code from — so
Claude can just `git pull` in a fresh session and directly inspect
real, current data. No manual copy-paste needed, ever, going forward.

Does NOT push credentials/secrets (those stay in the systemd service
file, never in git). Only pushes the memory/ and data/ directories'
JSON/JSONL content — the accumulated learning/tracking data itself.

Run manually: python3 auto_sync_data.py
Or call sync_data_to_github() from continuous_runner.py at EOD.
"""
import subprocess
import os
from datetime import datetime

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def sync_data_to_github():
    """
    Stages any changes in memory/ and data/ directories, commits, and
    pushes to origin/main. Safe to call repeatedly — if there's nothing
    new to commit, it's a no-op. Uses the git identity/remote already
    configured on the VPS (assumes persistent push credentials are set
    up via setup_git_push_credentials() below, run once).
    """
    try:
        subprocess.run(["git", "add", "memory/", "data/"], cwd=REPO_DIR, check=True, capture_output=True)

        status = subprocess.run(["git", "status", "--porcelain", "memory/", "data/"],
                                 cwd=REPO_DIR, capture_output=True, text=True)
        if not status.stdout.strip():
            return {"status": "no_changes"}

        commit_msg = f"Auto-sync VPS data — {datetime.now().isoformat()}"
        subprocess.run(["git", "-c", "user.email=agent@local", "-c", "user.name=OrderFlowAgent",
                         "commit", "-m", commit_msg], cwd=REPO_DIR, check=True, capture_output=True)

        # Pull first in case Claude pushed code changes in between (avoid conflicts)
        subprocess.run(["git", "pull", "origin", "main", "--no-edit"], cwd=REPO_DIR, capture_output=True)

        push_result = subprocess.run(["git", "push", "origin", "main"], cwd=REPO_DIR,
                                      capture_output=True, text=True)
        if push_result.returncode != 0:
            return {"status": "push_failed", "error": push_result.stderr}

        return {"status": "synced", "commit_message": commit_msg}
    except subprocess.CalledProcessError as e:
        return {"status": "error", "error": str(e), "stderr": e.stderr.decode() if e.stderr else None}


def setup_git_push_credentials(github_username, github_pat):
    """
    Run ONCE on the VPS to configure PERSISTENT git push credentials
    (unlike Claude's manual sessions, which temporarily embed the PAT
    then revert it — the VPS needs this to work autonomously,
    unattended, every time continuous_runner.py calls sync_data_to_github()).

    SECURITY NOTE: this embeds the PAT in the git remote URL on the VPS
    specifically (a private server Saim controls) — NOT in any file
    that gets committed to the repo itself. Standard practice for
    server-side automated git push.
    """
    remote_url = f"https://{github_username}:{github_pat}@github.com/{github_username}/Trading.git"
    subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=REPO_DIR, check=True)
    return {"status": "credentials_configured"}


if __name__ == "__main__":
    result = sync_data_to_github()
    print(result)
