# Deploy the public MemoGraph demo to Hugging Face Spaces

Free, no credit card, ~10 minutes start-to-finish. The result is a public
URL like `https://huggingface.co/spaces/Indhar01/memograph-demo` that
anyone can use without installing anything.

## Prerequisites

- A Hugging Face account ([sign up](https://huggingface.co/join))
- `git` and the [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) installed locally
- An [access token](https://huggingface.co/settings/tokens) with `write` scope

## Steps

**1. Create the Space**

Go to [huggingface.co/new-space](https://huggingface.co/new-space) and fill in:

| Field | Value |
|---|---|
| Owner | your username |
| Space name | `memograph-demo` (or anything you like) |
| License | MIT |
| Select the Space SDK | **Docker → Blank** |
| Space hardware | **CPU basic — Free** |
| Visibility | Public |

Click *Create Space*.

**2. Clone the empty Space**

```bash
git clone https://huggingface.co/spaces/<your-username>/memograph-demo
cd memograph-demo
```

**3. Copy the demo recipe**

From inside the MemoGraph repo:

```bash
cp deploy/huggingface/Dockerfile /path/to/memograph-demo/
cp deploy/huggingface/README.md  /path/to/memograph-demo/
```

The `README.md` frontmatter tells HF how to run the container
(`sdk: docker`, `app_port: 8000`, etc.). Don't strip it.

**4. Push**

```bash
cd /path/to/memograph-demo
git add Dockerfile README.md
git commit -m "Initial demo deployment"
git push
```

HF starts building immediately. Watch the build log in the *Logs* tab of
your Space. First build takes ~3–5 minutes (pip download + sample vault
seed). Subsequent builds are faster thanks to HF's layer cache.

**5. Verify**

Once the Space says *Running*:

- Visit the Space URL — the MemoGraph web UI should load.
- `curl https://<your-space>.hf.space/api/health` → `{"status":"healthy"}`
- `curl -X POST https://<your-space>.hf.space/api/memories` → 403 with
  `code: READ_ONLY_MODE` (confirms the read-only gate is on).

**6. Link it from the main README**

Open a PR on the MemoGraph repo replacing the "Hosted demo" badge
placeholder with the actual URL. Conventions:

```markdown
[![Try the live demo](https://img.shields.io/badge/demo-Hugging%20Face%20Space-yellow?logo=huggingface)](https://huggingface.co/spaces/<your-username>/memograph-demo)
```

## Bumping the MemoGraph version on the Space

Edit `Dockerfile`, change `ARG MEMOGRAPH_VERSION=...`, push. HF rebuilds.
Do this whenever you release a new PyPI version that you want the public
demo to track.

## Troubleshooting

**Build fails on `pip install`**
Usually the pinned `MEMOGRAPH_VERSION` doesn't exist on PyPI yet. Verify
on [pypi.org/project/memograph/#history](https://pypi.org/project/memograph/#history).

**Space starts but `/api/health` 502s**
Open the *Logs* tab. The lifespan handler logs `Vault ingested: N
memories loaded` on success. If you see an exception, check that the
quickstart vault was created at `/home/user/demo-vault` during the build
(grep the build log for `quickstart`).

**Writes succeed when they shouldn't**
`MEMOGRAPH_READONLY=true` must be in the Dockerfile's `ENV` block. If you
removed it, anyone on the internet can mutate your demo vault. Re-add and
push.

**Free CPU tier is overloaded**
A popular demo can saturate the 2-vCPU free tier. Options:
- Upgrade the Space hardware (paid)
- Add `CACHE_CONTROL` headers in nginx in front (out of scope here)
- Move to Cloudflare Pages + a Worker (different architecture)

## What this gives you

A public, zero-install, evergreen demo URL you can paste into:

- The MemoGraph README (top of the file, above "Try it in 60 seconds")
- HackerNews Show HN posts
- ProductHunt launch
- Conference / meetup demos when wifi is bad and `pip install` would be slow
- DM responses to "wait, what does it actually do?"

That last one is the killer use case. Most lost users never get past
"install something to find out." A hosted demo removes that step entirely.
