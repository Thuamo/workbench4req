// Authentication boundaries must discard the old page and its in-memory query cache.
export function refreshAtHome() {
  window.history.replaceState(null,'',window.location.pathname+window.location.search+'#page=dashboard');
  window.location.reload();
}
