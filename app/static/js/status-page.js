(() => {
  const updateWorkerStatus = (data) => {
    // Update overall worker status
    const workerTile = document.querySelector('[data-worker-status]');
    if (workerTile) {
      const statusValue = workerTile.querySelector('.stat-value');
      const summary = workerTile.querySelector('.small-status');
      if (statusValue) statusValue.textContent = capitalize(data.worker_status);
      if (summary) summary.textContent = data.worker_summary;

      // Update tile color
      workerTile.className = 'stat-tile';
      if (data.worker_status === 'ok') {
        workerTile.classList.add('status-ok');
      } else if (data.worker_status === 'stale') {
        workerTile.classList.add('status-bad');
      } else {
        workerTile.classList.add('status-neutral');
      }
    }

    // Update individual worker cards
    const workerGrid = document.querySelector('.worker-grid');
    if (workerGrid && data.workers) {
      workerGrid.innerHTML = data.workers.map(worker => `
        <div class="worker-card ${getWorkerStatusClass(worker.status)}" data-worker-name="${escapeHtml(worker.name)}">
          <div class="worker-card-content">
            <div class="stat-label">${escapeHtml(worker.name)}</div>
            <div class="stat-value">${capitalize(worker.status)}</div>
            ${worker.detail ? `<div class="small-status">${escapeHtml(worker.detail)}</div>` : ''}
          </div>
        </div>
      `).join('');

      // Reattach click handlers
      attachWorkerClickHandlers();
    }
  };

  const updateJobCounts = (data) => {
    const jobStats = {
      pending: data.job_counts?.pending,
      running: data.job_counts?.running,
      done: data.job_counts?.done,
      failed: data.job_counts?.failed
    };

    for (const [key, value] of Object.entries(jobStats)) {
      const tile = document.querySelector(`[data-job-${key}]`);
      if (tile) {
        const valueEl = tile.querySelector('.stat-value');
        if (valueEl) valueEl.textContent = value ?? '0';
      }
    }

    // Update indexing active status
    const indexingStatus = document.querySelector('[data-indexing-status]');
    if (indexingStatus) {
      indexingStatus.textContent = data.indexing_active ? 'Indexing active' : 'Indexer idle';
    }
  };

  const handleStatusUpdate = (data) => {
    updateWorkerStatus(data);
    updateJobCounts(data);
  };

  const connectEventSource = () => {
    const eventSource = new EventSource('/api/status/stream');

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleStatusUpdate(data);
      } catch (error) {
        console.error('Failed to parse status update:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE connection error:', error);
      eventSource.close();
      // Reconnect after 5 seconds
      setTimeout(connectEventSource, 5000);
    };

    return eventSource;
  };

  const getWorkerStatusClass = (status) => {
    if (status === 'ok') return 'status-ok';
    if (status === 'stale') return 'status-bad';
    return 'status-neutral';
  };

  const capitalize = (str) => {
    if (!str) return '';
    return str.charAt(0).toUpperCase() + str.slice(1);
  };

  const escapeHtml = (text) => {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  };

  let currentLogStream = null;

  const showWorkerLogs = (workerName) => {
    const logsSection = document.getElementById('worker-logs-section');
    const logsTitle = document.getElementById('worker-logs-title');
    const logsContent = document.getElementById('worker-logs-content');

    if (!logsSection || !logsTitle || !logsContent) return;

    // Close existing stream
    if (currentLogStream) {
      currentLogStream.close();
    }

    // Show logs section
    logsSection.style.display = 'block';
    logsTitle.textContent = `Logs: ${workerName}`;
    logsContent.textContent = 'Loading logs...\n';

    // Scroll to logs
    logsSection.scrollIntoView({ behavior: 'smooth' });

    // Start streaming logs
    currentLogStream = new EventSource(`/api/workers/${encodeURIComponent(workerName)}/logs`);

    currentLogStream.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.error) {
          logsContent.textContent = `Error: ${data.error}\n`;
        } else if (data.log) {
          // Clear "Loading..." on first log
          if (logsContent.textContent.startsWith('Loading')) {
            logsContent.textContent = '';
          }
          logsContent.textContent += data.log + '\n';
          // Auto-scroll to bottom
          logsContent.scrollTop = logsContent.scrollHeight;
        }
      } catch (err) {
        console.error('Failed to parse log data:', err);
      }
    };

    currentLogStream.onerror = (error) => {
      console.error('Log stream error:', error);
      logsContent.textContent += '\n[Stream disconnected]\n';
      currentLogStream.close();
      currentLogStream = null;
    };
  };

  const closeWorkerLogs = () => {
    const logsSection = document.getElementById('worker-logs-section');
    if (logsSection) {
      logsSection.style.display = 'none';
    }
    if (currentLogStream) {
      currentLogStream.close();
      currentLogStream = null;
    }
  };

  const attachWorkerClickHandlers = () => {
    document.querySelectorAll('.worker-card').forEach(card => {
      card.addEventListener('click', () => {
        const workerName = card.getAttribute('data-worker-name');
        if (workerName) {
          showWorkerLogs(workerName);
        }
      });
    });
  };

  // Close logs button
  const closeLogsBtn = document.getElementById('close-logs');
  if (closeLogsBtn) {
    closeLogsBtn.addEventListener('click', closeWorkerLogs);
  }

  // Connect to SSE stream
  connectEventSource();

  // Attach click handlers to initial worker cards
  attachWorkerClickHandlers();
})();
