(() => {
  const form = document.querySelector('[data-search-form]');
  if (!form) {
    return;
  }

  const resultsContainer = document.querySelector('[data-search-results]');
  const metaElement = document.querySelector('[data-results-meta]');
  const errorElement = document.querySelector('[data-results-error]');
  const warningElement = document.querySelector('[data-results-warning]');
  const summaryBox = document.querySelector('[data-summary-box]');
  const summaryContent = document.querySelector('[data-summary-content]');
  const endpoint = '/api/search';
  const summarizeEndpoint = '/api/summarize';

  const escapeHtml = (value = '') => {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
  };

  const nl2br = (value = '') => {
    return escapeHtml(value).replace(/\n/g, '<br>\n');
  };

  const capitalize = (value = '') => (value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : '');

  const showSummaryLoading = () => {
    if (!summaryBox || !summaryContent) return;
    summaryContent.innerHTML = '<span class="summary-loading">Generating summary...</span>';
    summaryBox.dataset.visible = 'true';
  };

  const fetchSummary = async (query, results, topN) => {
    if (!query || !results.length || !topN) {
      if (summaryBox) summaryBox.dataset.visible = 'false';
      return;
    }
    showSummaryLoading();
    try {
      const response = await fetch(summarizeEndpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: query, results, summarizer_top_n: topN }),
      });
      
      if (!response.ok) {
        if (summaryBox) summaryBox.dataset.visible = 'false';
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
        summaryContent.innerHTML = nl2br(summary);
      }
    } catch (err) {
      console.error('Summary fetch failed', err);
      if (summaryBox) summaryBox.dataset.visible = 'false';
    }
  };

  const renderResultCard = (result) => {
    const sectionLabel = result.section_name || result.filename || '';
    const titleText = result.unit_type === 'section'
      ? sectionLabel
      : `${capitalize(result.unit_type)} · ${sectionLabel}`;
    const snippet = result.highlighted_text || escapeHtml(result.display_text || '');
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
        <p class="result-snippet">${snippet}</p>
        ${figureHtml}
      </article>
    `;
  };

  const renderResults = (results, query) => {
    if (!resultsContainer) {
      return;
    }
    if (!results.length) {
      resultsContainer.innerHTML = query
        ? '<p class="empty-state">No indexed sections matched that query yet.</p>'
        : '';
      return;
    }
    resultsContainer.innerHTML = results.map(renderResultCard).join('');
  };

  const renderMeta = (count, query) => {
    if (!metaElement) {
      return;
    }
    if (query) {
      metaElement.textContent = `${count} result${count === 1 ? '' : 's'}`;
    } else {
      metaElement.textContent = '';
    }
  };

  const renderMessages = (error, warning) => {
    if (errorElement) {
      errorElement.textContent = error || '';
      errorElement.dataset.visible = error ? 'true' : 'false';
    }
    if (warningElement) {
      warningElement.textContent = warning || '';
      warningElement.dataset.visible = warning ? 'true' : 'false';
    }
  };

  const gatherPayload = () => {
    const queryInput = form.querySelector('[name="q"]');
    const slider = form.querySelector('[name="vector_min_score"]');
    const topNSlider = form.querySelector('[name="summarizer_top_n"]');
    const selectedSources = Array.from(form.querySelectorAll('input[name="source"]:checked'))
      .map((input) => Number(input.value))
      .filter((value) => !Number.isNaN(value));
    const selectedUnits = Array.from(form.querySelectorAll('input[name="unit_type"]:checked'))
      .map((input) => input.value);
    return {
      q: queryInput ? queryInput.value : '',
      source: selectedSources,
      unit_type: selectedUnits,
      vector_min_score: slider ? Number(slider.value) : undefined,
      summarizer_top_n: topNSlider ? Number(topNSlider.value) : 5,
    };
  };

  const updateUrl = (payload) => {
    const url = new URL(window.location.href);
    const params = url.searchParams;
    if (payload.q) {
      params.set('q', payload.q);
    } else {
      params.delete('q');
    }
    params.delete('source');
    payload.source.forEach((value) => params.append('source', String(value)));
    params.delete('unit_type');
    payload.unit_type.forEach((value) => params.append('unit_type', value));
    if (typeof payload.vector_min_score === 'number') {
      params.set('vector_min_score', payload.vector_min_score.toFixed(2));
    } else {
      params.delete('vector_min_score');
    }
    if (typeof payload.summarizer_top_n === 'number') {
      params.set('summarizer_top_n', String(payload.summarizer_top_n));
    } else {
      params.delete('summarizer_top_n');
    }
    const queryString = params.toString();
    window.history.replaceState({}, '', `${url.pathname}${queryString ? `?${queryString}` : ''}`);
  };

  const performSearch = async (event) => {
    if (event) {
      event.preventDefault();
    }
    const payload = gatherPayload();
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(`Search failed (${response.status})`);
      }
      const data = await response.json();
      renderMessages(data.error, data.warning);
      renderMeta(data.results.length, payload.q);
      renderResults(data.results, payload.q);
      updateUrl(payload);
      
      // Async fetch summary after results are shown
      fetchSummary(payload.q, data.results, payload.summarizer_top_n);
    } catch (error) {
      renderMessages(error.message, null);
      if (summaryBox) summaryBox.dataset.visible = 'false';
    }
  };

  form.addEventListener('submit', performSearch);

  // Initial load check if results already exist from SSR
  const initialPayload = gatherPayload();
  if (initialPayload.q && resultsContainer && resultsContainer.children.length > 0) {
    const initialResults = Array.from(resultsContainer.querySelectorAll('.result-card')).map((card) => {
      return {
          display_text: card.querySelector('.result-snippet').textContent,
      };
    });
    fetchSummary(initialPayload.q, initialResults, initialPayload.summarizer_top_n);
  }
})();
