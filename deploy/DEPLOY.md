# Hosting CALIPER so judges can click a link

The submission form asks for a **live prototype link**. This puts one up on
Hugging Face Spaces in about ten minutes, free, on a permanent URL.

Spaces is the right host here because the app is a plain Python HTTP server
with **no third-party packages** — the container is stock `python:3.12-slim`
plus the source, so there is no dependency that can break at build time.

---

## 1 · Create the Space

1. Sign in at **huggingface.co** (free).
2. **New** → **Space**.
3. Fill in:
   - **Owner** — your username
   - **Space name** — `caliper` *(URL becomes `huggingface.co/spaces/<you>/caliper`)*
   - **License** — MIT
   - **SDK** — **Docker** → *Blank*
   - **Hardware** — CPU basic (free)
   - **Visibility** — **Public** *(judges must be able to open it without a login)*
4. **Create Space.**

## 2 · Push the code

Hugging Face gives you a git remote. From the project root:

```bash
git remote add space https://huggingface.co/spaces/<YOUR-USERNAME>/caliper
```

The Space needs the `Dockerfile` and its `README.md` at the **repository root**,
not inside `deploy/`, so copy them up before pushing:

```bash
cp deploy/Dockerfile        ./Dockerfile
cp deploy/README_SPACE.md   ./README_HF.md
```

Spaces reads configuration from the root `README.md` frontmatter. Keep the
GitHub README as it is and push a Space-specific branch instead:

```bash
git checkout -b space
cp deploy/README_SPACE.md README.md          # Space needs its frontmatter here
git add Dockerfile README.md
git commit -m "Space: Dockerfile and Space README"
git push space space:main
git checkout main                            # GitHub README is untouched
```

First build takes 3–6 minutes. Watch the **Logs** tab. When it says *Running*,
your URL is live:

```
https://huggingface.co/spaces/<YOUR-USERNAME>/caliper
```

## 3 · Check it before you submit the link

- Opens without a login, in a private/incognito window.
- The setup screen appears → choose **Deterministic only** → **Continue**.
- **Catalogue** lists 1,000 rows.
- Click a row, click a cell — the evidence panel shows a rule id and the source
  substring. *(This is the thing to demo; make sure it works.)*
- **Export delivery CSV** downloads a 252-column file.

## 4 · Notes that matter

**It sleeps.** Free Spaces idle out after ~48 hours of no traffic and take
20–30 seconds to wake. Open your own link a few hours before judging so it is
warm, and again on the morning of.

**No key is stored in the image.** `.env` is gitignored and never ships. If a
judge wants the AI path they paste their own key into the first screen; it lives
in process memory for that session only.

**Rebuilding.** Push to the `space` branch again and the Space rebuilds:

```bash
git checkout space && git merge main && git push space space:main && git checkout main
```

---

## If you would rather not use Hugging Face

Any host that runs a container works, because the app reads `PORT` and `HOST`
from the environment.

| Host | Notes |
|---|---|
| **Render** | Free web service, Docker runtime. Sleeps on the free tier. |
| **Railway** | Docker, generous trial, no sleeping. |
| **Fly.io** | `fly launch` detects the Dockerfile. Free allowance. |

Locally, for a live demo without any host:

```bash
python -m caliper serve --host 0.0.0.0 --port 8765 --no-browser
```

…then expose it with `cloudflared tunnel --url http://localhost:8765`, which
gives a public HTTPS URL with no account. Good for a demo, **not** for a link
you submit — it dies when your laptop does.
