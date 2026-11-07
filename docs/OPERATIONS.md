# Running clip_star

How to run clip_star day to day: sign-in and team, email, spending limits, disk space and backups.

## First run

Open clip_star in the browser. The first visit opens the **setup wizard**. It walks you through:

1. creating the **owner** account;
2. the creator profile;
3. a check of the engines;
4. adding accounts;
5. adding your first video.

Until the owner account exists, the server is open to whoever reaches it first, so **finish setup right away**, before anyone else can open the address. If `CLIPSTAR_API_TOKEN` is set, the wizard asks for it, so only you can create the owner.

## Team and roles

Invite people in **Settings → Team**. Each invite is a link that works once and expires after 7 days. If email is set up, the link is also emailed.

| Role | Can |
|---|---|
| Owner | Everything, including the team, platform apps, paid-engine choice, budgets, storage rules and backups |
| Editor | Add videos, edit clips, schedule and publish, connect accounts, change creator settings |
| Reviewer | Approve or reject clips, approve or stop batches and posts, handle comments |
| Viewer | Look at everything, change nothing |

- **Forgotten password:** an owner opens the person's row in Team and clicks "New link". The person sets a new password from that link.
- **Disabling someone:** they are signed out on every device at once.
- **At least one owner:** there must always be an active owner, so the last owner can't be demoted or removed.
- **Sign-in protection:**
  - Sign-ins last 30 days (`CLIPSTAR_SESSION_DAYS`).
  - After 5 wrong passwords the account is locked for 15 minutes.
  - Changing your password signs out your other devices.
- **Behind https:** set `CLIPSTAR_COOKIE_SECURE=true`, and set `CLIPSTAR_WEB_URL` to the address people use, so invite and email links point to the right place.
- **Scripts and automation:** these can still use `CLIPSTAR_API_TOKEN` (`Authorization: Bearer …`), with owner rights.

## Workspaces

A workspace holds one creator's or brand's videos, clips, accounts, platform apps, settings, team and stats. Nothing is shared between workspaces.

- **Switching and creating:** use the workspace menu at the bottom of the sidebar. Owners (and the person who installed clip_star) can create workspaces.
- **Roles:** a person can be in several workspaces with a different role in each. Inviting someone who already has a login just adds them; no new password is needed.
- **Removing someone:** disabling or removing a person affects only that workspace.
- **Deleting:** an owner can delete a workspace in Settings → This workspace by typing its name. This removes its files too. The last workspace on a server can't be deleted.
- **Instance admin:** the person who installed clip_star is the instance admin. Backups and the server clean-up cover every workspace, so only they can run or download them.
- **Scripts:** API keys belong to the workspace they were made in. The server token (`CLIPSTAR_API_TOKEN`) picks one with the `X-ClipStar-Workspace: <id>` header (default: the first).

## Notifications and email

The bell shows anything that needs a person:

- a batch waiting for approval;
- failed or unconfirmed posts;
- an account that needs reconnecting;
- a video that is ready or that stopped processing;
- business enquiries in comments;
- the weekly report;
- spending-limit warnings;
- low disk space;
- backup results.

A burst of failures in one batch becomes a single notification per day.

**Push to phones and browsers:** turn it on per device in Settings → Notifications ("Turn on here"). No third-party account is needed: the phone's own push service delivers the message, and only that device can read it.

- **iPhone or iPad (iOS 16.4+):** open clip_star in Safari, tap Share → Add to Home Screen, open it from the Home Screen, then turn push on.
- **What gets pushed:** each person chooses, per workspace. By default you get things that need you (approvals, failures, reconnects, enquiries, budget, disk, backups), not every "video ready".
- **Keys:** the signing keys are created once in `<storage>/.vapid_key`. Back that file up with the rest; if it's lost, devices just need to turn push on again. Set `CLIPSTAR_VAPID_SUBJECT` to a `mailto:` or `https:` address you own, since some push services ask for one.
- **Links:** a tapped notification opens the right page in the right workspace.

**Email** is optional. Set these variables (they're also in `docker-compose.yml`):

- `CLIPSTAR_SMTP_HOST`
- `CLIPSTAR_SMTP_PORT` (587 uses STARTTLS; 465 uses SSL)
- `CLIPSTAR_SMTP_USER`
- `CLIPSTAR_SMTP_PASSWORD`
- `CLIPSTAR_SMTP_FROM`

Each person chooses what gets emailed to them in **Settings → Notifications**. If the email server rejects the login, the error shows in Activity and the email isn't retried forever.

## Spending on paid engines

Every call to a paid connector (Claude today) is recorded with an estimated cost, worked out from the token counts. The default price is Claude Opus 5.5 at $4 per million input tokens and $20 per million output tokens; change it with `CLIPSTAR_CLAUDE_PRICE_INPUT_PER_MTOK` and `CLIPSTAR_CLAUDE_PRICE_OUTPUT_PER_MTOK`.

In **Engines & connectors**, the owner can set a monthly limit and a warning level. When the limit is reached:

- paid engines stop;
- the free engine takes over, with a note on the video;
- work carries on.

The estimate is a guide. Your provider's bill is the final word.

## Disk space

**Settings → Storage** shows what uses the disk. A daily clean-up applies these rules, which the owner can change:

| Rule | Default | What it frees |
|---|---|---|
| Delete audio extracts once a video is ready | on | The WAV made for transcription |
| Delete renders of rejected clips after N days | 7 days | Rendered files of clips you rejected and never posted |
| Archive videos older than N days | off | The original upload and the preview, once no clip from the video is waiting for review or to be posted |

After archiving, the video's clips, transcript and stats stay, but the video can't be re-cut or re-clipped. Videos that are being processed are never touched.

The clean-up also deletes:

- finished jobs older than 30 days (90 days for failed jobs);
- expired sign-ins;
- notifications older than 90 days;
- leftover temporary files.

If free space falls below 5 GB, everyone gets a notification.

## Backups

A backup is one `.tar.gz` file containing:

- the database (made with `pg_dump`);
- the **encryption key**;
- optionally, the videos and clips.

Because the backup holds the key to your platform logins, **keep backups private, and keep a copy off this machine**.

- **Docker:** a daily backup runs automatically into `/data/backups`, and the newest 7 are kept (`CLIPSTAR_BACKUP_KEEP`).
- **Elsewhere:** set `CLIPSTAR_BACKUP_DIR` to turn on daily backups.
- **Back up now:** owners can start a backup and download files in **Settings → Backups**.

From the command line (inside the `api` or `worker` container: `docker compose exec worker python -m clipstar.backup …`):

```bash
python -m clipstar.backup create            # database + key
python -m clipstar.backup create --media    # also videos and clips (can be large)
python -m clipstar.backup list
```

### Restoring

```bash
docker compose stop api worker
docker compose run --rm worker python -m clipstar.backup restore /data/backups/clipstar-backup-YYYYMMDD-HHMMSS.tar.gz --yes
docker compose run --rm api alembic upgrade head
docker compose start api worker
```

Restoring replaces the current database. If the backup includes media, it also replaces the media. Two things to know:

- **Encryption key:** if you set `CLIPSTAR_SECRET_KEY` yourself, set it to the key inside the backup (the `secret_key` file). Otherwise connected accounts must be reconnected.
- **Database version:** `pg_dump` and `pg_restore` must be the same major version as the database or newer. The Docker image ships PostgreSQL 16 client tools to match the `db` service.

## Upgrading

1. Make a backup.
2. Pull the new version.
3. Run `docker compose up --build -d`.

Database changes are applied automatically when the API starts.
