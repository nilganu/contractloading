# Deployment Guide — Vercel (frontend) + Render (backend)

Two separate services. Frontend is a static Vite build hosted on
Vercel. Backend is a FastAPI Python service hosted on Render with a
persistent disk for SQLite + uploads.

## 0. Prerequisites

- GitHub repo with this project pushed to it
- Vercel account linked to that GitHub account
- Render account linked to that GitHub account
- OpenAI API key with access to whichever model you set in `OPENAI_MODEL_MINI`

## 1. Push the repo to GitHub

```powershell
cd "c:/new HotelContract"
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-user>/<your-repo>.git
git push -u origin main
```

The `.gitignore` already excludes `.env`, the SQLite DB, the upload
storage, and `node_modules` — your OpenAI key and uploads won't be
pushed.

## 2. Deploy the backend to Render

1. In Render, click **New → Blueprint** and point it at your GitHub
   repo. Render reads `render.yaml` at the repo root and provisions:
   - One Web Service (`hotel-contract-backend`)
   - One 1 GB persistent Disk mounted at `/var/data`
2. Before the first deploy succeeds, set these two **secret** env vars
   on the service:
   - `OPENAI_API_KEY` — your OpenAI key
   - `ALLOWED_ORIGINS` — `https://<your-vercel-domain>,http://localhost:5173`
3. Click **Apply / Create Resources**. First build takes ~3 min.
4. Note the backend URL Render gives you, e.g.
   `https://hotel-contract-backend.onrender.com`. Smoke test:
   ```
   curl https://hotel-contract-backend.onrender.com/api/health
   {"status":"ok"}
   ```

### Render gotchas

- Free tier sleeps after 15 min idle (cold start ~30 s). For
  production-ish use, upgrade the service to Starter ($7/mo).
- Long extractions (Volonline 15-hotel = ~5 min) work fine — Render
  has no function-timeout limit; it's a real server.
- Persistent disk costs $0.25/GB-month after the first GB.

## 3. Deploy the frontend to Vercel

1. In Vercel, click **Add New → Project** and import the same GitHub
   repo. `vercel.json` at the repo root tells Vercel to build only the
   `frontend/` directory.
2. Set the project-level env var:
   - `VITE_API_BASE` = `https://hotel-contract-backend.onrender.com/api`
   (the URL Render gave you in step 2, with `/api` appended)
3. Deploy. Vercel will run `cd frontend && npm install && npm run build`
   and serve `frontend/dist/`. ~90 s build.
4. Vercel will give you a URL like `https://your-project.vercel.app`.
   Go back to Render and set `ALLOWED_ORIGINS` to include that exact
   URL. Redeploy the backend (or hit "Manual Deploy" in Render).

## 4. Verify end-to-end

- Open the Vercel URL in a browser.
- Upload a contract.
- Check the backend logs in Render's dashboard — you should see
  per-hotel extraction lines.
- Download the generated bundle.

## 5. Updating the deployment

Both Vercel and Render auto-deploy on `git push origin main` thanks to
the GitHub integration. Backend redeploys in ~3 min, frontend in
~90 s.

## Local dev still works

`start.bat` still launches both services locally:
- Backend on `http://127.0.0.1:8001`
- Frontend on `http://127.0.0.1:5175`, proxying `/api` → backend

The `VITE_API_BASE` env var is only used in production builds.

## Cost rough estimate (June 2026)

- Vercel: free tier
- Render starter ($7/mo) + 1 GB disk ($0.25/mo after the first GB): **~$7/mo**
- OpenAI: variable — `gpt-5.4` runs $1–$10 per Volonline-15-hotel
  extraction depending on retries + verifier coverage

## Switching to Postgres later

When SQLite + disk feels limiting, swap to Render's managed Postgres:

1. Add a Render Postgres service (free tier available).
2. In the backend service env vars, set `DATABASE_URL` to the
   `Internal Connection String` Render gives you. SQLAlchemy uses the
   same code path; nothing else changes.
3. Drop the persistent disk if you don't also need file storage.
