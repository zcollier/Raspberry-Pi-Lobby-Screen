# Web Admin Spec — Integration Contract

Requirements for a PHP web application that uploads media files and selects
which one plays on the VRHS lobby screen.

You are building the **web half** of an existing system. A Raspberry Pi in the
school lobby already runs a Python video player that polls this website. It
cannot accept inbound connections, so everything is driven by two files this web
app writes to disk. Get these two contracts right and the Pi does the rest.

**Target stack:** Dreamhost LAMP — PHP, MySQL, HTML, CSS, JavaScript. No
frameworks, no Composer packages, no CDN-loaded libraries. Everything must work
from the standard PHP install.

---

## 1. The system you are integrating with

Two URLs form the entire interface:

| URL | What it is | Who writes it |
|-----|------------|---------------|
| `https://www.vrhsdramaboosters.com/lobby/state.json` | Says which file should be playing | **Your app** |
| `https://www.vrhsdramaboosters.com/lobby/video/` | Directory of media files | **Your app** (uploads) |

The Pi does this on a loop, forever:

- Every **15 seconds**: fetch `state.json`. If its contents changed since the
  last one it acted on, switch to the named file.
- Every **5 minutes**: fetch the directory listing of `/lobby/video/`, then send
  a `HEAD` request per file. Download anything missing locally or whose **size
  or modification time** differs from the local copy.

The Pi identifies itself with `User-Agent: vrhs-lobby-player/2.0` and appends a
cache-busting `?_=<unixtime>` query parameter to every request. Your server must
tolerate that unknown parameter (stock Apache does; a PHP router must ignore it).

---

## 2. `state.json` — exact contract

### Schema

```json
{
  "version": 1,
  "video": "spring-musical-2026.mp4",
  "updated": "2026-08-12T13:00:00Z"
}
```

| Field | Type | Required | Rules |
|-------|------|----------|-------|
| `version` | **integer** | no (defaults to 1) | Must be exactly `1`. Any other value makes the Pi **ignore the entire file** |
| `video` | string | **yes** | A bare filename. See filename rules in §4 |
| `updated` | string | no, but always send it | ISO 8601. `Z` suffix or explicit offset. A timestamp with no zone is interpreted as `America/Chicago` |

### Type traps that will silently break it

- **`version` must be a JSON number, not a string.** The Pi compares against the
  integer `1`; `"1"` fails the check and the whole file is discarded. In PHP,
  build the array with `'version' => 1`, not `'version' => '1'`.
- **The top level must be a JSON object**, not an array.
- **No UTF-8 BOM.** A BOM makes the parse fail and the file is ignored.
- **Must be valid UTF-8**, under 64 KB.

### What the Pi does with a malformed file

Nothing. It logs a warning and keeps playing whatever is on screen. A broken
`state.json` never blanks the lobby screen — but it also means a silent failure,
so validate before writing.

### Writing it atomically (required)

The Pi may read the file at any moment, including mid-write. Never write in
place. Write to a temporary file in the same directory and `rename()` it, which
is atomic on Linux:

```php
$dir = __DIR__;                        // the /lobby directory
$state = [
    'version' => 1,                    // integer!
    'video'   => $selectedFilename,    // bare filename, already validated
    'updated' => gmdate('Y-m-d\TH:i:s\Z'),
];

$json = json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
if ($json === false) {
    throw new RuntimeException('Could not encode state');
}

$tmp = $dir . '/.state.json.' . bin2hex(random_bytes(6)) . '.tmp';
if (file_put_contents($tmp, $json . "\n", LOCK_EX) === false) {
    throw new RuntimeException('Could not write temp state file');
}
chmod($tmp, 0644);                     // Apache must be able to serve it
if (!rename($tmp, $dir . '/state.json')) {
    unlink($tmp);
    throw new RuntimeException('Could not install state file');
}
```

Use `gmdate()` for an unambiguous UTC timestamp rather than relying on the
server's default timezone.

### Serve it as a static file

Do **not** generate `state.json` dynamically from PHP. If PHP ever emits a
notice or warning, it lands in the response body ahead of the JSON, the parse
fails, and the Pi ignores the instruction. A static file has no such failure
mode. Read it with `file_get_contents()` on the local path when you need to
display the current selection — never fetch it over HTTP, which would hit the
cache described in §6.

---

## 3. When the Pi acts on `state.json` — the important part

The Pi does **not** compare your timestamp against its own clock. It remembers a
fingerprint of the last instruction it applied and reacts only when the file's
**values** change.

This exists because the lobby also has physical buttons, and the rule is *most
recent instruction wins*:

| Time | Event | Result |
|------|-------|--------|
| 8:00 | Your app writes `video: A.mp4` | Pi plays A |
| 8:05 | Someone presses NEXT in the lobby, landing on B | Pi plays B |
| 8:06 | Pi polls; `state.json` still says A | **Pi keeps playing B** |
| 9:00 | Your app writes `video: C.mp4` | Pi plays C |

Three consequences you must design around:

**1. Only write `state.json` when a human makes a selection.**
Never write it on page load, on a cron job, or as a "refresh." Every write with
changed values is a command that overrides whatever the lobby buttons did.

**2. Never include volatile fields.**
The fingerprint covers *every* key in the object. If you add something like
`"generated": "<now>"` and write on each page view, the Pi will re-apply the
remote choice every few seconds and the physical buttons will appear broken.
Send only `version`, `video`, and `updated`.

**3. Re-selecting the same video requires a changed `updated`.**
Because the fingerprint is computed on parsed values, rewriting the file with
identical values is a no-op — whitespace and key order don't matter. If a user
picks the video that's already named in `state.json` (to override someone's
button press), you must still write a **new `updated` timestamp**. Simplest rule:
always set `updated` to now whenever the user submits the form.

A good UI affordance here is a "Play this again on the lobby screen" button that
rewrites `state.json` with a fresh timestamp for the already-selected video.

---

## 4. `/lobby/video/` — media directory contract

### The directory listing must keep working

The Pi enumerates this directory using **Apache's `mod_autoindex` listing**. It
is currently enabled and returns standard markup like:

```html
<a href="default.mov">default.mov</a>   2026-08-12 09:15   12M
```

**Do not place an `index.html`, `index.php`, or any other DirectoryIndex file in
`/lobby/video/`.** Doing so replaces the listing with your page, the Pi finds
zero files, and media sync silently stops working forever. This is the single
most likely way to break the system.

Put your admin UI at `/lobby/admin/` or `/lobby/index.php` — anywhere except
inside `/lobby/video/`. An `.htaccess` in `/lobby/video/` is fine; an index file
is not.

Also required of that directory:

- **Files must sit at the top level.** Subdirectories are not scanned.
- **The trailing-slash URL must keep working.** The Pi requests
  `/lobby/video/` exactly. Don't add a rewrite rule that changes what that path
  returns.
- **`HEAD` requests must return accurate `Content-Length` and `Last-Modified`.**
  This is how the size/timestamp comparison works. Stock Apache does this for
  static files. If you ever proxy these through PHP, you must reproduce both
  headers correctly.
- **No HTTP auth on this directory or on `state.json`.** The Pi sends no
  credentials. Protect your admin pages, not the content the Pi reads.
- The listing HTML must stay under about 1 MB, which is thousands of files.

### Filename rules

The Pi validates every filename it sees and skips anything that fails. Enforce
the same rules at upload time so nothing lands in a state the Pi will refuse.

**Allowed extensions** (case-insensitive):

| Kind | Extensions |
|------|------------|
| Video | `.mp4` `.mov` `.avi` `.mkv` `.webm` |
| Image | `.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` |

Anything else is ignored by the Pi and just wastes space on the server. Images
are first-class — the Pi displays them full screen indefinitely, so a poster or
announcement slide works exactly like a video, including being named in
`state.json`.

**Rejected by the Pi:**

- Any name containing `/`, `\`, or a null byte
- `.` or `..`
- Names with leading or trailing whitespace
- Anything that isn't a plain filename

**Additionally, you should reject:**

- **Leading dots.** `.hidden.mp4` passes the Pi's safety check but is skipped by
  its local file scanner, so it would download and then never appear. Reject it.
- **Case-insensitive duplicates.** `Video.mp4` and `video.mp4` can coexist on
  Linux, but the Pi's lookup falls back to case-insensitive matching, making
  which one plays ambiguous. Reject a name that collides case-insensitively with
  an existing file.

**Recommended sanitizing:** strip to `A-Za-z0-9._-`, converting spaces to
hyphens. Spaces do work end to end (Apache percent-encodes them, the Pi decodes
them) but they make every other tool harder to use.

Always run the client-supplied name through `basename()` and validate against an
allowlist server-side. Never trust a name from the browser.

### Uploads must be atomic

**Apache serves half-written files.** If you write directly into
`/lobby/video/`, the Pi can start downloading a file that is still uploading.

The Pi defends itself — it re-checks size after downloading and discards a file
that changed mid-transfer — but that means a wasted transfer and a delay. This
is not hypothetical; it was observed during testing.

Upload to a temporary name with a non-media extension, then rename:

```php
$final = $videoDir . '/' . $safeName;
$staging = $videoDir . '/' . $safeName . '.part';   // .part is ignored by the Pi

if (!move_uploaded_file($_FILES['media']['tmp_name'], $staging)) {
    throw new RuntimeException('Upload failed');
}
chmod($staging, 0644);
if (!rename($staging, $final)) {                     // atomic
    unlink($staging);
    throw new RuntimeException('Could not install file');
}
```

`.part` is not a recognized media extension, so a partially uploaded file is
invisible to the Pi until the rename completes.

### Do not touch files you haven't changed

The Pi re-downloads whenever size **or** modification time differs. Rewriting,
copying, or `touch`-ing an unchanged file changes its mtime and triggers a full
re-download of a possibly multi-hundred-megabyte video over the school's
internet. Leave existing files alone unless the user actually replaced them.

Replacing a file is fine and is the intended workflow: uploading a new
`default.mov` over the old one sets a fresh mtime, and the Pi picks it up within
5 minutes and restarts playback if that file is currently on screen.

### Deleting files

Deleting from `/lobby/video/` does **not** delete the Pi's local copy — the Pi
never deletes anything by default. If your UI offers deletion, say so plainly:
"Removes the file from the website. The lobby screen keeps its downloaded copy
until someone clears it manually."

---

## 5. Behavior your UI should reflect

So the interface tells the truth about what will happen:

- **Fallback video.** If `state.json` names a file the Pi doesn't have, it plays
  `default.mp4`, or `default.mov` if there's no mp4, and keeps waiting for the
  named file to appear. Warn the user if they select a file that isn't in
  `/lobby/video/`, and consider flagging when neither default exists.
- **Propagation delay.** A selection reaches the screen in about 15 seconds; a
  newly uploaded file can take up to 5 minutes plus download time. Show both
  expectations rather than implying it's instant.
- **The Pi may disagree with the website.** Someone may have pressed a button in
  the lobby since your last write. Your app cannot observe that — the Pi never
  reports back. Don't claim to display "what is playing now"; label it "last
  selection sent from this site."
- **Disk space.** The Pi refuses any download that would leave under 1 GB free,
  and refuses files over 8 GB. Showing the total size of `/lobby/video/` helps
  users avoid overrunning the SD card.

Suggested screens: a file list with size and modification date, a radio-button
selection that writes `state.json`, an upload form, and a delete action.

---

## 6. Caching

Everything under `/lobby/` is currently served with:

```
cache-control: max-age=172800      # two days
```

The Pi is immune (unique query parameter per request, no CDN in front of the
site), but this will mislead **you** during development — a browser will show a
two-day-old `state.json` while the Pi already has the new one. Always read the
file from disk in PHP, not over HTTP.

Add an `.htaccess` in `/lobby/` to fix it at the source:

```apache
<FilesMatch "\.json$">
    Header set Cache-Control "no-cache, no-store, must-revalidate"
</FilesMatch>
```

Media files can keep the long cache lifetime — the sync compares metadata via
`HEAD`, which isn't affected.

---

## 7. Security requirements

`/lobby/video/` is a public, web-served directory that your form writes into.
Treat this as the primary risk in the project.

**Required:**

- **Authenticate the admin UI.** Session-based login with `password_hash()` /
  `password_verify()`. No third-party dependency needed. Scope the protection to
  the admin pages — never to `state.json` or `/lobby/video/`.
- **CSRF token** on the upload and selection forms.
- **Server-side extension allowlist.** JavaScript validation is a convenience,
  not a control.
- **Disable PHP execution in the upload directory.** An extension allowlist
  should prevent a `.php` upload, but defense in depth matters when the target is
  a web-served folder. Add to `/lobby/video/.htaccess`:

  ```apache
  <FilesMatch "\.ph(p[0-9]?|tml|ar)$">
      Require all denied
  </FilesMatch>
  ```

  This does not affect the directory listing. Just don't add an index file.
- **Enforce a maximum upload size** server-side and reject anything over it.

---

## 8. Dreamhost practicalities

- **PHP upload limits will be your first obstacle.** `upload_max_filesize` and
  `post_max_size` default to something in the tens of megabytes, well below a
  typical video. Check the actual values with `phpinfo()` and raise them via a
  custom `php.ini` for the site. Also raise `max_execution_time` and
  `max_input_time`, since a large upload over a school connection is slow.
- If the limits can't be raised far enough, chunked upload is achievable with
  plain JavaScript — `Blob.slice()` plus `fetch()` posting sequential chunks
  that PHP appends to the `.part` file, renaming only when the last chunk lands.
  That fits the no-dependencies constraint and reuses the atomicity pattern
  above.
- **MySQL is optional.** The Pi reads only the filesystem. A database is
  reasonable for user accounts or an upload audit log, but `state.json` and the
  files on disk must remain the source of truth. Never make the Pi's behavior
  depend on the database being up.
- **File ownership.** PHP runs as the site user on Dreamhost, so uploaded files
  are owned correctly. Still set mode `0644` explicitly so Apache can serve them.

---

## 9. Verifying your work

The Pi has two diagnostic commands. Ask the operator to run them after you
deploy:

```bash
python3 /usr/local/bin/video-player.py --check-remote
python3 /usr/local/bin/video-player.py --sync-now
```

`--check-remote` prints the fetched `state.json`, its parsed values, the
resolved local file, and every file in `/lobby/video/` with its size, timestamp,
and whether it would be downloaded. It is the definitive check that your output
is compatible.

You can validate most of it yourself without the Pi:

```bash
# Valid JSON? Correct types?
curl -s 'https://www.vrhsdramaboosters.com/lobby/state.json' | python3 -m json.tool

# Directory listing still parseable? (should list your files, not your UI)
curl -s 'https://www.vrhsdramaboosters.com/lobby/video/' | grep -o 'href="[^"]*"'

# HEAD metadata present and accurate?
curl -sI 'https://www.vrhsdramaboosters.com/lobby/video/default.mov' \
  | grep -iE 'content-length|last-modified'
```

### Acceptance checklist

- [ ] `state.json` parses as a JSON object with `version` as an integer `1`
- [ ] `video` is a bare filename with an allowed extension
- [ ] `updated` changes on every user-submitted selection, including re-selecting
      the same video
- [ ] No extra or volatile fields in `state.json`
- [ ] `state.json` is written via temp file + `rename()`, never in place
- [ ] `state.json` is a static file, not PHP output
- [ ] `/lobby/video/` still returns an Apache directory listing (no index file)
- [ ] Uploads land via a `.part` file + `rename()`
- [ ] Uploaded filenames are sanitized, allowlisted, and rejected for leading
      dots and case-insensitive collisions
- [ ] Existing files are never re-touched, so mtimes stay stable
- [ ] Admin UI requires login; `state.json` and `/lobby/video/` do not
- [ ] PHP execution denied in `/lobby/video/`
- [ ] `state.json` written only on deliberate user action

---

## 10. Quick reference

| Constant | Value |
|----------|-------|
| State poll interval | 15 seconds |
| Media sync interval | 5 minutes |
| Max `state.json` size | 64 KB |
| Max listing size | ~1 MB |
| Max single file | 8 GB |
| Free space the Pi reserves | 1 GB |
| Timestamp comparison tolerance | 2 seconds |
| Fallback video | `default.mp4`, then `default.mov` |
| Video extensions | `.mp4` `.mov` `.avi` `.mkv` `.webm` |
| Image extensions | `.jpg` `.jpeg` `.png` `.gif` `.bmp` `.webp` |

The authoritative implementation is `video-player.py` in this repository —
`parse_remote_payload()` and `is_safe_filename()` define the validation rules,
and `sync_once()` defines the sync behavior.
