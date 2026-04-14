const STOP_WORDS = new Set([
  'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
  'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the', 'to', 'was', 'will', 'with'
]);

export const escapeHtml = (value = '') => {
  const div = document.createElement('div');
  div.textContent = value;
  return div.innerHTML;
};

export const capitalize = (value = '') => (value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : '');

export const truncateText = (text = '', limit = 320) => {
  if (text.length <= limit) {
    return text;
  }
  return `${text.slice(0, limit - 1).replace(/\s+$/, '')}\u2026`;
};

const normalizedTerms = (query = '') => {
  const tokens = String(query).match(/[A-Za-z0-9]+/g) || [];
  const normalized = tokens
    .map(token => token.toLowerCase())
    .filter(token => token && !STOP_WORDS.has(token));
  return new Set(normalized);
};

export const highlightText = (text = '', query = '') => {
  const matchedTerms = normalizedTerms(query);
  if (!matchedTerms.size) {
    return escapeHtml(text);
  }

  let result = '';
  let lastIndex = 0;
  const wordRe = /[A-Za-z0-9]+/g;
  let match;

  while ((match = wordRe.exec(text)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    result += escapeHtml(text.slice(lastIndex, start));
    const surface = match[0];
    const escapedSurface = escapeHtml(surface);
    if (matchedTerms.has(surface.toLowerCase())) {
      result += `<mark>${escapedSurface}</mark>`;
    } else {
      result += escapedSurface;
    }
    lastIndex = end;
  }

  result += escapeHtml(text.slice(lastIndex));
  return result;
};

export const renderResultCard = (result, options = {}) => {
  const {
    query = '',
  } = options;
  const sectionLabel = result.section_name || 'Untitled';
  const titleText = result.unit_type === 'section'
    ? sectionLabel
    : `${capitalize(result.unit_type)} · ${sectionLabel}`;
  const displayText = (result.text_content || '').trim();
  const renderedSnippetHtml = highlightText(displayText, query);
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
      <div class="result-path">${escapeHtml(result.document_path || '')}</div>
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
        data-query="${escapeHtml(query)}"
      >${renderedSnippetHtml}</p>
      <div class="result-summary-container" data-result-summary>
        <button
          class="result-summarize-btn"
          data-summarize-result
          data-result-text="${escapeHtml(displayText)}"
          title="summarise"
          aria-label="summarise"
        >✨</button>
        <div class="result-summary-content" data-result-summary-content style="display: none;"></div>
      </div>
      ${figureHtml}
    </article>
  `;
};

const handleResultSummarize = async (button) => {
  const card = button.closest('.result-card');
  if (!card) return;

  const text = button.dataset.resultText;
  const summaryContainer = card.querySelector('[data-result-summary]');
  const summaryContent = card.querySelector('[data-result-summary-content]');
  if (!text || !summaryContent || !summaryContainer) return;

  if (summaryContent.style.display !== 'none') {
    summaryContent.style.display = 'none';
    summaryContainer.classList.remove('expanded');
    return;
  }

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

    summaryContent.innerHTML = '';

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

const handleSnippetExpand = (snippet) => {
  const isExpanded = snippet.classList.contains('expanded');

  if (isExpanded) {
    const originalHtml = snippet.dataset.originalHtml;
    if (originalHtml) {
      snippet.innerHTML = originalHtml;
    }
    snippet.classList.remove('expanded');
    snippet.title = 'Click to expand';
    return;
  }

  snippet.dataset.originalHtml = snippet.innerHTML;
  const fullText = snippet.dataset.fullText;
  const query = snippet.dataset.query || '';
  if (fullText) {
    snippet.innerHTML = highlightText(fullText, query);
  }
  snippet.classList.add('expanded');
  snippet.title = 'Click to collapse';
};

export const bindResultInteractions = (container) => {
  if (!container || container.dataset.resultInteractionsBound === 'true') {
    return;
  }

  container.addEventListener('click', (event) => {
    const summarizeButton = event.target.closest('[data-summarize-result]');
    if (summarizeButton && container.contains(summarizeButton)) {
      handleResultSummarize(summarizeButton);
      return;
    }

    const snippet = event.target.closest('.result-snippet');
    if (snippet && container.contains(snippet)) {
      handleSnippetExpand(snippet);
    }
  });

  container.dataset.resultInteractionsBound = 'true';
};
