# tigris-static-assets

Deploy static assets (CSS, JS, fonts, build artifacts) to Tigris for global CDN delivery.

## What It Covers

- **Cache headers** — `Cache-Control`, ETags, immutable caching
- **Next.js** — `assetPrefix` configuration, `_next/static` deployment
- **Remix** — Vite `base` URL, build output upload
- **Rails** — Sprockets/Propshaft sync, `config.asset_host`
- **Django** — `collectstatic` with S3StaticStorage backend
- **Laravel** — Vite/Mix asset upload, `ASSET_URL`
- **Express** — static redirect pattern to Tigris
- **Cache-busting** — content hashes, query strings, directory versioning

## Installation

**Claude Code:**

```bash
cp -r skills/tigris-static-assets ~/.claude/skills/
```

**claude.ai:**

Add `skills/tigris-static-assets` to project knowledge or paste `SKILL.md` contents into the conversation.

## Usage

This skill activates when you mention:

- "Static assets", "deploy CSS", "deploy JS"
- "Asset CDN", "fonts Tigris", "asset hosting"
- "Cache headers", "asset pipeline"

## Example Prompts

```text
Deploy my Next.js static assets to Tigris CDN
```

```text
Set up Django collectstatic with Tigris
```

```text
Configure cache headers for static files on Tigris
```

## License

MIT
