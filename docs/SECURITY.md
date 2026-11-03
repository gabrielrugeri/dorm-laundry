# Security

How Dorm Laundry protects logins and residents' PINs. Package G of the
current plan extends this page (CI security checks, the test list, what is
not covered, how to report a problem).

## Residents' PINs

- A PIN is exactly 6 digits, not trivially guessable (`000000`, `123456`,
  `987654` are refused): `apps/accounts/validators.py`.
- **Hashed with a pepper.** A 6-digit PIN has only a million values, so a
  stolen database alone would let anyone try them all against each hash. Every
  PIN is first mixed with a server-side secret, `PIN_PEPPER`, using
  HMAC-SHA256, then hashed with PBKDF2 like a password
  (`apps/accounts/hashers.py`). The pepper lives only in an environment
  variable: never in the database, the backups or the repository. Without it
  the hashes cannot even be checked.
- Stored hashes start with `pin_pbkdf2_sha256$`. Set and check PINs only
  through `apps/accounts/pins.py`; `User.check_password` never lets Django
  re-hash a PIN without the pepper. Staff passwords use Django's normal
  hasher.
- **PINs set before the pepper existed** (plain `pbkdf2_sha256$` hashes) still
  work once and are re-hashed with the pepper at that login. Nothing else is
  needed; the demo can also simply be reseeded. ("Wrapping" the old hashes
  without a login was considered: it would need a second hash format kept
  forever, for a handful of demo accounts.)

### Looking after `PIN_PEPPER`

- Production refuses to start without it, or with the development value, or
  with fewer than 32 characters. Generate it once:
  `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
- **Back it up securely, separately from the database backups** (e.g. in the
  same password manager as the backup decryption key). A database backup and
  the pepper together are what an attacker needs; keep them apart.
- **Losing or changing it makes every resident PIN invalid.** Nobody can log
  in with a PIN until they get a new login link («Сбросить PIN / ссылка для
  входа») from the administration. Staff passwords are not affected.
- There is no rotation procedure: change it only if it leaked, and then plan
  for every resident needing a new link.

## Login limits

Kept in the shared cache (`apps/accounts/ratelimit.py`). The numbers are
fields of the money and upload rules that **only superusers** change, in
Django admin (`/admin/dorms/globalsettings/1/change/`), with a reason; every
change is in the history.

**Per account** (the student code or staff username as typed): after 5 wrong
PINs in a row the account is locked for 1 minute; each further lock lasts
twice as long (2, 4, 8, 16 minutes), up to 30 minutes. A successful login
starts over. Codes that do not exist are locked exactly like real ones.
Someone can deliberately lock a resident out for up to 30 minutes by typing
wrong PINs for their code; that is the price of stopping guessing.

**Per address:** the whole dormitory may reach the internet through one
address, so typos from hundreds of residents must not block it. Up to 30
wrong PINs in 15 minutes nothing happens. Beyond that an attempt has to wait
a few seconds after the address's last failure (1 more second per 10 extra
failures, at most 10 seconds): "Too many attempts from your network. Wait N
s". Only 1000 wrong PINs in an hour block the address until the hour is over.
A test checks that 300 residents behind one address, each mistyping once in
the same hour, all get in, waiting at most a few seconds once.

Every refusal happens before the PIN is checked, and every message is
generic: none says whether a student code exists. Wrong current PINs on the
"Change PIN" page and wrong old passwords on "Change password" count toward
the same limits.

Known limit: the counts are read and written without a lock, so a few
requests arriving at the very same moment may each get one extra attempt
(at most the number of server threads, 4 on the pilot).

## The client's address

Login limits need the address the request really comes from. Behind a reverse
proxy `REMOTE_ADDR` is the proxy itself (or empty, with nginx on a unix
socket). The app trusts **one header only**, `CLIENT_IP_HEADER`
(`X-Real-IP` in production), which our proxy sets on every request and
overwrites if the client sent one (`apps/core/client_ip.py`):

- **nginx** (`deploy/nginx/dorm-laundry.conf`):
  `proxy_set_header X-Real-IP $remote_addr;`. Keep that line.
- **Railway:** its public edge sets `X-Real-IP` to the connecting address and
  replaces any copy the client sent
  (docs.railway.com/networking/public-networking/specs-and-limits). This
  holds for requests through the public domain; do not let other services in
  the same Railway project call the app over the private network.
- `X-Forwarded-For` is **never** read: proxies append to whatever the client
  sent, so it is easy to spoof. A test sends a forged one and checks it is
  ignored.
- Development without a proxy leaves `CLIENT_IP_HEADER` empty and uses
  `REMOTE_ADDR`.

## Changing a PIN or password

- Residents: «Сменить PIN-код» in the header menu (`/account/pin/`): the
  current PIN, then the new one twice. The new PIN follows the usual rules and
  must differ from the current one.
- Staff: «Сменить пароль» (`/account/password/`), Django's password rules.
- Afterwards every other device of that person is logged out; the current one
  stays logged in. The change is recorded in the history (never the PIN or
  password itself).
