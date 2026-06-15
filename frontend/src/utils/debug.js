// Direct-DOM debug overlay — toggleable, resizable, always shows version.
// Usage: D('message') — writes to console + fixed bottom panel.
// Click ● in bottom-right to toggle, drag top border to resize.

var MAX_LINES = 40;
var panel = null, handle = null, toggle = null;
var lines = [];
var ver = '?.?.?';
var visible = true;
var resizeY = 0, startH = 0, dragging = false;

function ensurePanel() {
  if (panel) return;

  // Toggle button
  toggle = document.createElement('div');
  toggle.id = '__dbg_toggle';
  Object.assign(toggle.style, {
    position: 'fixed', bottom: '4px', right: '8px', zIndex: '100001',
    width: '18px', height: '18px', borderRadius: '50%',
    background: '#F39C12', color: '#000', cursor: 'pointer',
    textAlign: 'center', lineHeight: '18px', fontSize: '12px',
    fontWeight: 'bold', userSelect: 'none',
  });
  toggle.textContent = '●';
  toggle.title = 'Toggle debug panel';
  toggle.addEventListener('click', function() {
    visible = !visible;
    if (visible) { panel.style.display = ''; handle.style.display = ''; }
    else { panel.style.display = 'none'; handle.style.display = 'none'; }
  });
  document.body.appendChild(toggle);

  // Panel
  panel = document.createElement('div');
  panel.id = '__dbg_panel';
  Object.assign(panel.style, {
    position: 'fixed', bottom: '0', left: '0', right: '0',
    zIndex: '99999', background: '#000', borderTop: '3px solid #F39C12',
    padding: '4px 28px 4px 8px', fontSize: '11px', fontFamily: 'monospace',
    color: '#0f0', height: '140px', minHeight: '40px', maxHeight: '80vh',
    overflowY: 'auto', opacity: '0.93', whiteSpace: 'pre-wrap',
    wordBreak: 'break-all', userSelect: 'text', boxSizing: 'border-box',
  });
  document.body.appendChild(panel);

  // Drag handle
  handle = document.createElement('div');
  handle.id = '__dbg_handle';
  Object.assign(handle.style, {
    position: 'fixed', bottom: '140px', left: '0', right: '0',
    height: '6px', zIndex: '100000', cursor: 'ns-resize',
    background: 'transparent',
  });
  handle.addEventListener('mousedown', function(e) {
    dragging = true; resizeY = e.clientY; startH = panel.offsetHeight;
    e.preventDefault();
  });
  document.addEventListener('mousemove', function(e) {
    if (!dragging) return;
    var h = startH + (resizeY - e.clientY);
    if (h < 30) h = 30;
    if (h > window.innerHeight * 0.8) h = window.innerHeight * 0.8;
    panel.style.height = h + 'px';
    handle.style.bottom = h + 'px';
  });
  document.addEventListener('mouseup', function() { dragging = false; });
  document.body.appendChild(handle);
}

function D(msg) {
  ensurePanel();
  var t = new Date().toLocaleTimeString();
  lines.push(t + ' ' + msg);
  if (lines.length > MAX_LINES) lines = lines.slice(-MAX_LINES);
  panel.textContent = 'v' + ver + '\n' + lines.join('\n');
  console.log('[DBG]', msg);
}

window.D = D;
window.setDebugVersion = function(v) {
  ver = v;
  if (panel) panel.textContent = 'v' + ver + '\n' + lines.join('\n');
};

export default D;
