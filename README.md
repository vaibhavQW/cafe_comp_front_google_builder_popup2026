# Cafe Companion — backend

FastAPI + **Google Cloud SQL (PostgreSQL)** + **Gemini API**, deployed on **Cloud Run**.
Frontend lives in `../../cafe_companion_website/cafe_companion_frontend`.

## What it does

| Problem | Feature |
|---|---|
| Ordering | Each table has a QR → `/c/<cafe>/t/<table>`. Menu + cart + order, no sign-in needed. |
| Wait time | Live ETA per order: simulates the queue across `BARISTAS` lanes using each item's prep time. Barista board at `/c/<cafe>/staff`. |
| Discovery | Gemini “what are you in the mood for?” recommender, aware of the current wait. |
| Connect people | Opt-in Google sign-in → you check in to the room and see others who did the same: name, photo, YouTube channel + recent videos, Blogger blogs + posts, Google Maps contributor link. |
| Understanding the room | Gemini summary of shared interests in the room + per-person conversation starters. |

### Privacy model (by design)
- Profile data comes **only from the user's own Google account with their OAuth consent** (YouTube Data API `mine=true`, Blogger `users/self`). We never look anyone up by email.
- Email is stored but **never shown** to other guests.
- You're visible only while checked in (default 3 h). Hidden users can't see others (two-way).
- Per-source share toggles, "Leave the room", and "Delete my data" endpoints.
- Google has **no API for a user's Maps reviews**, so users paste their public contributor link.

## Run locally

```bash
cp .env.example .env            # fill in GOOGLE_CLIENT_ID, GEMINI_API_KEY, JWT_SECRET
poetry install
poetry run uvicorn cafe_companion.main:app --reload --port 8080
```
By default data lives in a local SQLite file, `./cafe_companion.db`. Delete it to start fresh.

**Switching to Cloud SQL later:** set `INSTANCE_CONNECTION_NAME` (+ `DB_USER`/`DB_PASS`/`DB_NAME`) and
run `gcloud auth application-default login`, or run the Cloud SQL Auth Proxy and point `DATABASE_URL`
at `postgresql+pg8000://…@127.0.0.1:5432/cafe_companion`. No code changes needed.
Tables are created and a demo cafe (`demo`, 12 tables) is seeded on startup.
Without `GEMINI_API_KEY` the AI features fall back to simple rule-based answers.

## Google Cloud setup

```bash
PROJECT=your-project REGION=asia-south1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com sqladmin.googleapis.com \
  youtube.googleapis.com blogger.googleapis.com cloudbuild.googleapis.com

# 1. Cloud SQL
gcloud sql instances create cafe-companion-db --database-version=POSTGRES_16 \
  --region=$REGION --tier=db-f1-micro --edition=enterprise
gcloud sql databases create cafe_companion --instance=cafe-companion-db
gcloud sql users set-password postgres --instance=cafe-companion-db --password='CHANGE_ME'

# 2. OAuth client (Console → APIs & Services → Credentials → OAuth client ID → Web)
#    Authorized JavaScript origins: http://localhost:5173 and your frontend Cloud Run URL.
#    OAuth consent screen scopes: openid, email, profile, youtube.readonly, blogger.readonly
#    (youtube.readonly / blogger.readonly are sensitive scopes: add test users while in
#     "Testing", or submit for Google verification before going public.)

# 3. Gemini key: https://aistudio.google.com/apikey
```

## Deploy to Cloud Run

```bash
# Backend (use Secret Manager for DB_PASS / JWT_SECRET / GEMINI_API_KEY in real deployments)
gcloud run deploy cafe-companion-api --source . --region=$REGION --allow-unauthenticated \
  --add-cloudsql-instances=$PROJECT:$REGION:cafe-companion-db \
  --set-env-vars=INSTANCE_CONNECTION_NAME=$PROJECT:$REGION:cafe-companion-db,DB_USER=postgres,DB_PASS=CHANGE_ME,DB_NAME=cafe_companion,GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com,JWT_SECRET=$(openssl rand -hex 32),GEMINI_API_KEY=xxx,STAFF_PIN=4821,CORS_ORIGINS=https://<frontend-url>
# The Cloud Run service account needs roles/cloudsql.client.

# Frontend (from cafe_companion_frontend/) — Vite bakes env vars in at build time
docker build -t $REGION-docker.pkg.dev/$PROJECT/web/cafe-companion-web \
  --build-arg VITE_API_URL=https://<api-url> --build-arg VITE_GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com .
docker push $REGION-docker.pkg.dev/$PROJECT/web/cafe-companion-web
gcloud run deploy cafe-companion-web --image $REGION-docker.pkg.dev/$PROJECT/web/cafe-companion-web \
  --region=$REGION --allow-unauthenticated
```
Then open `https://<frontend-url>/c/demo/qr`, print the codes, and stick them on tables.

## API overview

| Method | Path | Auth |
|---|---|---|
| GET | `/api/cafes/{slug}` | – menu, current wait, people count |
| POST | `/api/cafes/{slug}/recommend` | – Gemini picks |
| POST | `/api/cafes/{slug}/orders` | optional |
| GET | `/api/orders/{token}` | order token |
| POST | `/api/auth/google` | Google access token → session JWT |
| GET/PATCH/DELETE | `/api/me` | session |
| POST/GET/DELETE | `/api/cafes/{slug}/checkin` | session |
| GET | `/api/cafes/{slug}/people[/{id}]` | session + visible check-in |
| GET | `/api/cafes/{slug}/room` | session + visible check-in (Gemini) |
| GET | `/api/cafes/{slug}/people/{id}/icebreaker` | session + visible check-in (Gemini) |
| GET/POST | `/api/cafes/{slug}/staff/orders[/{id}]` | `X-Staff-Pin` |
