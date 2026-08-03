/** Plain global class, defined in app/globals.css. It cannot be a Tailwind
 *  utility: these spans come from dangerouslySetInnerHTML, so Tailwind never
 *  sees them at build time. */
export const HIGHLIGHT_CLASS = "cited-sentence";

/**
 * Highlight the sentences a citation resolves to, inside already-mounted HTML.
 *
 * Operates on the live container rather than rewriting the HTML string,
 * because a real 10-K's viewer_html is ~818 KB -- re-parsing that on every
 * citation click would be visibly slow, and regex-over-HTML is fragile.
 * Injection happens once per filing; this runs on every sid change.
 */
export function applyHighlight(container: HTMLElement, sids: number[]): void {
  container
    .querySelectorAll(`.${HIGHLIGHT_CLASS}`)
    .forEach((el) => el.classList.remove(HIGHLIGHT_CLASS));

  // Collected into an array rather than tracked in a `let` that a callback
  // assigns: TypeScript narrows such a variable to `null` at the use site and
  // reports `scrollIntoView` on type `never`.
  const cited: Element[] = [];
  for (const sid of sids) {
    container.querySelectorAll(`[data-sid="${sid}"]`).forEach((el) => {
      el.classList.add(HIGHLIGHT_CLASS);
      cited.push(el);
    });
  }
  cited[0]?.scrollIntoView({ behavior: "smooth", block: "center" });
}
