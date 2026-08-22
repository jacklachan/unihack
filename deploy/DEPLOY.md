# The live prototype

**It is up:** <https://huggingface.co/spaces/jacklachan/unihack>
(direct: <https://jacklachan-unihack.hf.space>)

This is a **Gradio** Space, not Docker. That is forced, not chosen — see below.

---

## What the free tier actually allows

Worth writing down, because two reasonable-looking plans fail:

| Option | Result |
|---|---|
| Gradio/Docker Space on **cpu-basic** | **402 Payment Required.** *"hosting Gradio and Docker Spaces on free cpu-basic requires a PRO subscription."* Applies to creating a new Space and to downgrading an existing one. |
| **Static** Space | Free, but HTML/JS only — no Python backend. |
| **ZeroGPU** (`zero-a10g`) | Free, runs Python. **The only workable free option here.** |

ZeroGPU comes with a catch that is easy to miss: it refuses to start unless it
finds a `@spaces.GPU` function at import time. Without one the Space builds
cleanly, starts, and then dies with:

```
"errorMessage": "No @spaces.GPU function detected during startup"
```

CALIPER is pure CPU and never calls a GPU, so `app.py` declares one small
function purely to satisfy that check, commented as such. No GPU is ever
allocated.

## Deploying a change

`app.py` and the pipeline are the same code the CLI runs, so a normal commit to
`main` is the source of truth. To push it to the Space:

```bash
bash deploy/push_space.sh
```

The script builds a `space` branch whose root `README.md` is
`deploy/README_SPACE.md` (Hugging Face reads its configuration from that
frontmatter, and the GitHub README is a different document), pushes it, and
returns you to the branch you started on.

Git will ask for credentials: the username is your Hugging Face username and the
**password is an access token with write permission** from
<https://huggingface.co/settings/tokens> — not your account password.

If you have `huggingface_hub` installed and are already logged in, this also
works and skips the branch dance for a single file:

```bash
python -c "from huggingface_hub import HfApi; HfApi().upload_file(path_or_fileobj='app.py', path_in_repo='app.py', repo_id='jacklachan/unihack', repo_type='space', commit_message='update app')"
```

## Watching a deploy

The Space goes `BUILDING` → `APP_STARTING` → `RUNNING`, usually inside 90
seconds. Check it without opening a browser:

```bash
python -c "from huggingface_hub import HfApi; r=HfApi().space_info('jacklachan/unihack').runtime; print(r.stage, r.raw.get('errorMessage',''))"
```

A `RUNTIME_ERROR` almost always has a one-line explanation in
`raw['errorMessage']`, which is more useful than the run log — the log can look
like a clean startup while the container is being torn down.

## Before submitting the link

Open it **in a private window**, so you test what a judge sees:

- Loads with no login.
- The catalogue fills on its own — 1,000 rows, no button pressed.
- Clicking a row shows a rule id and a quoted source substring underneath.
  **This is the thing being demonstrated; make sure it works.**
- *Try a file with completely different column names* returns 40 rows.
- *Download the delivery file* gives a CSV that opens with 252 columns.

## Two things that will bite you on the day

**It sleeps.** A free Space idles out after ~48 hours and takes 20–30 seconds to
wake. Open your own link the evening before judging and again that morning.

**No key ships in it.** `.env` is gitignored and never leaves your machine. A
judge who wants the AI path pastes their own key into the page; it is held in
process memory for that request only — never written to disk, logged, or
returned to the browser.

---

## Hosting it somewhere else

`deploy/Dockerfile` builds the **stdlib** web console — `python -m caliper
serve`, no Gradio, no third-party packages at all. Any host that runs a
container works, because the app reads `HOST` and `PORT` from the environment.

| Host | Notes |
|---|---|
| **Render** | Free web service, Docker runtime. Sleeps on the free tier. |
| **Railway** | Docker, generous trial, no sleeping. |
| **Fly.io** | `fly launch` detects the Dockerfile. Free allowance. |

Locally, for a live demo with no host at all:

```bash
python -m caliper serve --host 0.0.0.0 --port 8765 --no-browser
```

…then expose it with `cloudflared tunnel --url http://localhost:8765`, which
gives a public HTTPS URL and needs no account. Good for a demo; **not** for a
link you submit, because it dies when your laptop does.
