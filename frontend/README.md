# Frontend

Next.js (App Router) + TypeScript app: answer pane + canonical filing viewer
with click-to-highlight citations.

Not scaffolded yet. 

Planned key pieces:
- `app/filings/[accession]/page.tsx` — HTML viewer
- `app/ask/page.tsx` — question input + streamed answer with citation markers
- `components/citation-marker.tsx` — click handler wiring answer citations to
  the viewer pane