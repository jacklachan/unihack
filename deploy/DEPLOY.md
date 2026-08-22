# Putting CALIPER on a public URL

The submission form asks for a **live prototype link**. The Space is already
created at:

```
https://huggingface.co/spaces/jacklachan/unihack
```

This is the Gradio SDK, not Docker. That matters: Hugging Face now puts *CPU
basic* behind a PRO subscription, and the only free hardware left — **ZeroGPU** —
is offered on the Gradio SDK. So the front end for the Space is `app.py`, a
Gradio wrapper around the same `caliper.pipeline.Pipeline` the CLI calls. The
pipeline itself is untouched and still imports nothing outside the standard
library; `gradio` is the one dependency, and it only exists to put a URL in front
of it.

---

## 1 · Push it

Hugging Face reads its configuration from the frontmatter of `README.md` **at the
repository root**. The GitHub README is a different document and should stay as
it is, so the Space gets its own branch:

```bash
bash deploy/push_space.sh
```

That script creates (or resets) a local `space` branch, swaps in
`deploy/README_SPACE.md` as the root `README.md`, commits, and pushes to the
Space. It leaves you back on `main` with the GitHub README untouched.

**Git will ask for credentials.** Username is `jacklachan`; the password is a
Hugging Face **access token with write permission**, from
<https://huggingface.co/settings/tokens>. Paste the token into the password
prompt — not your account password, which HF no longer accepts over git.

## 2 · Watch the build

Open the Space and click **Logs**. The first build installs Gradio and takes
2–4 minutes. When the status reads **Running**, the URL is live.

If the build fails, the two things worth checking first are the `sdk_version` in
`deploy/README_SPACE.md` (it must be a version HF actually offers) and whether
`requirements.txt` reached the root of the Space repo.

**On ZeroGPU hardware.** ZeroGPU is the only free tier left, and it is fine here:
CALIPER is pure CPU and never asks for a GPU, so no `@spaces.GPU` function is
needed and none exists. If the logs ever complain about the missing `spaces`
package, add `spaces` to `requirements.txt` — it does not change the pipeline.

## 3 · Check it before you paste the link into the form

Open the URL **in a private window**, so you are testing what a judge sees rather
than what your logged-in session sees.

- It loads with no login.
- The catalogue fills on its own — 1,000 rows, no button pressed. *(The Space
  runs the real pipeline on page load; it takes a few seconds.)*
- Click a row. The evidence panel underneath shows a rule id and a quoted source
  substring. **This is the thing being demonstrated — make sure it works.**
- **Try a file with completely different column names** returns 40 rows and
  reports the detected column roles.
- **Download the delivery file** gives a CSV that opens with 252 columns.

## 4 · Two things that will bite you on the day

**It sleeps.** A free Space idles out after ~48 hours of no traffic and takes
20–30 seconds to wake. Open your own link the evening before judging, and again
on the morning of, so the judge does not meet a cold boot.

**No key ships in it.** `.env` is gitignored and never leaves your machine. A
judge who wants the AI path pastes their own key into the form on the page; it
lives in process memory for that request and is never written to disk, logged, or
returned to the browser.

To ship a change, commit to `main` as usual and run `bash deploy/push_space.sh`
again.

---

## If you would rather not use Hugging Face

`deploy/Dockerfile` still builds the **stdlib** web console — `python -m caliper
serve`, no Gradio, no third-party packages at all. Any host that runs a container
works, because the app reads `HOST` and `PORT` from the environment.

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
