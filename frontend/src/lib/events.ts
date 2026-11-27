/**
 * A tiny signal for "transactions changed" (a correction or an upload), so parts of the
 * page that show derived numbers, such as the review count in the nav, can refresh.
 */

const TARGET = new EventTarget();
const EVENT = "transactions-changed";

export function notifyTransactionsChanged(): void {
  TARGET.dispatchEvent(new Event(EVENT));
}

export function onTransactionsChanged(listener: () => void): () => void {
  TARGET.addEventListener(EVENT, listener);
  return () => TARGET.removeEventListener(EVENT, listener);
}
