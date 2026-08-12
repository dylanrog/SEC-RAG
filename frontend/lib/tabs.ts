export type TabState = {
  /** Display order. Deliberately stable so the tab strip never reshuffles. */
  open: string[];
  active: string | null;
  /** Most-recently-active first. Drives eviction only. */
  recency: string[];
};

/**
 * A real 10-K's viewer_html is ~800 KB, and open tabs stay mounted so each
 * keeps its scroll position. Three is the point where that stops being free.
 */
export const MAX_TABS = 3;

export const initialTabState: TabState = { open: [], active: null, recency: [] };

export function openTab(state: TabState, accession: string): TabState {
  const recency = [accession, ...state.recency.filter((a) => a !== accession)];

  if (state.open.includes(accession)) {
    return { open: state.open, active: accession, recency };
  }

  let open = [...state.open, accession];
  if (open.length > MAX_TABS) {
    const evicted = [...recency].reverse().find((a) => open.includes(a));
    if (evicted !== undefined) {
      open = open.filter((a) => a !== evicted);
      return { open, active: accession, recency: recency.filter((a) => a !== evicted) };
    }
  }
  return { open, active: accession, recency };
}

export function closeTab(state: TabState, accession: string): TabState {
  const open = state.open.filter((a) => a !== accession);
  const recency = state.recency.filter((a) => a !== accession);
  const active = state.active === accession ? (recency[0] ?? null) : state.active;
  return { open, active, recency };
}
