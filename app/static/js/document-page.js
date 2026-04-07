import { bindResultInteractions, deriveDisplayText, renderResultCard } from './result-card-utils.js';

(() => {
  const { sourceRootId, documentId } = window.DOCUMENT_VIEW_CONFIG || {};
  if (!sourceRootId || !documentId) {
    console.error('Missing document view configuration');
    return;
  }

  const resultsContainer = document.querySelector('[data-search-results]');
  const metaElement = document.querySelector('[data-results-meta]');
  const errorElement = document.querySelector('[data-results-error]');
  const endpoint = `/api/sources/${sourceRootId}/documents/${documentId}`;

  const renderResults = (results) => {
    if (!resultsContainer) {
      return;
    }
    if (!results.length) {
      resultsContainer.innerHTML = '<p class="empty-state">No content units found.</p>';
      return;
    }
    resultsContainer.innerHTML = results.map((result) => renderResultCard(result, {
      summaryText: result.text_content || deriveDisplayText(result),
    })).join('');
  };

  const renderMeta = (count) => {
    if (!metaElement) {
      return;
    }
    metaElement.textContent = `${count} content unit${count === 1 ? '' : 's'}`;
  };

  const renderError = (error) => {
    if (errorElement) {
      errorElement.textContent = error || '';
      errorElement.dataset.visible = error ? 'true' : 'false';
    }
  };

  const loadDocument = async () => {
    try {
      const response = await fetch(endpoint);
      if (!response.ok) {
        throw new Error(`Failed to load document (${response.status})`);
      }
      const data = await response.json();
      renderMeta(data.results.length);
      renderResults(data.results);
      renderError(null);
    } catch (error) {
      console.error('Document load failed', error);
      renderError(error.message);
    }
  };

  bindResultInteractions(resultsContainer);
  loadDocument();
})();
