# Public deployment

The public app is deployed on Streamlit Community Cloud from a dedicated
deployment repository. The deployment repository is an allow-listed copy; it
must never be replaced with the working project directory.

## Runtime configuration

Set this root-level Streamlit Community Cloud secret in **App settings → Secrets**:

```toml
FANTASY_BUNDESLIGA_MODE = "public"
```

The application defaults to `local`, so a public deployment without this value
must be treated as misconfigured. Public mode renders only Players, Position
leaders, and Match stats. It does not construct the ingestion repository and
the operational repository opens SQLite with `mode=ro`.

No API key, `.env` file, local filesystem path, screenshot, OCR artifact,
ingestion record, saved squad, note, or transfer belongs in the deployment
repository.

## Build the public database

From the working project root, with the project virtual environment installed:

```bash
.venv/bin/python scripts/build_public_database.py \
  --output deployment/public_app/data/fantasy_bundesliga.sqlite
```

This uses SQLite's online backup API to make a consistent copy. It then removes
ingestion/evidence/audit data, API raw-request provenance, and private squad
planning data; rewrites retained source paths to `public://` identifiers;
checks foreign keys; and vacuums the result. It never edits the working database.

Run the public-snapshot and deployment checks:

```bash
.venv/bin/python -m pytest -q \
  tests/test_public_database_snapshot.py tests/test_deployment_mode.py
```

## Prepare and deploy

Populate `deployment/public_app` only with the sanitized database and the
allow-listed application files used by the public app. Confirm before pushing:

```bash
find deployment/public_app -type f -print | sort
rg -n '/Users/|fantasy_ingestion/objects|APIFOOTBALL_KEY' deployment/public_app
```

The second command must produce no output. Commit and push the dedicated public
repository, then deploy `app.py` from its `main` branch in Streamlit Community
Cloud. Select Python 3.9 when offered, add the public-mode secret above, and use
the assigned `https://…streamlit.app` URL.

## Refresh the public database

1. Finish and verify local imports or approved publication work.
2. Run the build command in **Build the public database**.
3. Run the two focused test files.
4. Copy only the rebuilt SQLite file into the deployment repository at
   `data/fantasy_bundesliga.sqlite`.
5. Verify the allow-list and secret/path scan.
6. Commit the database change and push `main`. Streamlit Community Cloud
   automatically redeploys the new commit.
7. Open the public URL and verify the three public tabs, player totals, and match
   statistics. Confirm that no Ingestion, My Team, Data quality, approval,
   publication, matching-decision, notes, or transfer controls appear.

## Manual redeploy

Use **App settings → Reboot app** to restart the current commit. For a code or
database update, push the intended commit to `main`; Community Cloud redeploys
from GitHub automatically.

## Rollback

Revert the deployment repository to the last known-good commit, push `main`,
and wait for the automatic redeploy. If an immediate containment step is
needed, make the app private from **App settings → Sharing** while investigating.
Never copy the working local database into the deployment repository as a
rollback shortcut.
