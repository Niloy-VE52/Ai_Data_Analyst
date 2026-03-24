/* ── State ─────────────────────────────────────────────────── */
const chatHistory = [];     // {role, text}
let allCharts = [];          // [{label, source, index}]

/* ── Theme Switching ──────────────────────────────────────── */
document.querySelectorAll('.theme-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    const theme = btn.dataset.theme;
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('da-theme', theme);
    document.querySelectorAll('.theme-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    // Re-render all plotly charts with updated colors
    recolorPlotlyCharts();
  });
});

// Restore saved theme
const saved = localStorage.getItem('da-theme');
if (saved) {
  document.documentElement.setAttribute('data-theme', saved);
  document.querySelectorAll('.theme-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.theme === saved);
  });
}

/* ── Plotly theme helper ──────────────────────────────────── */
function getPlotlyLayout() {
  const style = getComputedStyle(document.documentElement);
  const bg = style.getPropertyValue('--bg-card').trim();
  const textColor = style.getPropertyValue('--text-secondary').trim();
  const gridColor = style.getPropertyValue('--border').trim();
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: { family: 'Inter, sans-serif', color: textColor, size: 12 },
    xaxis: { gridcolor: gridColor, zerolinecolor: gridColor },
    yaxis: { gridcolor: gridColor, zerolinecolor: gridColor },
    margin: { t: 40, r: 20, b: 40, l: 50 },
    colorway: ['#7c5cfc', '#38d5f8', '#f87171', '#34d399', '#fbbf24', '#c96bfa', '#ff6b9d', '#56e0a0'],
  };
}

function renderPlotlyChart(containerId, figureJson) {
  const layout = { ...figureJson.layout, ...getPlotlyLayout() };
  if (figureJson.layout && figureJson.layout.title) {
    layout.title = figureJson.layout.title;
  }
  Plotly.newPlot(containerId, figureJson.data, layout, {
    responsive: true,
    displayModeBar: false,
  });
}

function recolorPlotlyCharts() {
  document.querySelectorAll('.plotly-chart-div').forEach(el => {
    const figJson = JSON.parse(el.dataset.figure);
    renderPlotlyChart(el.id, figJson);
  });
}

/* ── Drag & Drop ──────────────────────────────────────────── */
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');

uploadArea.addEventListener('dragover', e => {
  e.preventDefault();
  uploadArea.classList.add('dragover');
});
uploadArea.addEventListener('dragleave', () => uploadArea.classList.remove('dragover'));
uploadArea.addEventListener('drop', e => {
  e.preventDefault();
  uploadArea.classList.remove('dragover');
  if (e.dataTransfer.files.length) {
    fileInput.files = e.dataTransfer.files;
    handleUpload(e.dataTransfer.files[0]);
  }
});
fileInput.addEventListener('change', () => {
  if (fileInput.files.length) handleUpload(fileInput.files[0]);
});

/* ── Upload CSV ───────────────────────────────────────────── */
async function handleUpload(file) {
  showLoading(true);
  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/upload', { method: 'POST', body: formData });
    const data = await res.json();
    if (data.error) {
      alert(data.error);
      showLoading(false);
      return;
    }

    // Show file info
    document.getElementById('fileInfo').classList.remove('hidden');
    document.getElementById('fileStats').innerHTML =
      `<strong>${file.name}</strong><br>${data.shape.rows.toLocaleString()} rows × ${data.shape.columns} columns`;

    // Data preview
    buildPreviewTable(data.columns, data.sample);

    // Auto charts
    renderAutoCharts(data.auto_charts);

    // Show errors if any
    if (data.errors && data.errors.length > 0) {
      const sec = document.getElementById('errorsSection');
      sec.classList.remove('hidden');
      sec.innerHTML = data.errors.map(e => `<div class="error-banner">${e}</div>`).join('');
    }

    // Reset chat
    chatHistory.length = 0;
    document.getElementById('chatMessages').innerHTML = '';

    // Show sections
    document.getElementById('welcomeState').classList.add('hidden');
    document.getElementById('chatSection').classList.remove('hidden');

    // Refresh summary selector
    refreshSummarySelector();

  } catch (err) {
    alert('Upload failed: ' + err.message);
  } finally {
    showLoading(false);
  }
}

function showLoading(show) {
  document.getElementById('loadingOverlay').classList.toggle('hidden', !show);
}

/* ── Data Preview Table ───────────────────────────────────── */
function buildPreviewTable(columns, sample) {
  const sec = document.getElementById('previewSection');
  sec.classList.remove('hidden');
  const container = document.getElementById('dataPreview');
  let html = '<table><thead><tr>';
  columns.forEach(c => html += `<th>${esc(c)}</th>`);
  html += '</tr></thead><tbody>';
  sample.forEach(row => {
    html += '<tr>';
    columns.forEach(c => html += `<td>${esc(String(row[c] ?? ''))}</td>`);
    html += '</tr>';
  });
  html += '</tbody></table>';
  container.innerHTML = html;
}

/* ── Render Auto Charts ───────────────────────────────────── */
let chartIdCounter = 0;

function renderAutoCharts(charts) {
  const grid = document.getElementById('chartsGrid');
  const sec = document.getElementById('chartsSection');
  grid.innerHTML = '';

  if (!charts.length) {
    sec.classList.add('hidden');
    return;
  }

  sec.classList.remove('hidden');
  document.getElementById('chartCount').textContent = `${charts.length} charts`;

  charts.forEach((chart, i) => {
    const chartId = `auto-chart-${chartIdCounter++}`;
    const codeId = `code-${chartId}`;

    const card = document.createElement('div');
    card.className = 'card chart-card';
    card.innerHTML = `
      <div class="card-header">
        <h3>📊 Chart ${i + 1}: ${esc(chart.title)}</h3>
      </div>
      <div class="chart-container">
        <div id="${chartId}" class="plotly-chart-div" data-figure='${JSON.stringify(chart.figure_json)}'></div>
      </div>
      ${chart.explanation ? `<div class="chart-explanation">${esc(chart.explanation)}</div>` : ''}
      <button class="view-code-btn" onclick="toggleCode('${codeId}')">▸ View code</button>
      <div id="${codeId}" class="code-block"><pre>${esc(chart.code)}</pre></div>
    `;
    grid.appendChild(card);

    // Render chart after DOM insertion
    setTimeout(() => renderPlotlyChart(chartId, chart.figure_json), 50);
  });
}

function toggleCode(id) {
  document.getElementById(id).classList.toggle('visible');
}

/* ── Chat ─────────────────────────────────────────────────── */
document.getElementById('chatInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

async function sendChat() {
  const input = document.getElementById('chatInput');
  const question = input.value.trim();
  if (!question) return;

  const explainWithChart = document.getElementById('chartToggle').checked;

  // Add user message
  appendChatMsg('user', question);
  chatHistory.push({ role: 'user', text: question });
  input.value = '';

  // Show typing indicator
  const typingId = showTyping();

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question,
        explain_with_chart: explainWithChart,
        chat_history: chatHistory.slice(-10),
      }),
    });
    const data = await res.json();
    removeTyping(typingId);

    if (data.error && data.type !== 'chart' && data.type !== 'text') {
      appendChatMsg('assistant', data.error, null, null, true);
      return;
    }

    if (data.type === 'chart') {
      const text = data.explanation || '';
      appendChatMsg('assistant', text, data.figure_json, data.code);
      chatHistory.push({ role: 'assistant', text });

    } else if (data.type === 'text') {
      let text = data.content || '';
      appendChatMsg('assistant', text, data.chart_figure_json, data.chart_code,
        false, data.chart_explanation);
      chatHistory.push({ role: 'assistant', text });

    } else {
      appendChatMsg('assistant', data.content || 'Unknown error', null, null, true);
    }

    // Refresh deep summary selector
    refreshSummarySelector();

  } catch (err) {
    removeTyping(typingId);
    appendChatMsg('assistant', 'Request failed: ' + err.message, null, null, true);
  }
}

function appendChatMsg(role, text, figureJson, code, isError, chartExplanation) {
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;

  const avatar = role === 'user' ? '👤' : '🤖';
  let bubbleContent = '';

  if (isError) {
    bubbleContent = `<div class="error-banner">${esc(text)}</div>`;
  } else {
    bubbleContent = `<div>${formatText(text)}</div>`;
  }

  if (figureJson) {
    const chartId = `chat-chart-${chartIdCounter++}`;
    bubbleContent += `
      <div class="chat-chart">
        <div id="${chartId}" class="plotly-chart-div" data-figure='${JSON.stringify(figureJson)}' style="min-height:280px"></div>
        ${chartExplanation ? `<div class="chat-chart-explanation">💡 ${esc(chartExplanation)}</div>` : ''}
      </div>
    `;
    if (code) {
      const codeId = `code-${chartId}`;
      bubbleContent += `
        <button class="view-code-btn" onclick="toggleCode('${codeId}')" style="border:none;background:none;padding:6px 0;color:var(--text-muted);cursor:pointer;font-size:0.78rem">▸ View code</button>
        <div id="${codeId}" class="code-block" style="display:none"><pre style="font-size:0.72rem;color:var(--text-secondary)">${esc(code)}</pre></div>
      `;
    }
    // Render chart after DOM insertion
    setTimeout(() => renderPlotlyChart(chartId, figureJson), 50);
  }

  div.innerHTML = `
    <div class="avatar">${avatar}</div>
    <div class="bubble">${bubbleContent}</div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
}

let typingCounter = 0;
function showTyping() {
  const id = `typing-${typingCounter++}`;
  const container = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'chat-msg assistant';
  div.id = id;
  div.innerHTML = `
    <div class="avatar">🤖</div>
    <div class="bubble"><span class="spinner">Thinking</span></div>
  `;
  container.appendChild(div);
  container.scrollTop = container.scrollHeight;
  return id;
}

function removeTyping(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

/* ── Deep Summary ─────────────────────────────────────────── */
async function refreshSummarySelector() {
  try {
    const res = await fetch('/api/all-charts');
    const data = await res.json();
    allCharts = data.charts || [];

    const sec = document.getElementById('deepSummarySection');
    const select = document.getElementById('summarySelect');

    if (allCharts.length === 0) {
      sec.classList.add('hidden');
      return;
    }

    sec.classList.remove('hidden');
    select.innerHTML = allCharts.map((c, i) =>
      `<option value="${i}">${esc(c.label)}</option>`
    ).join('');
  } catch (err) {
    console.error('Failed to fetch charts:', err);
  }
}

async function getDeepSummary() {
  const select = document.getElementById('summarySelect');
  const idx = parseInt(select.value);
  const chart = allCharts[idx];
  if (!chart) return;

  const btn = document.getElementById('summaryBtn');
  const resultDiv = document.getElementById('summaryResult');
  btn.disabled = true;
  btn.textContent = '⏳ Generating…';
  resultDiv.innerHTML = '';

  try {
    const res = await fetch('/api/deep-summary', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source: chart.source, index: chart.index }),
    });
    const data = await res.json();
    resultDiv.innerHTML = `<div class="deep-summary-result">${formatText(data.summary || data.error)}</div>`;
  } catch (err) {
    resultDiv.innerHTML = `<div class="error-banner">Failed: ${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '📝 Get Deeper Summary';
  }
}

/* ── Helpers ──────────────────────────────────────────────── */
function esc(str) {
  const d = document.createElement('div');
  d.textContent = str;
  return d.innerHTML;
}

function formatText(text) {
  if (!text) return '';
  // Basic markdown-like formatting
  return text
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
    .replace(/`(.*?)`/g, '<code style="background:var(--accent-subtle);padding:1px 5px;border-radius:4px;font-size:0.82em">$1</code>')
    .replace(/\n/g, '<br>');
}
