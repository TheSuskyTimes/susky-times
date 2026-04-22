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
from datetime import date, timedelta, datetime
from pathlib import Path
from urllib import request as urlreq, error as urlerr

# ── LOAD .env IF PRESENT ─────────────────────────────────────────────────────
_script_dir = Path(__file__).parent
_env_file = _script_dir / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ[_k.strip()] = _v.strip()

# ── CONFIG ───────────────────────────────────────────────────────────────────
GITHUB_OWNER    = "TheSuskyTimes"
GITHUB_REPO     = "susky-times"
GITHUB_TOKEN    = os.environ.get("GITHUB_TOKEN", "")
BEEHIIV_PUB_ID  = os.environ.get("BEEHIIV_PUB_ID", "")   # Set in .env to enable email sends
BEEHIIV_API_KEY = os.environ.get("BEEHIIV_API_KEY", "")  # Set in .env to enable email sends
BRANCH          = "main"


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
    # Also update sub-count and reader count
    sub_count = d.get("sub_count", "SU students")
    html = _replace_between(html, "sub-count", f'{sub_count} readers')

    # Inject Beehiiv publication ID if configured
    if BEEHIIV_PUB_ID:
        html = html.replace("'__BEEHIIV_PUB_ID__'", f"'{BEEHIIV_PUB_ID}'")

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

    # ── River Hawks Scorecard ─────────────────────────────────────────────────
    games = d.get("recent_games")
    if games is None:
        print("  Fetching recent game results from suriverhawks.com...")
        games = fetch_recent_games()
        print(f"  Found {len(games)} recent game(s)")
    html = inject_recent_games(html, games)

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

def send_beehiiv_email(issue_data: dict, html: str) -> bool:
    """Send today's issue to all Beehiiv subscribers as an email newsletter.
    Returns True if sent, False if skipped (no API key configured).
    """
    if not BEEHIIV_PUB_ID or not BEEHIIV_API_KEY:
        print("  Beehiiv not configured — skipping email send (set BEEHIIV_PUB_ID and BEEHIIV_API_KEY in .env)")
        return False

    subject = f"🗞️ {issue_data['date_str']}: {issue_data['top_headline'][:60]}"

    payload = json.dumps({
        "subject": subject,
        "content": {
            "free": {
                "web": html,
                "email": html,
            }
        },
        "status": "draft"
    }).encode("utf-8")

    req = urlreq.Request(
        f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts",
        data=payload,
        headers={
            "Authorization": f"Bearer {BEEHIIV_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlreq.urlopen(req, timeout=15) as r:
            result = json.loads(r.read())
            post_id = result.get("data", {}).get("id", "")
            print(f"  Beehiiv draft created: {post_id}")

        # Now send/confirm the post
        if post_id:
            send_payload = json.dumps({"status": "confirmed"}).encode("utf-8")
            send_req = urlreq.Request(
                f"https://api.beehiiv.com/v2/publications/{BEEHIIV_PUB_ID}/posts/{post_id}",
                data=send_payload,
                headers={
                    "Authorization": f"Bearer {BEEHIIV_API_KEY}",
                    "Content-Type": "application/json",
                },
                method="PATCH",
            )
            with urlreq.urlopen(send_req, timeout=15) as r:
                print(f"  Beehiiv email scheduled for send!")
            return True
    except Exception as e:
        print(f"  Beehiiv send failed: {e}")
        return False


def publish_issue(issue_data: dict):
    """
    Build today's HTML from the template, push the issue file, update index.html
    and archive.html on GitHub, and save updated files locally.
    Also push the GitHub Actions workflow for subscriber management.

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

    # Push GitHub Actions workflow for subscriber management (if not already there)
    workflow_path = local_dir / ".github" / "workflows" / "add-subscriber.yml"
    if workflow_path.exists():
        try:
            push_file(
                ".github/workflows/add-subscriber.yml",
                workflow_path.read_text(encoding="utf-8"),
                "Update subscriber workflow"
            )
            print(f"  Pushed subscriber workflow")
        except Exception as e:
            print(f"  Subscriber workflow push failed (may already be up to date): {e}")

    # Push subscribers data file
    sub_file = local_dir / "data" / "subscribers.json"
    if sub_file.exists():
        try:
            push_file(
                "data/subscribers.json",
                sub_file.read_text(encoding="utf-8"),
                "Update subscriber data"
            )
            print(f"  Pushed subscribers.json")
        except Exception as e:
            print(f"  subscribers.json push skipped: {e}")

    # Send email newsletter via Beehiiv (only if configured)
    send_beehiiv_email(issue_data, html)

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


# ── RIVER HAWKS SCORECARD ─────────────────────────────────────────────────────

SPRING_SPORTS = [
    ("Baseball",          "baseball"),
    ("Softball",          "softball"),
    ("Men's Lacrosse",    "mens-lacrosse"),
    ("Women's Lacrosse",  "womens-lacrosse"),
    ("Men's Tennis",      "mens-tennis"),
    ("Women's Tennis",    "womens-tennis"),
]


def _parse_tables(html_text):
    """Return all HTML tables as a list of (list of rows), each row a list of strings."""
    tables = []
    for tbl in re.findall(r'<table[^>]*>.*?</table>', html_text, re.DOTALL | re.IGNORECASE):
        rows = []
        for row_html in re.findall(r'<tr[^>]*>.*?</tr>', tbl, re.DOTALL | re.IGNORECASE):
            cells = []
            for cell_html in re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row_html, re.DOTALL | re.IGNORECASE):
                text = re.sub(r'<[^>]+>', '', cell_html)
                text = re.sub(r'\s+', ' ', text).strip()
                cells.append(text)
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables


def _calc_potg(bs_html):
    """
    Parse SU batting stats from a box score page.
    Table index 3 (0-based) = SU batting: Player, Pos, AB, R, H, RBI, BB, SO
    Player of Game score = H + (RBI * 2) + R
    Returns dict {name, pos, ab, h, r, rbi, stats_str} or None.
    """
    tables = _parse_tables(bs_html)
    if len(tables) < 4:
        return None

    batting = tables[3]
    if len(batting) < 2:
        return None

    # Map header columns
    header = [c.upper().strip() for c in batting[0]]
    try:
        r_idx   = header.index('R')
        h_idx   = header.index('H')
        rbi_idx = header.index('RBI')
        ab_idx  = header.index('AB')
    except ValueError:
        return None

    pos_idx = 1
    if 'POS' in header:
        pos_idx = header.index('POS')

    best = None
    best_score = -1

    for row in batting[1:]:
        if len(row) <= max(h_idx, rbi_idx, r_idx):
            continue
        name = row[0].strip()
        if not name or name.upper() in ('TOTALS', 'TOTAL', ''):
            continue
        if name.startswith('--') or name.startswith('  '):
            continue
        try:
            h   = int(row[h_idx])
            rbi = int(row[rbi_idx])
            r   = int(row[r_idx])
            ab  = int(row[ab_idx])
        except (ValueError, IndexError):
            continue

        score = h + (rbi * 2) + r
        if score > best_score:
            best_score = score
            pos = row[pos_idx].strip() if len(row) > pos_idx else ""
            best = {
                "name": name,
                "pos": pos,
                "ab": ab,
                "h": h,
                "r": r,
                "rbi": rbi,
                "stats_str": f"{h}-for-{ab}, {rbi} RBI, {r} R",
            }

    return best if (best and best_score > 0) else None


def fetch_recent_games():
    """
    Scrape suriverhawks.com for recent (last 14 days) game results.
    Returns list of game dicts: {sport, opponent, date, su_score, opp_score, win, potg, box_score_url}
    """
    today = date.today()
    cutoff = today - timedelta(days=14)
    games = []

    for sport_name, sport_slug in SPRING_SPORTS:
        try:
            url = f"https://suriverhawks.com/sports/{sport_slug}/schedule"
            req = urlreq.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlreq.urlopen(req, timeout=12) as r:
                sched_html = r.read().decode("utf-8", errors="ignore")
        except Exception:
            continue

        # Find box score links: /sports/{slug}/stats/YYYY/{opp}/boxscore/{id}
        bs_pattern = re.compile(
            r'href="(/sports/' + re.escape(sport_slug) + r'/stats/\d{4}/[^/]+/boxscore/(\d+))"',
            re.IGNORECASE
        )

        seen = set()
        for m in bs_pattern.finditer(sched_html):
            bs_path = m.group(1)
            if bs_path in seen:
                continue
            seen.add(bs_path)

            # Grab surrounding context (2000 chars before link, 600 after)
            ctx_start = max(0, m.start() - 2000)
            ctx = sched_html[ctx_start: m.end() + 600]

            # ── Parse date ────────────────────────────────────────────
            game_date = None
            game_date_str = ""
            date_patterns = [
                (r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},\s*\d{4}', "%b. %d, %Y"),
                (r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s*\d{4}',    "%B %d, %Y"),
                (r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}',           "%b. %d"),
                (r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}',              "%B %d"),
            ]
            for dpat, dfmt in date_patterns:
                dm = re.search(dpat, ctx, re.IGNORECASE)
                if dm:
                    raw = dm.group(0).strip()
                    try:
                        parsed = datetime.strptime(raw, dfmt)
                        game_date = parsed.replace(year=today.year).date()
                        if game_date > today:
                            game_date = game_date.replace(year=today.year - 1)
                        game_date_str = game_date.strftime("%b %-d, %Y")
                        break
                    except ValueError:
                        continue

            if game_date and game_date < cutoff:
                continue  # Too old

            # ── Parse opponent ────────────────────────────────────────
            opponent = "Opponent"
            opp_m = re.search(r'(?:vs\.?\s+|at\s+)([A-Z][A-Za-z &\'\-\.]{2,40}?)(?:\s*<|\s*\(|\s*–|\s*\n)', ctx)
            if opp_m:
                opponent = opp_m.group(1).strip().rstrip('.')

            # ── Parse win/loss and score ──────────────────────────────
            wl_m = re.search(r'\b(W|L)\s+(\d+)\s*[-–]\s*(\d+)', ctx, re.IGNORECASE)
            if not wl_m:
                # Try reversed score format
                wl_m = re.search(r'(\d+)\s*[-–]\s*(\d+)\s+(W|L)\b', ctx, re.IGNORECASE)
                if wl_m:
                    result = wl_m.group(3).upper()
                    s1, s2 = int(wl_m.group(1)), int(wl_m.group(2))
                else:
                    continue  # No result found

                win = (result == 'W')
                su_score  = s1 if win else s2
                opp_score = s2 if win else s1
            else:
                result = wl_m.group(1).upper()
                win = (result == 'W')
                s1, s2 = int(wl_m.group(2)), int(wl_m.group(3))
                su_score  = s1 if win else s2
                opp_score = s2 if win else s1

            # ── Fetch box score for Player of the Game ────────────────
            potg = None
            box_url = f"https://suriverhawks.com{bs_path}"
            try:
                bs_req = urlreq.Request(box_url, headers={"User-Agent": "Mozilla/5.0"})
                with urlreq.urlopen(bs_req, timeout=12) as r:
                    bs_html = r.read().decode("utf-8", errors="ignore")
                potg = _calc_potg(bs_html)
            except Exception:
                pass

            games.append({
                "sport":        sport_name,
                "opponent":     opponent,
                "date":         game_date_str or "Recent",
                "su_score":     su_score,
                "opp_score":    opp_score,
                "win":          win,
                "potg":         potg,
                "box_score_url": box_url,
            })

        if len(games) >= 5:
            break

    return games[:5]


def inject_recent_games(html, games):
    """Inject River Hawks Scorecard cards into the HTML template."""
    if not games:
        cards_html = (
            '<p class="scorecard-no-data">No recent game results found. '
            'Check <a href="https://suriverhawks.com" target="_blank">suriverhawks.com</a> '
            'for the latest scores.</p>'
        )
    else:
        cards_html = ""
        for g in games:
            rc = "win" if g["win"] else "loss"
            rl = "W" if g["win"] else "L"

            potg_html = ""
            if g.get("potg"):
                p = g["potg"]
                pos_part = f" &middot; {p['pos']}" if p.get("pos") else ""
                potg_html = (
                    f'\n      <div class="potg-row">'
                    f'<div class="potg-star">&#11088;</div>'
                    f'<div class="potg-info">'
                    f'<div class="potg-label">Player of the Game</div>'
                    f'<div class="potg-name">{p["name"]}{pos_part}</div>'
                    f'<div class="potg-stats">{p["stats_str"]}</div>'
                    f'</div></div>'
                )

            cards_html += (
                f'\n    <div class="game-card">'
                f'\n      <div class="game-meta">{g["sport"]} &middot; {g["date"]}</div>'
                f'\n      <div class="game-score-row">'
                f'<span class="game-score-team">SU</span>'
                f'<span class="game-score-num {rc}">{g["su_score"]}</span>'
                f'<span class="game-score-sep">&ndash;</span>'
                f'<span class="game-score-num">{g["opp_score"]}</span>'
                f'<span class="game-score-team">{g["opponent"]}</span>'
                f'<span class="game-result-badge {rc}">{rl}</span>'
                f'</div>{potg_html}'
                f'\n    </div>'
            )

    return html.replace('<!-- SCORECARD_INJECT -->', cards_html, 1)


if __name__ == "__main__":
    print("Susky Times publisher loaded. Call publish_issue(data) to publish.")
