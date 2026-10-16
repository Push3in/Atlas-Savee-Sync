#!/usr/bin/env python3
"""Savee -> Atlas sync, no Claude needed.

  savee_atlas_sync.py login   one-time: approve access in the browser, token goes to Keychain
  savee_atlas_sync.py sync    import new Savee saves, then mirror Savee boards onto the
                              collections in Atlas's "Savee" folder (run by launchd)
  savee_atlas_sync.py dry-run show what would be imported or moved, change nothing

Each Savee board maps to a collection of the same name inside the "Savee" folder
(or "<name> (Savee)" when that name is already taken outside the folder). Saves on
no board go to Unsorted. Only "savee"-tagged items and Savee-folder collections are touched.

Several Macs can run this against the same iCloud library. Board mirroring is idempotent,
and if two Macs import the same save before iCloud catches up, the next run moves the
newer copy to Atlas's Trash. The Atlas key is read from the library's .mcp-token file.
"""
import base64, glob, hashlib, http.server, json, os, re, secrets, subprocess, sys, time
import urllib.parse, urllib.request, urllib.error, webbrowser

SAVEE_MCP = "https://mcp.savee.com/mcp"
AUTH_URL = "https://savee.com/oauth/authorize/"
TOKEN_URL = "https://savee.com/api/oauth/token/"
REGISTER_URL = "https://savee.com/api/oauth/register/"
SCOPE = "saves:read boards:read"
REDIRECT_PORT = 53682
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"

ATLAS_MCP = "http://127.0.0.1:50473/mcp"
ATLAS_TOKEN_GLOB = "~/Library/Mobile Documents/com~apple~CloudDocs/*.atlaslibrary/.mcp-token"

KEYCHAIN_SERVICE = "savee-atlas-sync"
STOP_AFTER_KNOWN = 5   # consecutive already-synced saves before we stop paging
MAX_PAGES = 5
PAGE_SIZE = 30

SAVEE_FOLDER = "Savee"
FALLBACK = "Unsorted"


def log(*a):
    print(time.strftime("%F %T"), *a, flush=True)


# ---------- Keychain ----------

def kc_get():
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", "oauth", "-w"],
                       capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def kc_set(data):
    subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", "oauth",
                    "-w", json.dumps(data)], check=True, capture_output=True)


# ---------- HTTP helpers ----------

def post(url, body, headers=None, form=False, timeout=60):
    data = urllib.parse.urlencode(body).encode() if form else json.dumps(body).encode()
    h = {"Content-Type": "application/x-www-form-urlencoded" if form else "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(), dict(r.headers)


def parse_rpc(raw):
    """MCP replies are plain JSON or SSE ('data: {...}' lines)."""
    raw = raw.strip()
    if raw.startswith("{"):
        return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith("data:"):
            msg = json.loads(line[5:].strip())
            if "result" in msg or "error" in msg:
                return msg
    raise RuntimeError(f"unexpected MCP reply: {raw[:200]}")


# ---------- Savee OAuth ----------

def login():
    state = kc_get() or {}
    if not state.get("client_id") or state.get("scope") != SCOPE:  # re-register when the scope grows
        state["scope"] = SCOPE
        raw, _ = post(REGISTER_URL, {
            "client_name": "Savee to Atlas sync (local script)",
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": SCOPE,
        })
        state["client_id"] = json.loads(raw)["client_id"]

    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    csrf = secrets.token_urlsafe(16)
    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": state["client_id"], "redirect_uri": REDIRECT_URI,
        "scope": SCOPE, "state": csrf, "code_challenge": challenge, "code_challenge_method": "S256",
        "resource": "https://mcp.savee.com/",
    })

    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            result.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Savee connected. You can close this tab.</h2>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    print("Opening Savee in your browser. Approve access there.\nIf it doesn't open:", url)
    webbrowser.open(url)
    srv.timeout = 300
    srv.handle_request()
    if result.get("state") != csrf or "code" not in result:
        sys.exit(f"Login failed: {result}")

    raw, _ = post(TOKEN_URL, {
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": REDIRECT_URI,
        "client_id": state["client_id"], "code_verifier": verifier,
        "resource": "https://mcp.savee.com/",
    }, form=True)
    save_tokens(state, json.loads(raw))
    print("Logged in. Token stored in Keychain under", KEYCHAIN_SERVICE)


def save_tokens(state, tok):
    state["access_token"] = tok["access_token"]
    if tok.get("refresh_token"):
        state["refresh_token"] = tok["refresh_token"]
    state["expires_at"] = time.time() + int(tok.get("expires_in", 3600)) - 60
    kc_set(state)


def access_token():
    state = kc_get()
    if not state or not state.get("refresh_token"):
        sys.exit("Not logged in to Savee. Run: savee_atlas_sync.py login")
    if time.time() < state.get("expires_at", 0):
        return state["access_token"]
    try:
        raw, _ = post(TOKEN_URL, {"grant_type": "refresh_token", "refresh_token": state["refresh_token"],
                                  "client_id": state["client_id"], "resource": "https://mcp.savee.com/"},
                      form=True)
    except urllib.error.HTTPError as e:
        sys.exit(f"Savee token refresh failed ({e.code}). Run: savee_atlas_sync.py login")
    save_tokens(state, json.loads(raw))
    return state["access_token"]


# ---------- MCP clients ----------

class MCP:
    def __init__(self, url, token):
        self.url, self.token, self.session, self.n = url, token, None, 0

    def _send(self, method, params=None, notify=False):
        h = {"Authorization": f"Bearer {self.token}", "Accept": "application/json, text/event-stream",
             "MCP-Protocol-Version": "2025-06-18"}
        if self.session:
            h["Mcp-Session-Id"] = self.session
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            self.n += 1
            body["id"] = self.n
        raw, headers = post(self.url, body, h, timeout=180)
        sid = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
        if sid:
            self.session = sid
        return None if notify else parse_rpc(raw)

    def start(self):
        self._send("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                  "clientInfo": {"name": "savee-atlas-sync", "version": "1"}})
        self._send("notifications/initialized", notify=True)
        return self

    def call(self, name, args):
        msg = self._send("tools/call", {"name": name, "arguments": args})
        if "error" in msg:
            raise RuntimeError(f"{name}: {msg['error']}")
        res = msg["result"]
        text = "".join(c.get("text", "") for c in res.get("content", []) if c.get("type") == "text")
        if res.get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return res, text


def atlas_json(atlas, name, args):
    _, text = atlas.call(name, args)
    return json.loads(text)


# ---------- Savee parsing ----------

def parse_saves(text):
    """Parse list_saves' text output into dicts."""
    saves = []
    for block in re.split(r"\n(?=\d+\. )", text):
        m = re.match(r"\d+\. (.*)", block)
        if not m:
            continue
        s = {"title": m.group(1).strip()}
        for line in block.splitlines()[1:]:
            line = line.strip()
            if line.startswith("savee:"):
                s["savee_url"] = line.split(":", 1)[1].strip()
            elif line.startswith("source:"):
                s["source"] = line.split(":", 1)[1].strip()
            elif re.match(r"(image|video|gif)\b", line):
                kind, url = re.match(r"(\w+)[^:]*:\s*(\S+)", line).groups()
                s["kind"], s["media_url"] = kind, url
        code = re.search(r"savee\.com/i/([^/\s]+)", s.get("savee_url", ""))
        if code and s.get("media_url"):
            s["code"] = code.group(1)
            saves.append(s)
    cursor = re.search(r"cursor:\s*(\S+)\s*$", text.strip())
    return saves, (cursor.group(1) if cursor and "More results" in text else None)


def parse_boards(text):
    """Parse list_boards' text output into (name, id) pairs."""
    boards = []
    for block in re.split(r"\n(?=\d+\. )", text):
        m = re.match(r"\d+\. (.*)", block)
        bid = re.search(r"^\s*id:\s*(\S+)", block, re.M)
        if m and bid:
            boards.append((m.group(1).strip(), bid.group(1)))
    return boards


def clean_title(t, kind):
    if re.fullmatch(r"[\w\-]{20,}", t) or re.fullmatch(r"[0-9a-f\-]{30,}", t):
        return "Video" if kind == "video" else "Image"
    return t


# ---------- Sync ----------

def atlas_items(atlas, args):
    items, offset = [], 0
    while True:
        d = atlas_json(atlas, "search_items", {**args, "limit": 200, "offset": offset})
        items += d["items"]
        if len(d["items"]) < 200:
            return items
        offset += 200


def known_items(atlas):
    """Savee short code -> 'savee'-tagged Atlas items, oldest first, from their annotations."""
    codes = {}
    items = atlas_items(atlas, {"tags": ["savee"], "verbose": True, "sort": "date_added", "order": "asc"})
    for it in items:
        m = re.search(r"savee\.com/i/([^/\s]+)", it.get("annotation") or "")
        if m:
            codes.setdefault(m.group(1), []).append(it)
    return codes


def known_codes(atlas):
    """Savee short code -> Atlas item ids."""
    return {code: [it["id"] for it in items] for code, items in known_items(atlas).items()}


def remove_duplicates(atlas, dry):
    """Trash all but the oldest Atlas item per Savee save (left by two Macs importing at once)."""
    extra = [it["id"] for items in known_items(atlas).values() for it in items[1:]]
    if extra:
        log(f"{'would trash' if dry else 'trash'} {len(extra)} duplicate(s)")
        if not dry:
            atlas.call("trash_items", {"item_ids": extra})


def board_codes(savee):
    """Savee board name -> set of save short codes on it."""
    _, text = savee.call("list_boards", {})
    boards = parse_boards(text)
    if not boards:
        raise RuntimeError("Savee returned no boards")
    result = {}
    for name, bid in boards:
        codes, cursor = set(), None
        for _ in range(50):
            args = {"board_id": bid, "limit": 100}
            if cursor:
                args["cursor"] = cursor
            _, text = savee.call("list_board_saves", args)
            saves, cursor = parse_saves(text)
            codes |= {s["code"] for s in saves}
            if not cursor:
                break
        result[name] = codes
    return result


class Collections:
    """The collections in Atlas's Savee folder, created on demand for new boards."""

    def __init__(self, atlas, dry):
        self.atlas, self.dry = atlas, dry
        cols = atlas_json(atlas, "list_collections", {})["collections"]
        self.folder_id = next((c["folder_id"] for c in cols if c.get("folder") == SAVEE_FOLDER), None)
        if not self.folder_id:
            raise RuntimeError(f'no "{SAVEE_FOLDER}" collection folder in Atlas')
        self.inside = {c["name"]: c["id"] for c in cols if c.get("folder_id") == self.folder_id}
        self.outside = {c["name"] for c in cols if c.get("folder_id") != self.folder_id}

    def for_board(self, board):
        for name in (board, f"{board} (Savee)"):
            if name in self.inside:
                return name
        name = f"{board} (Savee)" if board in self.outside else board
        if self.dry:
            log(f"would create collection {name!r}")
            self.inside[name] = None
            return name
        cid = atlas_json(self.atlas, "create_collection", {"name": name})["id"]
        self.atlas.call("move_collection_to_folder", {"collection": cid, "folder": self.folder_id})
        self.inside[name] = cid
        log(f"created collection {name!r} for new Savee board")
        return name

    def members(self, name):
        cid = self.inside.get(name)
        return {i["id"] for i in atlas_items(self.atlas, {"collection": cid})} if cid else set()


def mirror_boards(atlas, savee, dry):
    """Put every synced item in exactly the Savee-folder collections matching its boards."""
    boards = board_codes(savee)
    cols = Collections(atlas, dry)
    known = known_codes(atlas)

    want = {}  # Atlas item id -> set of collection names
    for code, ids in known.items():
        names = {cols.for_board(b) for b, codes in boards.items() if code in codes} or {FALLBACK}
        for item_id in ids:
            want[item_id] = names

    have = {}
    for name in list(cols.inside):
        for item_id in cols.members(name):
            if item_id in want:
                have.setdefault(item_id, set()).add(name)

    adds, removes = {}, {}
    for item_id, names in want.items():
        cur = have.get(item_id, set())
        for n in names - cur:
            adds.setdefault(n, []).append(item_id)
        for n in cur - names:
            removes.setdefault(n, []).append(item_id)

    # Add before removing, so an item is never left in no collection (which refiles it to Inbox).
    for name, ids in adds.items():
        log(f"{'would add' if dry else 'add'}    {len(ids):3} -> {name}")
        if not dry:
            atlas.call("add_to_collection", {"item_ids": ids, "collection": cols.inside[name]})
    for name, ids in removes.items():
        log(f"{'would remove' if dry else 'remove'} {len(ids):3} <- {name}")
        if not dry:
            atlas.call("remove_from_collection", {"item_ids": ids, "collection": cols.inside[name]})
    log(f"boards mirrored: {sum(map(len, adds.values()))} placements added, "
        f"{sum(map(len, removes.values()))} removed")


def ensure_atlas():
    def up():
        try:
            MCP(ATLAS_MCP, atlas_token())._send("ping")
            return True
        except Exception:
            return False
    if up():
        return
    subprocess.run(["open", "-g", "-a", "Atlas"])
    for _ in range(15):
        time.sleep(2)
        if up():
            return
    sys.exit("Atlas MCP unreachable (is Settings ▸ MCP ▸ Atlas MCP on?)")


def store_atlas_key():
    """Copy the Atlas key from the library into the Keychain. Run from Terminal: launchd
    jobs aren't allowed to read the library's files, but can read the Keychain."""
    paths = glob.glob(os.path.expanduser(ATLAS_TOKEN_GLOB))
    if not paths:
        sys.exit("Atlas key not found (no .mcp-token in an iCloud Drive .atlaslibrary)")
    with open(paths[0]) as f:
        key = f.read().strip()
    subprocess.run(["security", "add-generic-password", "-U", "-s", KEYCHAIN_SERVICE, "-a", "atlas",
                    "-w", key], check=True, capture_output=True)
    print("Atlas key stored in Keychain under", KEYCHAIN_SERVICE)


def atlas_token():
    r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", "atlas", "-w"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("Atlas key not in Keychain. Run: savee_atlas_sync.py atlas-key")
    return r.stdout.strip()


def sync(dry=False):
    ensure_atlas()
    atlas = MCP(ATLAS_MCP, atlas_token())
    remove_duplicates(atlas, dry)
    known = known_codes(atlas)
    savee = MCP(SAVEE_MCP, access_token()).start()

    new, streak, cursor = [], 0, None
    for _ in range(MAX_PAGES):
        args = {"limit": PAGE_SIZE}
        if cursor:
            args["cursor"] = cursor
        _, text = savee.call("list_saves", args)
        saves, cursor = parse_saves(text)
        for s in saves:
            if s["code"] in known:
                streak += 1
            else:
                streak = 0
                new.append(s)
        if streak >= STOP_AFTER_KNOWN or not cursor:
            break

    log(f"known in Atlas: {len(known)}, new on Savee: {len(new)}")
    added = []
    for s in reversed(new):  # oldest first, so Atlas order matches Savee
        coll = FALLBACK  # mirror_boards files it onto its boards' collections below
        if dry:
            log(f"would add  {coll:18} | {s['title'][:70]} | {s['savee_url']}")
            continue
        try:
            before = {i["id"] for i in atlas_json(atlas, "search_items", {"added_within_days": 1, "limit": 200})["items"]}
            atlas.call("save_media_from_url", {"url": s["media_url"], "collection": coll})
            after = atlas_json(atlas, "search_items", {"added_within_days": 1, "limit": 200})["items"]
            ids = [i["id"] for i in after if i["id"] not in before]
            if not ids:
                raise RuntimeError("Atlas reported no new item")
            for item_id in ids:
                meta = {"item_id": item_id,
                        "annotation": f"{clean_title(s['title'], s.get('kind'))}\n\nSavee: {s['savee_url']}"}
                if s.get("source"):
                    meta["source_url"] = s["source"]
                atlas.call("set_metadata", meta)
            atlas.call("add_tags", {"item_ids": ids, "tags": ["savee"]})
            added.append(s)
            log(f"added  {coll:18} | {s['title'][:70]} | {s['savee_url']}")
        except Exception as e:
            log(f"FAILED {s['savee_url']}: {e}")
    if not dry:
        log(f"done: {len(added)}/{len(new)} imported")
    try:
        mirror_boards(atlas, savee, dry)
    except Exception as e:
        log(f"FAILED mirroring boards: {e}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "sync"
    if cmd == "login":
        login()
    elif cmd == "atlas-key":
        store_atlas_key()
    elif cmd == "dry-run":
        sync(dry=True)
    elif cmd == "sync":
        sync()
    else:
        sys.exit(__doc__)
