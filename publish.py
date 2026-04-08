#!/usr/bin/env python3
"""
The Susky Times — Daily Publishing Script
==========================================
Called by the scheduled task every morning.
Injects today's content into the HTML template, then pushes to GitHub.
Uses only Python stdlib (no third-party packages needed).
"""

import os, json, base64, re
from pathlib import Path
from urllib import request as urlreq, error as urlerr

# ── CONFIG ───────────────────────────────────────────────────────────────────
GITHUB_OWNER  = "TheSuskyTimes"
GITHUB_REPO   = "susky-times"
GITHUB_TOKEN  = os.environ.get("GITHUB_TOKEN", "")
BRANCH        = "main"


# ── GITHUB HELPERS ────────────────────────────────────────────────────────────

def gh_put(api_path, payload_dict):
    """PUT to GitHub API. Returns parsed JSON response."""
    data = json.dumps(payload_dict).encode("utf-8")
    req = urlreq.Request(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}{api_path}",
        data=data,
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="PUT",
    )
    with urlreq.urlopen(req) as resp:
        return json.loads(resp.read().decode())


def gh_get(api_path):
    """GET from GitHub API. Returns parsed JSON or None on 404."""
    req = urlreq.Request(
        f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}{api_path}",
        headers={
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urlreq.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urlerr.HTTPError as e:
        if e.code == 404:
            return None
        raise


def get_sha(filepath):
    data = gh_get(f"/contents/{filepath}")
    return data["sha"] if data else None


def push_file(filepath, content_str, commit_msg):
    """Create or update a file on GitHub."""
    encoded = base64.b64encode(content_str.encode("utf-8")).decode("utf-8")
    payload = {"message": commit_msg, "content": encoded, "branch": BRANCH}
    sha = get_sha(filepath)
    if sha:
        payload["sha"] = sha
    return gh_put(f"/contents/{filepath}", payload)


# ── HTML BUILDER ─────────────────────────────────────────────────────────────

def _replace_between(html, tag_id, new_value):
    """Replace content between id="tag_id"> and the next </ tag."""
    pattern = rf'(id="{re.escape(tag_id)}">)[^<]*(</)'
    return re.sub(pattern, rf'\g<1>{new_value}\2', html, count=1)


def build_html(d):
    """Read index_template.html and inject today's content."""
    template_path = Path(__file__).parent / "index_template.html"
    if not template_path.exists():
        raise FileNotFoundError("index_template.html not found next to publish.py")

    html = template_path.read_text(encoding="utf-8")

    # ── Date / meta ──────────────────────────────────────────────────────────
    html = _replace_between(html, "today-date", d["date_str"])
    # Also update sub-count
    html = _replace_between(html, "sub-count", f'{d["sub_count"]} subscribers')

    # ── Market snapshot ──────────────────────────────────────────────────────
    for key in ("sp500", "nasdaq", "dow"):
        m = d[key]
        direction = "up" if m["up"] else "down"
        # Replace value
        html = re.sub(
            rf'(id="{key}-val">)[^<]*(</)',
            rf'\g<1>{m["val"]}\2', html, count=1
        )
        # Replace change text and class
        html = re.sub(
            rf'(id="{key}-chg" class="change )(up|down)(">[^<]*</)',
            rf'\g<1>{direction}\g<3>', html, count=1
        )
        html = re.sub(
            rf'(id="{key}-chg"[^>]*>)[^<]*(</)',
            rf'\g<1>{m["chg"]}\2', html, count=1
        )

    # ── Top story ────────────────────────────────────────────────────────────
    html = _replace_between(html, "top-story-headline", d["top_headline"])
    html = _replace_between(html, "top-story-body-1",   d["top_body"][0])
    html = _replace_between(html, "top-story-body-2",   d["top_body"][1])
    html = _replace_between(html, "top-story-body-3",   d["top_body"][2])

    # Update the top-story source link href
    if d.get("top_link"):
        html = re.sub(
            r'(id="top-story-link"[^>]*href=")[^"]*(")',
            rf'\g<1>{d["top_link"]}\2', html, count=1
        )

    # ── Quick hits ───────────────────────────────────────────────────────────
    hits_html = ""
    for h in d["hits"]:
        hits_html += f"""
      <div class="hit">
        <div class="hit-icon">{h.get('emoji', '')}</div>
        <div class="hit-body">
          <strong>{h['title']}</strong>
          <p>{h['body']}</p>
          <span class="tag">{h['tag']}</span>
        </div>
      </div>"""
    html = re.sub(
        r'(<div[^>]+id="hits-container"[^>]*>).*?(</div>\s*</div>)',
        rf'\g<1>{hits_html}\n    </div>\n  </div>',
        html, count=1, flags=re.DOTALL
    )

    # ── Campus ───────────────────────────────────────────────────────────────
    html = _replace_between(html, "campus-headline", d["campus_headline"])
    html = _replace_between(html, "campus-body",     d["campus_body"])

    # ── Career corner ────────────────────────────────────────────────────────
    html = _replace_between(html, "career-headline", d["career_headline"])
    html = _replace_between(html, "career-body",     d["career_body"])

    # ── Startup spotlight ─────────────────────────────────────────────────────
    html = _replace_between(html, "startup-headline", d["startup_headline"])
    html = _replace_between(html, "startup-body",     d["startup_body"])
    if d.get("startup_link"):
        html = re.sub(
            r'(id="startup-link"[^>]*href=")[^"]*(")',
            rf'\g<1>{d["startup_link"]}\2', html, count=1
        )

    # ── Term of the day ──────────────────────────────────────────────────────
    html = _replace_between(html, "term-word",    d["term_word"])
    html = _replace_between(html, "term-def",     d["term_def"])
    html = _replace_between(html, "term-example", d["term_example"])

    # ── Poll ─────────────────────────────────────────────────────────────────
    html = _replace_between(html, "poll-question", d["poll_question"])
    for i, opt in enumerate(d["poll_options"][:4]):
        html = _replace_between(html, f"opt-{i}", opt)

    # Seed poll vote counts in the JS
    votes_js = f"const seedVotes = {json.dumps(d.get('poll_votes_init', [12,18,9,15]))};"
    if "const seedVotes" in html:
        html = re.sub(r'const seedVotes\s*=\s*\[[^\]]*\];', votes_js, html)
    else:
        html = html.replace("</script>", f"  {votes_js}\n</script>", 1)

    # ── Closer stat ──────────────────────────────────────────────────────────
    html = _replace_between(html, "closer-stat",    d["closer_stat"])
    html = _replace_between(html, "closer-context", d["closer_context"])

    return html


# ── ARCHIVE UPDATER ───────────────────────────────────────────────────────────

def update_archive(d):
    """Prepend a new entry card to archive.html."""
    raw = gh_get("/contents/archive.html")
    if not raw:
        return
    current = base64.b64decode(raw["content"]).decode("utf-8")
    sha = raw["sha"]

    tags = [h.get("tag", "").split("&")[0].strip()[:20] for h in d.get("hits", [])[:3] if h.get("tag")]
    tag_html = "".join(f'<span class="tag">{t}</span>' for t in tags[:4])
    preview = d["hits"][0]["title"][:80] if d.get("hits") else ""

    new_entry = f"""
    <div class="issue-card" onclick="window.location.href='issues/{d['date_file']}.html'">
      <div class="issue-number">#{d['issue_num']}</div>
      <div class="issue-meta">
        <div class="date">{d['date_str']}</div>
        <div class="headline">{d['top_headline']}</div>
        <div class="preview">{preview}…</div>
        <div class="tags">{tag_html}</div>
      </div>
    </div>"""

    updated = current.replace(
        "<!-- ARCHIVE_ENTRIES_START -->",
        f"<!-- ARCHIVE_ENTRIES_START -->\n{new_entry}"
    )
    push_file("archive.html", updated, f"Archive: add issue #{d['issue_num']}")


# ── MAIN PUBLISH ─────────────────────────────────────────────────────────────

def publish_issue(issue_data: dict):
    """
    Build today's HTML from the template, push the issue file, update index.html
    and archive.html on GitHub, and save updated files locally.

    Required keys in issue_data: see comments in build_html() above.
    """
    html = build_html(issue_data)
    date_file  = issue_data["date_file"]
    issue_num  = issue_data["issue_num"]
    headline   = issue_data["top_headline"]

    # Save locally so Netlify deploy can pick it up
    local_dir = Path(__file__).parent
    (local_dir / "index.html").write_text(html, encoding="utf-8")
    print(f"  Saved index.html locally")

    # Push today's dated issue
    push_file(
        f"issues/{date_file}.html",
        html,
        f"Issue #{issue_num}: {headline[:60]}"
    )
    print(f"  Pushed issues/{date_file}.html")

    # Update root index.html
    push_file("index.html", html, f"Update index.html for {date_file}")
    print(f"  Updated index.html on GitHub")

    # Update archive
    update_archive(issue_data)
    print(f"  Updated archive.html")

    print(f"Published Issue #{issue_num} for {date_file}")
    return html


if __name__ == "__main__":
    print("Susky Times publisher loaded. Call publish_issue(data) to publish.")
