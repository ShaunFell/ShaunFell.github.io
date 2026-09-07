# shaundbfell.com

Personal website of Shaun D. B. Fell. Built with [Jekyll](https://jekyllrb.com),
deployed with GitHub Pages, and kept up to date by a scheduled GitHub Action
that syncs the publication list from INSPIRE-HEP.

## Layout

| Path | What it is |
|---|---|
| `_data/profile.yml` | Name, position, bio, links, research areas. Edit this first. |
| `_data/publications.yml` | Publication list. **Auto-maintained** (see below). |
| `_data/news.yml`, `experience.yml`, `education.yml`, `talks.yml`, `teaching.yml` | Everything else on the CV and home page. |
| `_writing/*.md` | Long-form essays. Add a Markdown file to add an essay. |
| `index.html`, `publications.md`, `cv.md`, `writing.md` | The pages. Mostly Liquid templates over the data files. |
| `_layouts/`, `_includes/` | Page skeletons and reusable snippets (header, footer, publication card, icons). |
| `assets/css/main.css` | The stylesheet. Hand-written, no framework. Light and dark themes. |
| `assets/img/publications/` | First-page thumbnails, generated automatically. |
| `scripts/update_publications.py` | The publication sync script. |
| `.github/workflows/` | CI: `deploy.yml` builds and publishes; `update-publications.yml` runs the sync weekly. |

## Publication automation

`scripts/update_publications.py` runs every Monday (and on demand from the
Actions tab). It:

1. Queries INSPIRE-HEP for every record by the author (`publications.inspire_bai`
   in `_config.yml`) and cross-checks ORCID (`publications.orcid`) for anything
   INSPIRE has not indexed.
2. Diffs against `_data/publications.yml`. New papers are added. For existing
   papers only citation counts and journal details are refreshed. Fields you
   edit by hand (`description`, `thumbnail`, `featured`, `hidden`, `code`,
   `title`) are never overwritten.
3. Downloads each new paper's arXiv PDF and renders the first page to a PNG
   thumbnail. Works without an arXiv id get a generated placeholder card.
4. Writes a two-sentence, plain-English description with the Claude API
   (`claude-opus-5`). If the `ANTHROPIC_API_KEY` secret is missing or the call
   fails, the first sentences of the abstract are used instead, so the
   workflow never breaks because of the API.
5. Commits the result and triggers a site deploy.

### One-time setup

> **The weekly schedule only runs from the repository's default branch.** GitHub
> ignores `schedule:` triggers on every other branch. The site lives on `source`,
> so either make `source` the default branch (*Settings → General → Default
> branch*), or move the site to `main` and point Pages at it. Until one of those
> is done, the sync will only run when started by hand.


1. **Nothing is required to keep deploying the way you do now.** GitHub Pages is
   set to "deploy from a branch" (`source`), and it builds this site with its own
   Jekyll exactly as before. Merge into `source` and it goes live.
2. **Add the API key** (optional but recommended): repository *Settings →
   Secrets and variables → Actions → New repository secret*, name
   `ANTHROPIC_API_KEY`. Without it the sync still runs and uses abstract
   excerpts as descriptions. See "The API key" below for local use.
3. Run *Actions → Update publications → Run workflow* once to confirm.

### Testing the automation end to end

You do not have to wait for a new paper. Tell the run to forget one existing
entry; it will then re-discover that paper on INSPIRE, download the PDF, render
the thumbnail, write a description with Claude, commit, and trigger a deploy:

```bash
gh workflow run "Update publications" -f forget=2608.10800
gh run watch            # follow the run
git pull                # see the bot's commit
```

Or in the browser: *Actions → Update publications → Run workflow*, fill in the
"forget" box. The run's log ends with a line such as
`Descriptions: 1 written by Claude, 0 taken from abstracts`. If you prefer the
hand-written description, revert the bot's change to that entry; the script
never overwrites an existing description.

Note that GitHub disables scheduled workflows in repositories with no commits
for 60 days and emails you first; re-enable it from the Actions tab.

### How deployment works

`deploy.yml` checks which Pages mode the repository is in and does the right
thing:

| Pages setting | On your own pushes | After the weekly publication sync |
|---|---|---|
| Deploy from a branch (current) | GitHub builds the site itself; the workflow does nothing. | GitHub ignores pushes made by bots, so the workflow requests a Pages build through the API. |
| GitHub Actions | The workflow builds with the `github-pages` gem and deploys the artifact. | Same, triggered by the sync workflow. |

Switching to the "GitHub Actions" mode is optional (*Settings → Pages → Build
and deployment → Source*). It gives you build logs and a deploy history in the
Actions tab; the site output is identical.

### The API key

The key is never stored in the repository or in a file.

| Where | How the script gets it |
|---|---|
| GitHub Actions | The `ANTHROPIC_API_KEY` repository secret (encrypted by GitHub, masked in logs, unavailable to forks). |
| Your machine | The operating system's credential store via the `keyring` library: Secret Service / KWallet / GNOME Keyring on Linux, Keychain on macOS, Credential Locker on Windows. |

Store it once (the prompt hides your input, so the key never lands in shell
history):

```bash
.venv/bin/python scripts/update_publications.py --set-key
.venv/bin/python scripts/update_publications.py --check-api   # one small test call
```

`--delete-key` removes it again. An exported `ANTHROPIC_API_KEY` always takes
precedence over the keyring, which is what CI relies on.

Create the key **inside a workspace** in the Anthropic Console (Settings →
Workspaces), ideally a dedicated one with a spend limit. A key created at
organisation level is not tied to a workspace and the API rejects it unless a
workspace is named; in that case set `publications.anthropic_workspace_id` in
`_config.yml` (and the `ANTHROPIC_WORKSPACE_ID` repository *variable* for
Actions). Do not put the key in
a `.env` file: anything running as your user could read it in plaintext.

### Running locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt
python scripts/update_publications.py --dry-run   # see what would change
python scripts/update_publications.py             # apply
```

Useful flags: `--regen-thumbnails`, `--regen-descriptions`, `--no-descriptions`,
`--check-api`.

### Editing the list by hand

Open `_data/publications.yml`. Each entry looks like:

```yaml
- id: '2104.06488'          # stable key (arXiv id, DOI, or inspire:<recid>) - do not change
  title: Positive energy warp drive from hidden geometric structures
  authors: [S. D. B. Fell, L. Heisenberg]
  year: 2021
  type: article             # article | preprint | thesis | software | book
  venue: Classical and Quantum Gravity
  doi: 10.1088/1361-6382/ac0e47
  arxiv: '2104.06488'
  citations: 32             # refreshed automatically
  description: ...          # yours to edit; the script will not touch it
  thumbnail: /assets/img/publications/2104.06488.png
  code: https://github.com/...   # optional, adds a "Code" button
  featured: true            # show on the home page
  hidden: false             # hide everywhere
```

## Local preview

```bash
bundle install
bundle exec jekyll serve --livereload
```

The `Gemfile` uses the `github-pages` gem, so a local build matches what
GitHub Pages produces.

Or, without installing Ruby:

```bash
podman run --rm -it -p 4000:4000 -v "$PWD":/srv:Z -w /srv docker.io/library/ruby:3.3-slim \
  sh -c "apt-get update -qq && apt-get install -y -qq build-essential git >/dev/null && bundle install && bundle exec jekyll serve --host 0.0.0.0"
```

## Credits

Images: M87* by the [EHT Collaboration](https://eventhorizontelescope.org)
(CC BY 4.0); Einstein ring and quasar images courtesy NASA/ESA Hubble.
