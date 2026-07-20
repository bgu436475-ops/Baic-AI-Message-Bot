# AI News Scheduler

This Worker triggers `bgu436475-ops/Baic-AI-Message-Bot` every day at 01:05 UTC / 09:05 Asia/Shanghai. GitHub Actions retains its native schedules as fallbacks.

## 1. Create the GitHub token

Create a fine-grained personal access token for only `bgu436475-ops/Baic-AI-Message-Bot`. Grant `Contents: Read and write`; do not grant organization or account permissions.

## 2. Test locally

```bash
npm install
npm test
npx wrangler deploy --dry-run
```

## 3. Sign in and save the secret

```bash
npx wrangler login
npx wrangler secret put GITHUB_DISPATCH_TOKEN
```

Paste the token only into Wrangler's protected prompt. Do not create `.env`, `.dev.vars`, screenshots, or chat messages containing the token.

## 4. Deploy

```bash
npm run deploy
```

After deployment, confirm that the Cron Trigger is `5 1 * * *` and observability is enabled.

## 5. Validate without sending a second digest

Use Wrangler's local scheduled route only before the day's digest, or rely on the next real 09:05 run. In GitHub Actions, the external run must show event `repository_dispatch`; a later `schedule` run must be skipped by the daily guard after the day's digest exists.
