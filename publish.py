#!/usr/bin/env python3
"""
The Susky Times — Daily Publishing Script
Includes Athlete of the Day scraper from suriverhawks.com
==========================================
Called by the scheduled task every morning.
Injects today's content into the HTML template, then pushes to GitHub.
Uses only Python stdlib (no third-party packages needed).
"""

import os, json, base64, re, random
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
    html = _replace_between(html, "issue-num",  str(d["issue_num"]))
    # day-greeting: extract day name from date_str (first word)
    day_name = d["date_str"].split(",")[0]  # e.g. "Tuesday"
    html = _replace_between(html, "day-greeting", day_name)
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

    # ── Athlete of the Day ────────────────────────────────────────────────────
    athlete = d.get("athlete")
    if not athlete:
        print("  Fetching Athlete of the Day from suriverhawks.com...")
        athlete = fetch_athlete_of_the_day()
        print(f"  Athlete: {athlete['name']} ({athlete['sport']})")
    html = inject_athlete(html, athlete)

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


# ── ATHLETE OF THE DAY ────────────────────────────────────────────────────────

SU_SPORTS = [
    ("Football",          "football"),
    ("Men's Basketball",  "mens-basketball"),
    ("Women's Basketball","womens-basketball"),
    ("Baseball",          "baseball"),
    ("Softball",          "softball"),
    ("Men's Soccer",      "mens-soccer"),
    ("Women's Soccer",    "womens-soccer"),
    ("Men's Lacrosse",    "mens-lacrosse"),
    ("Women's Lacrosse",  "womens-lacrosse"),
    ("Volleyball",        "volleyball"),
    ("Field Hockey",      "field-hockey"),
    ("Wrestling",         "wrestling"),
    ("Men's Tennis",      "mens-tennis"),
    ("Women's Tennis",    "womens-tennis"),
    ("Men's Cross Country","mens-cross-country"),
    ("Women's Cross Country","womens-cross-country"),
    ("Swimming & Diving", "swimming-and-diving"),
]

def fetch_athlete_of_the_day():
    """
    Pick a random sport, fetch the roster, pick a random athlete.
    Returns a dict: {name, sport, position, year, hometown, photo_url, profile_url, initials}
    """
    random.shuffle(SU_SPORTS)
    for sport_name, sport_slug in SU_SPORTS:
        try:
            url = f"https://suriverhawks.com/sports/{sport_slug}/roster"
            req = urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlreq.urlopen(req, timeout=10) as r:
                html = r.read().decode("utf-8", errors="ignore")

            # Extract all athlete photo URLs from the page
            photo_urls = re.findall(
                r'https://suriverhawks\.com/images/[^\s"\']+\.(?:jpg|jpeg|png|JPG|PNG)',
                html, re.IGNORECASE
            )
            # Build a name→photo map (URL has Name_Lastname.JPG pattern)
            photo_map = {}
            for p in photo_urls:
                fname = re.sub(r'\.[^.]+$', '', p.split("/")[-1])  # strip extension
                key = re.sub(r'[_\-]+', ' ', fname).strip().lower()
                photo_map[key] = p

            # Extract athlete names and profile links
            athletes = []
            seen_profiles = set()
            for m in re.finditer(
                r'href="(/sports/' + re.escape(sport_slug) + r'/roster/[^"]+/(\d+))"[^>]*>\s*([^<]{3,60})</a>',
                html
            ):
                profile_path, _uid, name = m.group(1), m.group(2), m.group(3).strip()
                # Skip generic link labels and duplicates
                if not name or len(name) < 3 or name.lower() in ("full bio", "bio", "profile", "more"):
                    continue
                if profile_path in seen_profiles:
                    continue
                seen_profiles.add(profile_path)
                name_key = name.lower()
                photo = photo_map.get(name_key, "")
                # Fuzzy photo match: try last name
                if not photo:
                    last = name.split()[-1].lower() if name.split() else ""
                    photo = next((v for k, v in photo_map.items() if last in k), "")
                athletes.append({
                    "name": name,
                    "photo_url": photo,
                    "profile_url": f"https://suriverhawks.com{profile_path}",
                })

            # Fallback: just use photo URLs to build minimal athlete entries
            if not athletes and photo_urls:
                for p in photo_urls:
                    fname = re.sub(r'\.[^.]+$', '', p.split("/")[-1])
                    name = re.sub(r'[_\-]+', ' ', fname).strip()
                    # Filter out non-name strings (too short or contain digits)
                    if len(name) >= 5 and not re.search(r'\d', name):
                        athletes.append({
                            "name": name,
                            "photo_url": p,
                            "profile_url": f"https://suriverhawks.com/sports/{sport_slug}/roster",
                        })

            if not athletes:
                continue

            athlete = random.choice(athletes)
            name = athlete["name"]
            initials = "".join(p[0].upper() for p in name.split()[:2])

            # Try to get more detail from profile page
            position, year, hometown = "", "", ""
            if athlete.get("profile_url") and "rp_id" in athlete.get("profile_url", ""):
                try:
                    preq = urlreq.Request(athlete["profile_url"], headers={"User-Agent": "Mozilla/5.0"})
                    with urlreq.urlopen(preq, timeout=8) as pr:
                        phtml = pr.read().decode("utf-8", errors="ignore")
                    for label, field_var in [("Position", "position"), ("Class", "year"), ("Hometown", "hometown")]:
                        pm = re.search(rf'{label}[^<]*</[^>]+>\s*<[^>]+>\s*([^<]+)<', phtml, re.IGNORECASE)
                        if pm:
                            val = pm.group(1).strip()
                            if field_var == "position": position = val
                            elif field_var == "year": year = val
                            elif field_var == "hometown": hometown = val
                except Exception:
                    pass

            return {
                "name": name,
                "sport": sport_name,
                "position": position,
                "year": year,
                "hometown": hometown,
                "photo_url": athlete.get("photo_url", ""),
                "profile_url": athlete.get("profile_url", f"https://suriverhawks.com/sports/{sport_slug}/roster"),
                "initials": initials,
            }
        except Exception:
            continue

    # Final fallback if all sports fail
    return {
        "name": "River Hawk",
        "sport": "Athletics",
        "position": "",
        "year": "",
        "hometown": "Selinsgrove, PA",
        "photo_url": "",
        "profile_url": "https://suriverhawks.com",
        "initials": "RH",
    }


def inject_athlete(html, a):
    """Inject athlete-of-the-day data into the HTML."""
    html = _replace_between(html, "athlete-name",      a["name"])
    html = _replace_between(html, "athlete-sport-tag", a["sport"].upper())
    html = _replace_between(html, "athlete-position",  a.get("position", ""))
    html = _replace_between(html, "athlete-year",      a.get("year", ""))
    html = _replace_between(html, "athlete-hometown",  a.get("hometown", ""))
    html = _replace_between(html, "athlete-initials",  a.get("initials", ""))

    # Bio line
    bio_parts = []
    if a.get("sport"): bio_parts.append(f"Competing for the River Hawks in {a['sport']}")
    if a.get("year"):  bio_parts.append(f"a {a['year'].lower()}")
    if a.get("hometown"): bio_parts.append(f"from {a['hometown']}")
    bio = (", ".join(bio_parts) + ".") if bio_parts else f"A member of SU's {a['sport']} team."
    html = _replace_between(html, "athlete-bio", bio)

    # Photo src
    if a.get("photo_url"):
        html = re.sub(
            r'(id="athlete-photo"\s+src=")[^"]*(")',
            rf'\g<1>{a["photo_url"]}\2', html, count=1
        )
    # Profile link
    html = re.sub(
        r'(id="athlete-link"\s+href=")[^"]*(")',
        rf'\g<1>{a["profile_url"]}\2', html, count=1
    )
    return html


if __name__ == "__main__":
    print("Susky Times publisher loaded. Call publish_issue(data) to publish.")
