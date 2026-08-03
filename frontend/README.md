# Frontend

Next.js (App Router) + TypeScript. One page, `/ask`: streamed answer with
citation chips on the left, the original filing with highlighted cited
sentences on the right.

## Running

The backend must be up first (see the repo root README):

    docker compose up -d          # repo root
    python -m uvicorn api.app:app --port 8000   # backend/

Then:

    npm install
    cp .env.local.example .env.local
    npm run dev

## Testing

    npm test          # vitest — lib/ logic, no browser
    npm run test:e2e  # playwright — the click-to-highlight exit criterion

`lib/` holds the logic (SSE parsing, event reduction, marker splitting,
highlighting); components are thin renderers over it. Only `lib/highlight.ts`
touches the DOM.
