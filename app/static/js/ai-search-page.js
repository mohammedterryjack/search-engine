(() => {
  const form = document.querySelector('[data-search-form]');
  if (!form) {
    return;
  }

  const metaElement = document.querySelector('[data-results-meta]');
  const errorElement = document.querySelector('[data-results-error]');
  const warningElement = document.querySelector('[data-results-warning]');
  const answerElement = document.querySelector('[data-ai-answer]');
  const citationsSection = document.querySelector('[data-ai-citations]');
  const citationList = document.querySelector('[data-ai-citation-list]');
  const endpoint = '/api/ai-search';

  const escapeHtml = (value = '') => {
    const div = document.createElement('div');
    div.textContent = value;
    return div.innerHTML;
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

  const renderMeta = (value = '') => {
    if (metaElement) {
      metaElement.textContent = value;
    }
  };

  const renderCitations = (sources = []) => {
    if (!citationsSection || !citationList) {
      return;
    }
    if (!sources.length) {
      citationsSection.hidden = true;
      citationList.innerHTML = '';
      return;
    }
    citationsSection.hidden = false;
    citationList.innerHTML = sources.map((source) => (
      `<li><strong>[${source.id}]</strong> ${escapeHtml(source.label || '')}</li>`
    )).join('');
  };

  const gatherPayload = () => {
    const queryInput = form.querySelector('[name="q"]');
    const slider = form.querySelector('[name="vector_min_score"]');
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
    const queryString = params.toString();
    window.history.replaceState({}, '', `${url.pathname}${queryString ? `?${queryString}` : ''}`);
  };

  const handleEvent = (event) => {
    if (!event || typeof event.type !== 'string') {
      return false;
    }
    switch (event.type) {
      case 'warning':
        renderMessages(null, event.warning || '');
        return false;
      case 'error':
        renderMessages(event.error || 'AI search failed.', null);
        renderMeta('Error');
        return false;
      case 'sources':
        renderCitations(Array.isArray(event.sources) ? event.sources : []);
        return false;
      case 'answer':
        if (answerElement) {
          answerElement.textContent += event.chunk || '';
        }
        return false;
      case 'done':
        return true;
      default:
        return false;
    }
  };

  const performSearch = async (event) => {
    if (event) {
      event.preventDefault();
    }
    const payload = gatherPayload();
    renderMessages(null, null);
    renderCitations([]);
    if (answerElement) {
      answerElement.textContent = payload.q ? '' : 'Ask a question and I’ll answer from the indexed sources with citations.';
    }
    renderMeta(payload.q ? 'Generating answer' : '');
    updateUrl(payload);
    if (!payload.q) {
      return;
    }

    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok || !response.body) {
        throw new Error(`AI search failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split('\n\n');
        buffer = events.pop() || '';
        for (const rawEvent of events) {
          const lines = rawEvent.split('\n');
          for (const line of lines) {
            if (!line.startsWith('data: ')) {
              continue;
            }
            const parsed = JSON.parse(line.slice(6));
            if (handleEvent(parsed)) {
              renderMeta('Answer ready');
              return;
            }
          }
        }
      }
      if (buffer.trim().startsWith('data: ')) {
        const parsed = JSON.parse(buffer.trim().slice(6));
        handleEvent(parsed);
      }
      renderMeta('Answer ready');
    } catch (error) {
      renderMessages(error.message, null);
      renderMeta('Error');
    }
  };

  form.addEventListener('submit', performSearch);

  const queryInput = form.querySelector('[name="q"]');
  if (queryInput && queryInput.value.trim()) {
    performSearch();
  }
})();
