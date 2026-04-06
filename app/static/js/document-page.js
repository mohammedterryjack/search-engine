(() => {
  const { sourceRootId, documentId } = window.DOCUMENT_VIEW_CONFIG || {};
  if (!sourceRootId || !documentId) {
    console.error('Missing document view configuration');
    return;
  }

  const resultsContainer = document.querySelector('[data-search-results]');
  const metaElement = document.querySelector('[data-results-meta]');
  const errorElement = document.querySelector('[data-results-error]');
  const titleElement = document.querySelector('[data-document-title]');
  const endpoint = `/api/sources/${sourceRootId}/documents/${documentId}`;

  const escapeHtml = (value = '') => {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  };

  const capitalize = (value = '') => (value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : '');

  const truncateText = (text = '', limit = 320) => {
    if (text.length <= limit) {
      return text;
    }
    return `${text.slice(0, limit - 1).replace(/\s+$/, '')}\u2026`;
  };

  const deriveDisplayText = (result) => {
    const text = (result.text_content || '').trim();
    const section = (result.section_name || '').trim();
    if (text) {
      return text;
    }
    if (result.unit_type === 'figure' && section) {
      return `Figure in ${section}`;
    }
    if (result.unit_type === 'table' && section) {
      return `Table in ${section}`;
    }
    if (result.unit_type === 'figure') {
      return 'Figure';
    }
    if (result.unit_type === 'table') {
      return 'Table';
    }
    return '';
  };

  const renderResultCard = (result) => {
    const sectionLabel = result.section_name || 'Untitled';
    const titleText = result.unit_type === 'section'
      ? sectionLabel
      : `${capitalize(result.unit_type)} · ${sectionLabel}`;
    const displayText = deriveDisplayText(result);
    const snippet = escapeHtml(truncateText(displayText));
    const subtitleParts = [`<span>${escapeHtml(result.unit_type)}</span>`];
    if (typeof result.page_number === 'number' && !Number.isNaN(result.page_number)) {
      subtitleParts.push(`<span>Page ${result.page_number}</span>`);
    }
    const figureHtml = result.image_data
      ? `<div class="result-figure">
        <img
          src="data:${result.image_mime || 'image/png'};base64,${result.image_data}"
          alt="${escapeHtml(sectionLabel)}"
          loading="lazy"
          decoding="async"
        >
      </div>`
      : '';
    return `
      <article class="result-card">
        <h2 class="result-title">
          <a href="/open/${result.source_root_id}/${result.content_unit_id}">
            ${escapeHtml(titleText)}
          </a>
        </h2>
        <div class="result-subtitle">
          ${subtitleParts.join('')}
        </div>
        <p
          class="result-snippet"
          title="Click to expand"
          data-full-text="${escapeHtml(displayText)}"
        >${snippet}</p>
        <div class="result-summary-container" data-result-summary>
          <button
            class="result-summarize-btn"
            data-summarize-result
            data-result-text="${escapeHtml(result.text_content || displayText)}"
            title="summarise"
            aria-label="summarise"
          >✨</button>
          <div class="result-summary-content" data-result-summary-content style="display: none;"></div>
        </div>
        ${figureHtml}
      </article>
    `;
  };

  const renderResults = (results) => {
    if (!resultsContainer) {
      return;
    }
    if (!results.length) {
      resultsContainer.innerHTML = '<p class="empty-state">No content units found.</p>';
      return;
    }
    resultsContainer.innerHTML = results.map(renderResultCard).join('');
    attachSummarizeListeners();
    attachSnippetListeners();
  };

  const renderMeta = (count) => {
    if (!metaElement) {
      return;
    }
    metaElement.textContent = `${count} content unit${count === 1 ? '' : 's'}`;
  };

  const renderTitle = () => {
    if (!titleElement) {
      return;
    }
    titleElement.textContent = 'Document View';
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
      renderTitle();
      renderMeta(data.results.length);
      renderResults(data.results);
      renderError(null);
    } catch (error) {
      console.error('Document load failed', error);
      renderError(error.message);
    }
  };

  // Handle per-result summarization
  const handleResultSummarize = async (event) => {
    const button = event.currentTarget;
    const card = button.closest('.result-card');
    if (!card) return;

    const text = button.dataset.resultText;
    const summaryContainer = card.querySelector('[data-result-summary]');
    const summaryContent = card.querySelector('[data-result-summary-content]');
    if (!text || !summaryContent || !summaryContainer) return;

    // Toggle if already shown
    if (summaryContent.style.display !== 'none') {
      summaryContent.style.display = 'none';
      summaryContainer.classList.remove('expanded');
      return;
    }

    // Show loading state and expand container
    summaryContainer.classList.add('expanded');
    summaryContent.innerHTML = '<span class="summary-loading">Generating summary...</span>';
    summaryContent.style.display = 'block';

    try {
      const response = await fetch('/api/summarize-single', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });

      if (!response.ok) {
        summaryContent.innerHTML = '<span class="summary-error">Failed to generate summary</span>';
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let summary = '';

      summaryContent.innerHTML = ''; // Clear loading message

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        const chunk = decoder.decode(value, { stream: true });
        summary += chunk;
        summaryContent.textContent = summary;
      }
    } catch (err) {
      console.error('Result summary fetch failed', err);
      summaryContent.innerHTML = '<span class="summary-error">Failed to generate summary</span>';
    }
  };

  // Handle snippet expansion on click
  const handleSnippetExpand = (event) => {
    const snippet = event.currentTarget;
    const isExpanded = snippet.classList.contains('expanded');

    if (isExpanded) {
      // Collapse - restore original HTML
      const originalHtml = snippet.dataset.originalHtml;
      if (originalHtml) {
        snippet.innerHTML = originalHtml;
      }
      snippet.classList.remove('expanded');
      snippet.title = 'Click to expand';
    } else {
      // Expand - store original and show full text
      snippet.dataset.originalHtml = snippet.innerHTML;
      const fullText = snippet.dataset.fullText;
      if (fullText) {
        snippet.textContent = fullText;
      }
      snippet.classList.add('expanded');
      snippet.title = 'Click to collapse';
    }
  };

  // Attach listeners to existing buttons and snippets
  const attachSummarizeListeners = () => {
    document.querySelectorAll('[data-summarize-result]').forEach((button) => {
      button.addEventListener('click', handleResultSummarize);
    });
  };

  const attachSnippetListeners = () => {
    document.querySelectorAll('.result-snippet').forEach((snippet) => {
      snippet.addEventListener('click', handleSnippetExpand);
    });
  };

  // Load the document on page load
  loadDocument();

  // Allow navigation to search by submitting the form
  const form = document.querySelector('[data-search-form]');
  if (form) {
    form.addEventListener('submit', (event) => {
      // Let the form submit naturally to /search
    });
  }
})();
