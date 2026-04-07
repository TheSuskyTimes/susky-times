#!/usr/bin/env python3
"""
The Susky Times — Daily Publishing Script
==========================================
Run by the scheduled task every morning at 7 AM.
Searches for today's news, generates the digest, and pushes to GitHub.

Requirements (install once):
  pip install requests python-dotenv
"""

import os, json, base64, re, datetime, requests
from pathlib import Path

# ── CONFIG ──────────────────────────────────────────────────────────────────
GITHUB_OWNER   = "TheSuskyTimes"
GITHUB_REPO    = "susky-times"
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")   # set in env or .env file
BRANCH         = "main"

# ── HELPERS ─────────────────────────────────────────────────────────────────

def gh_api(method, path, data=None):
    """GitHub API wrapper."""
    r = requests.request(
        method,
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}{path}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json=data,
    )
    r.raise_for_status()
    return r.json()

def get_file_sha(filepath):
    """Get the current SHA of a file (needed to update it)."""
    try:
        data = gh_api("GET", f"/contents/{filepath}")
        return data["sha"]
    except Exception:
        return None

def push_file(filepath, content_str, commit_msg):
    """Create or update a file on GitHub."""
    encoded = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    sha = get_file_sha(filepath)
    payload = {
        "message": commit_msg,
        "content": encoded,
        "branch": BRANCH,
    }
    if sha:
        payload["sha"] = sha
    return gh_api("PUT", f"/contents/{filepath}", payload)


# ── MAIN PUBLISH FUNCTION ────────────────────────────────────────────────────

def publish_issue(issue_data: dict):
    """
    issue_data keys:
      date_str        – "Tuesday, April 8, 2026"
      date_file       – "2026-04-08"
      issue_num       – 1
      top_headline    – str
      top_body        – [str, str, str]   (3 paragraphs)
      top_link        – str (URL)
      top_kicker      – str
      hits            – list of dicts: {emoji, title, body, tag}
      campus_headline – str
      campus_body     – str
      career_headline – str
      career_body     – str
      startup_headline– str
      startup_body    – str
      startup_link    – str
      term_word       – str
      term_def        – str
      term_example    – str
      poll_question   – str
      poll_options    – list of 4 strings
      poll_votes_init – list of 4 ints  (seed so not blank)
      closer_stat     – str
      closer_context  – str
      sp500           – {val, chg, up}
      nasdaq          – {val, chg, up}
      dow             – {val, chg, up}
      sub_count       – int
    """

    html = build_html(issue_data)
    date_file = issue_data["date_file"]
    issue_num = issue_data["issue_num"]

    # 1) Push today's issue as issues/YYYY-MM-DD.html
    push_file(
        f"issues/{date_file}.html",
        html,
        f"📰 Issue #{issue_num}: {issue_data['top_headline'][:60]}"
    )

    # 2) Update index.html (today's main page)
    push_file("index.html", html, f"🔄 Update index.html for {date_file}")

    # 3) Update archive.html
    update_archive(issue_data)

    print(f"✅ Published Issue #{issue_num} for {date_file}")


def update_archive(d):
    """Prepend a new entry to the archive page."""
    try:
        raw = gh_api("GET", "/contents/archive.html")
        current = base64.b64decode(raw["content"]).decode("utf-8")
    except Exception:
        return  # archive.html doesn't exist yet

    tags = extract_tags(d)
    tag_html = "".join(f'<span class="tag">{t}</span>' for t in tags)

    new_entry = f"""
    <div class="issue-card" onclick="window.location.href='issues/{d['date_file']}.html'">
      <div class="issue-number">#{d['issue_num']}</div>
      <div class="issue-meta">
        <div class="date">{d['date_str']}</div>
        <div class="headline">{d['top_headline']}</div>
        <div class="preview">{d['hits'][0]['title'][:80]}...</div>
        <div class="tags">{tag_html}</div>
      </div>
    </div>"""

    updated = current.replace(
        "<!-- ARCHIVE_ENTRIES_START -->",
        f"<!-- ARCHIVE_ENTRIES_START -->\n{new_entry}"
    )
    push_file("archive.html", updated, f"📚 Archive: add issue #{d['issue_num']}")


def extract_tags(d):
    tags = []
    for hit in d.get("hits", [])[:3]:
        t = hit.get("tag", "")
        if t: tags.append(t.split("&")[0].strip()[:20])
    return tags[:4]


def build_html(d):
    """Read the template and inject today's content."""
    # Read the base template
    template_path = Path(__file__).parent / "index_template.html"
    if not template_path.exists():
        raise FileNotFoundError("index_template.html not found. Run setup first.")

    html = template_path.read_text(encoding="utf-8")

    # Market data
    for key, idx_key in [("sp500", "sp500"), ("nasdaq", "nasdaq"), ("dow", "dow")]:
        m = d[key]
        direction = "up" if m["up"] else "down"
        arrow = "▲" if m["up"] else "▼"
        sign = "+" if m["up"] else "−"
        html = html.replace(f'id="{idx_key}-val">{d[key]["val_placeholder"]}<',
                            f'id="{idx_key}-val">{m["val"]}<')
        html = html.replace(f'id="{idx_key}-chg" class="change up"',
                            f'id="{idx_key}-chg" class="change {direction}"')

    # Use simple token replacement on content sections
    replacements = {
        'id="top-story-headline">': f'id="top-story-headline">{d["top_headline"]}<',
        'id="top-story-body-1">':   f'id="top-story-body-1">{d["top_body"][0]}<',
        'id="top-story-body-2">':   f'id="top-story-body-2">{d["top_body"][1]}<',
        'id="top-story-body-3">':   f'id="top-story-body-3">{d["top_body"][2]}<',
        'id="campus-headline">':    f'id="campus-headline">{d["campus_headline"]}<',
        'id="campus-body">':        f'id="campus-body">{d["campus_body"]}<',
        'id="career-headline">':    f'id="career-headline">{d["career_headline"]}<',
        'id="career-body">':        f'id="career-body">{d["career_body"]}<',
        'id="startup-headline">':   f'id="startup-headline">{d["startup_headline"]}<',
        'id="startup-body">':       f'id="startup-body">{d["startup_body"]}<',
        'id="term-word">':          f'id="term-word">{d["term_word"]}<',
        'id="term-def">':           f'id="term-def">{d["term_def"]}<',
        'id="term-example">':       f'id="term-example">{d["term_example"]}<',
        'id="closer-stat">':        f'id="closer-stat">{d["closer_stat"]}<',
        'id="closer-context">':     f'id="closer-context">{d["closer_context"]}<',
        'id="poll-question">':      f'id="poll-question">{d["poll_question"]}<',
        'id="sub-count">':          f'id="sub-count">{d["sub_count"]} subscribers<',
    }

    # Build hits HTML
    hits_html = ""
    for h in d["hits"]:
        hits_html += f"""
      <div class="hit">
        <div class="hit-emoji">{h['emoji']}</div>
        <div class="hit-body">
          <strong>{h['title']}</strong>
          <p>{h['body']}</p>
          <span class="tag">{h['tag']}</span>
        </div>
      </div>"""
    html = re.sub(
        r'<div class="quick-hits" id="hits-container">.*?</div>\s*</div>',
        f'<div class="quick-hits" id="hits-container">{hits_html}\n    </div>\n  </div>',
        html, flags=re.DOTALL
    )

    # Poll options
    for i, opt in enumerate(d["poll_options"]):
        html = html.replace(f'id="opt-{i}">{html_opt_text(html, i)}<', f'id="opt-{i}">{opt}<')

    return html


def html_opt_text(html, idx):
    """Extract current option text from HTML for replacement."""
    m = re.search(rf'id="opt-{idx}">([^<]+)<', html)
    return m.group(1) if m else ""


# ── STANDALONE TEST ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    # This is used for testing. The scheduled task calls publish_issue() directly.
    print("Susky Times publisher loaded. Call publish_issue(data) to publish.")
