'use strict';
const $ = id => document.getElementById(id);
const fragment = location.hash.slice(1);
if (fragment) {
  if (fragment !== 'main') sessionStorage.setItem('freep2p-token', fragment);
  history.replaceState(null, '', '/');
}
const token = sessionStorage.getItem('freep2p-token') || '';
let role = 'host', current = null, toastTimer, pendingRefresh = null;
let appExited = false, locked = !token, offline = false, copiedCode = '', nextAction = null;
let removeTarget = null, guideSignature = '', logSignature = '';
const names = {host: '나의 월드', guest: '플레이어'};
const peerRows = new Map();
document.querySelector('.skip-link').onclick = event => {
  event.preventDefault();
  $('main').focus({preventScroll: true});
  $('main').scrollIntoView({block: 'start'});
};
const labels = {punching: '연결 시도 중', handshaking: '연결 확인 중', connected: '연결됨', failed: '연결 실패', closed: '연결 끊김'};

function element(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}
function setText(id, text) {
  if ($(id).textContent !== text) $(id).textContent = text;
}
function toast(message) {
  setText('toast', message);
  $('toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 5000);
}
function showError(id, error, field) {
  setText(id, error.message || String(error));
  $(id).hidden = false;
  if (field) { field.setAttribute('aria-invalid', 'true'); field.focus(); }
}
function clearError(id, field) {
  $(id).hidden = true;
  if (field) field.removeAttribute('aria-invalid');
}
function focusField(id) {
  $(id).scrollIntoView({block: 'center'});
  $(id).focus({preventScroll: true});
}
function setOffline(value) {
  offline = value;
  $('app-connection').hidden = !value || locked || appExited;
  $('setup').inert = $('workspace').inert = value || locked || appExited;
  $('quit-app').disabled = value || locked || appExited;
}
function showLocked() {
  locked = true;
  $('locked').hidden = false;
  $('setup').hidden = $('workspace').hidden = true;
  for (const dialog of document.querySelectorAll('dialog[open]')) dialog.close();
  setOffline(false);
  $('locked').querySelector('h2').focus();
}
async function api(path, body) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8000);
  let res;
  try {
    res = await fetch('/api/' + path, {
      method: body === undefined ? 'GET' : 'POST', signal: controller.signal,
      headers: {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  } catch {
    if (!appExited) setOffline(true);
    throw new Error('FreeP2P의 응답이 없습니다. 실행 파일이 켜져 있는지 확인해 주세요.');
  } finally { clearTimeout(timeout); }
  if (res.status === 401) {
    showLocked();
    throw new Error('FreeP2P 실행 파일을 다시 열어 주세요.');
  }
  let value;
  try { value = await res.json(); }
  catch { throw new Error('응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요.'); }
  if (!res.ok) throw new Error(value.error || '처리하지 못했습니다. 다시 시도해 주세요.');
  return value;
}

function setRole(next) {
  if (role === next) return;
  names[role] = $('name').value;
  role = next;
  const host = role === 'host';
  for (const choice of ['host', 'guest']) {
    $('choose-' + choice).classList.toggle('selected', choice === role);
    $('choose-' + choice).setAttribute('aria-pressed', String(choice === role));
  }
  $('name').value = names[role];
  $('port-label').hidden = $('host-preparation').hidden = $('host-options').hidden = !host;
  $('port').disabled = $('max-peers').disabled = !host;
  $('host-code-field').hidden = $('guest-options').hidden = host;
  $('listen-port').disabled = $('host-code').disabled = host;
  $('host-code').required = !host;
  setText('start-hint', host ? '월드는 플레이하는 동안 계속 열어 두세요.' : '받은 코드를 넣은 뒤, 내 참가 코드도 친구에게 보내 주세요.');
  setText('start-button', host ? '호스트 시작 →' : '참가 준비 →');
  clearError('start-error', $('host-code'));
}
$('choose-host').onclick = () => setRole('host');
$('choose-guest').onclick = () => setRole('guest');
// Let native validation focus fields even when their settings are collapsed.
document.addEventListener('invalid', event => {
  for (let parent = event.target.parentElement; parent; parent = parent.parentElement) {
    if (parent.tagName === 'DETAILS') parent.open = true;
  }
}, true);
for (const [field, error] of [['host-code', 'start-error'], ['guest-code', 'add-error'], ['live-max-peers', 'limit-error']]) {
  $(field).addEventListener('input', () => clearError(error, $(field)));
}
$('start-form').onsubmit = async event => {
  event.preventDefault();
  const host = role === 'host';
  $('start-button').disabled = true;
  setText('start-button', '준비하는 중…');
  clearError('start-error', $('host-code'));
  try {
    await api('start', {role, name: $('name').value.trim(), game_port: host ? Number($('port').value) : 25565,
      listen_port: host ? 25565 : Number($('listen-port').value), host_code: host ? '' : $('host-code').value.trim(),
      max_peers: host ? Number($('max-peers').value) : 16});
    copiedCode = ''; guideSignature = ''; logSignature = '';
    $('copy-feedback').hidden = $('game-check-result').hidden = true;
    await refresh(true);
    if (!locked && !offline && current) $('world-name').focus();
  } catch (error) { showError('start-error', error, host ? null : $('host-code')); }
  finally {
    $('start-button').disabled = false;
    setText('start-button', host ? '호스트 시작 →' : '참가 준비 →');
  }
};
$('add-form').onsubmit = async event => {
  event.preventDefault();
  $('add-button').disabled = true;
  setText('add-button', '추가하는 중…');
  clearError('add-error', $('guest-code'));
  try {
    await api('peers', {action: 'add', code: $('guest-code').value.trim()});
    $('guest-code').value = '';
    await refresh(true);
    toast('친구를 등록했습니다. 연결 상태를 확인해 주세요.');
  } catch (error) { showError('add-error', error, $('guest-code')); }
  finally { $('add-button').disabled = false; setText('add-button', '참가자 추가 +'); }
};
async function copy(text, field) {
  try { await navigator.clipboard.writeText(text); return true; }
  catch {
    field.focus(); field.select();
    toast('텍스트를 선택했습니다. Ctrl+C 또는 Mac의 ⌘C로 복사하세요.');
    return false;
  }
}
async function copyCode() {
  if (!current?.code) return;
  const code = current.code;
  const success = await copy(code, $('own-code'));
  if (success && current?.code === code) {
    copiedCode = code;
    setText('copy-feedback', '복사했습니다. 친구와의 개인 대화창에 붙여넣어 보내 주세요.');
    $('copy-feedback').hidden = false;
    renderNext();
  }
}
async function copyAddress() {
  if (current && await copy($('game-address').value, $('game-address'))) {
    toast('Minecraft → 멀티플레이 → 직접 연결에 붙여넣으세요.');
  }
}
$('copy-code').onclick = copyCode;
$('copy-address').onclick = copyAddress;
$('next-action').onclick = () => nextAction?.();
$('check-game').onclick = async () => {
  $('check-game').disabled = true;
  setText('game-check-result', '게임이 응답하는지 확인하고 있어요…');
  $('game-check-result').hidden = false;
  try {
    const result = await api('check-game', {});
    setText('game-check-result', result.ok
      ? '입력한 번호에서 응답이 왔습니다. 친구가 실제로 게임에 들어갈 수 있는지도 확인해 주세요.'
      : '게임이 응답하지 않습니다. LAN 서버가 열려 있는지, 게임에 나온 숫자를 맞게 적었는지 확인하세요.');
    $('game-check-result').classList.toggle('error', !result.ok);
  } catch (error) { showError('game-check-result', error); }
  finally { $('check-game').disabled = false; }
};

function openDialog(id, error) { clearError(error); $(id).showModal(); }
$('stop-button').onclick = () => openDialog('stop-dialog', 'stop-error');
$('cancel-stop').onclick = () => $('stop-dialog').close();
$('confirm-stop').onclick = async () => {
  $('confirm-stop').disabled = true;
  try {
    await api('stop', {});
    $('stop-dialog').close();
    copiedCode = ''; guideSignature = ''; logSignature = '';
    $('copy-feedback').hidden = $('game-check-result').hidden = true;
    $('guest-code').value = '';
    clearError('start-error'); clearError('add-error');
    await refresh(true);
    if (!locked && !offline) $('setup-title').focus();
  } catch (error) { showError('stop-error', error); }
  finally { $('confirm-stop').disabled = false; }
};
$('quit-app').onclick = () => openDialog('quit-dialog', 'quit-error');
$('cancel-quit').onclick = () => $('quit-dialog').close();
$('confirm-quit').onclick = async () => {
  $('confirm-quit').disabled = true;
  try {
    await api('shutdown', {});
    appExited = true;
    $('quit-dialog').close();
    $('setup').hidden = $('workspace').hidden = true;
    $('exited').hidden = false;
    setOffline(false);
    $('exited').querySelector('h2').focus();
  } catch (error) { showError('quit-error', error); }
  finally { $('confirm-quit').disabled = false; }
};
$('cancel-remove').onclick = () => $('remove-dialog').close();
$('confirm-remove').onclick = async () => {
  $('confirm-remove').disabled = true;
  try {
    await api('peers', {action: 'remove', id: removeTarget});
    $('remove-dialog').close();
    await refresh(true);
    if (!locked && !offline) $('peers-panel').focus();
  } catch (error) { showError('remove-error', error); }
  finally { $('confirm-remove').disabled = false; }
};
$('limit-form').onsubmit = async event => {
  event.preventDefault();
  $('save-limit').disabled = true;
  clearError('limit-error', $('live-max-peers'));
  try {
    await api('settings', {max_peers: Number($('live-max-peers').value)});
    await refresh(true);
    toast('최대 참가자 수를 변경했습니다.');
  } catch (error) { showError('limit-error', error, $('live-max-peers')); }
  finally { $('save-limit').disabled = false; }
};

function size(n) { return n < 1024 ? n + ' B' : n < 1048576 ? (n / 1024).toFixed(1) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
function renderPeers(peers) {
  // Keep the same buttons alive while counters and RTT change during polling.
  const ids = new Set(peers.map(peer => peer.id));
  for (const [id, row] of peerRows) {
    if (!ids.has(id)) { row.root.remove(); peerRows.delete(id); }
  }
  let empty = $('peers').querySelector('.empty');
  if (!peers.length && !empty) {
    empty = element('div', 'empty', current.role === 'host'
      ? '친구가 보내 준 참가 코드를 위에 등록해 주세요.' : '친구의 연결이 없습니다. 연결을 끝낸 뒤 새 코드로 다시 준비해 주세요.');
    $('peers').append(empty);
  } else if (peers.length && empty) empty.remove();
  for (const peer of peers) {
    let row = peerRows.get(peer.id);
    if (!row) {
      row = {root: element('div', 'peer-row'), avatar: element('span', 'avatar'), name: element('strong', 'peer-name'),
        badge: element('span', 'badge'), meta: element('div', 'peer-meta'), help: element('p', 'peer-help'),
        detail: element('details', 'peer-detail'), error: element('p', 'peer-error'),
        retry: element('button', 'text-button', '다시 연결'), remove: element('button', 'text-button', '연결 해제')};
      const top = element('div', 'peer-top'), actions = element('div', 'peer-actions');
      top.append(row.avatar, row.name, row.badge);
      row.detail.append(element('summary', '', '오류 내용 보기'), row.error);
      actions.append(row.retry, row.remove);
      row.root.append(top, row.meta, row.help, row.detail, actions);
      row.retry.onclick = async () => {
        row.retry.disabled = true;
        try { await api('peers', {action: 'retry', id: peer.id}); await refresh(true); }
        catch (error) { toast(error.message); }
        finally { row.retry.disabled = false; }
      };
      row.remove.onclick = () => {
        removeTarget = peer.id;
        setText('remove-description', `${row.name.textContent} 님의 게임 연결이 끊깁니다. 다른 친구들은 계속 플레이할 수 있습니다. 다시 초대하려면 이 친구의 참가 코드를 등록하세요.`);
        openDialog('remove-dialog', 'remove-error');
      };
      peerRows.set(peer.id, row);
      $('peers').append(row.root);
    }
    const failed = ['failed', 'closed'].includes(peer.state);
    row.avatar.textContent = peer.name.slice(0, 1);
    row.name.textContent = peer.name;
    row.badge.textContent = labels[peer.state] || peer.state;
    row.badge.className = 'badge ' + peer.state;
    row.meta.textContent = `게임 연결 ${peer.streams}개 · ↑ ${size(peer.uploaded)} ↓ ${size(peer.downloaded)}${peer.rtt === null ? '' : ' · ' + peer.rtt + ' ms'}`;
    row.help.hidden = !failed;
    row.help.textContent = '양쪽 프로그램이 켜져 있고 최신 코드를 서로 등록했는지 확인한 뒤 다시 연결해 보세요.';
    row.detail.hidden = !peer.error;
    row.error.textContent = peer.error;
    row.retry.hidden = !failed;
    row.remove.hidden = current.role !== 'host';
    row.retry.setAttribute('aria-label', peer.name + ' 다시 연결');
    row.remove.setAttribute('aria-label', peer.name + ' 연결 해제');
  }
}
function renderNext() {
  if (!current) return;
  const host = current.role === 'host', peers = current.peers;
  const connected = peers.filter(peer => peer.state === 'connected').length;
  const failed = peers.filter(peer => ['failed', 'closed'].includes(peer.state)).length;
  let title, description, label = '', action = null;
  if (!current.code) {
    title = current.status === 'stun_failed' ? '연결 코드를 준비하지 못했어요' : '연결 코드를 준비하고 있어요';
    description = current.status === 'stun_failed'
      ? '인터넷 연결을 확인해 주세요. 자동으로 다시 시도하고 있습니다. 계속 안 되면 다른 인터넷 환경에서 시도해 주세요.'
      : '코드가 나오면 함께할 친구에게 보내 주세요. 잠시만 기다려 주세요.';
  } else if (failed) {
    title = connected ? '연결되지 않은 친구가 있어요' : '친구와 연결하지 못했어요';
    description = '서로 최신 코드를 등록했는지 확인하세요. 아래 친구 목록에서 다시 연결할 수 있습니다.';
    label = '연결 상태 확인'; action = () => focusField('peers-panel');
  } else if (connected) {
    title = host ? `${connected}명의 친구와 연결됐어요` : '이제 Minecraft에서 접속하세요';
    description = host ? '친구는 자기 화면의 게임 주소로 접속하면 됩니다. 내 월드는 계속 열어 두세요.'
      : '아래 주소를 복사해 Minecraft → 멀티플레이 → 직접 연결에 붙여넣으세요.';
    label = host ? '다른 친구 초대하기' : '게임 접속 주소 복사';
    action = host ? copyCode : copyAddress;
  } else if (copiedCode !== current.code) {
    title = host ? '내 코드를 친구에게 보내 주세요' : '내 참가 코드도 친구에게 보내 주세요';
    description = host ? '코드를 복사해 개인 대화창에 보내고, 친구의 참가 코드도 받아 주세요.'
      : '월드를 연 친구가 내 참가 코드를 등록해야 연결됩니다. 코드 복사를 눌러 보내 주세요.';
    label = '코드 복사'; action = copyCode;
  } else if (host && !peers.length) {
    title = '친구가 보내 준 코드를 등록하세요';
    description = '복사한 코드를 친구에게 보냈나요? 이제 친구의 ‘내 참가 코드’를 받아 아래에 붙여넣으세요.';
    label = '참가 코드 입력'; action = () => focusField('guest-code');
  } else {
    title = '친구의 연결을 기다리고 있어요';
    description = host ? '친구도 FreeP2P를 켜 두어야 합니다. 연결 상태는 자동으로 바뀝니다.'
      : '복사한 참가 코드를 친구에게 보내고 등록해 달라고 해 주세요. 연결 상태는 자동으로 바뀝니다.';
  }
  setText('next-title', title); setText('next-description', description);
  setText('next-action', label); $('next-action').hidden = !action; nextAction = action;
}
function render(data) {
  if (appExited || locked) return;
  const previousCode = current?.code;
  current = data.node;
  $('setup').hidden = !!current; $('workspace').hidden = !current;
  if (!current) {
    for (const row of peerRows.values()) row.root.remove();
    peerRows.clear(); $('peers').replaceChildren();
    return;
  }
  if (previousCode && previousCode !== current.code) { copiedCode = ''; $('copy-feedback').hidden = true; }
  const host = current.role === 'host';
  const connected = current.peers.filter(peer => peer.state === 'connected').length;
  const failed = current.peers.filter(peer => ['failed', 'closed'].includes(peer.state)).length;
  const waiting = current.peers.length - connected - failed;
  setText('mode-label', (host ? '내 월드 열기' : '친구 월드 참가') + (data.local_test ? ' · 로컬 테스트' : ''));
  setText('world-name', current.name);
  setText('session-description', host ? '월드를 여는 사람의 화면입니다.' : '월드를 연 친구와 서로 코드를 주고받아 주세요.');
  setText('node-state', connected ? `${connected}명 연결됨${failed ? ' · ' + failed + '명 확인 필요' : ''}`
    : current.status === 'stun_failed' ? '코드 준비 실패' : !current.code ? '코드 준비 중'
    : waiting ? '친구와 연결 중' : failed ? '연결 실패' : '코드 교환 대기');
  setText('node-state-help', failed ? '친구 목록에서 상태를 확인해 주세요.' : connected ? '게임 입장은 Minecraft에서 확인해 주세요.' : '양쪽에서 서로의 코드를 등록해야 합니다.');
  setText('count-title', host ? '연결된 친구' : '친구와의 연결');
  setText('peer-count', host ? `${connected} / ${current.max_peers}` : connected ? '연결됨' : '아직 연결되지 않음');
  setText('peer-count-help', host ? `등록한 친구 ${current.peers.length}명 · 최대 인원은 아래에서 변경할 수 있어요.`
    : connected ? 'Minecraft에서 친구 월드에 들어갈 준비가 됐어요.' : '코드를 보내고 친구가 등록할 때까지 기다려 주세요.');
  setText('endpoint-title', host ? '내 게임 주소' : 'Minecraft 직접 연결에 넣을 주소');
  $('game-address').value = '127.0.0.1:' + (host ? current.game_port : current.listen_port);
  setText('game-address-help', host ? '게임에서 표시한 숫자가 맞는지 확인하세요.' : connected ? '게임 주소를 복사해 붙여넣으세요.' : '연결되면 주소를 복사할 수 있습니다.');
  $('check-game').hidden = !host; $('copy-address').hidden = host; $('copy-address').disabled = !connected;
  setText('code-title', host ? '호스트 연결 코드' : '내 참가 코드');
  setText('code-help', host ? '친구에게 이 코드를 보내세요. 돌아온 참가 코드도 아래에 등록해야 합니다.' : '월드를 연 친구에게 이 코드를 보내세요. 친구가 등록하면 연결됩니다.');
  if ($('own-code').value !== current.code) $('own-code').value = current.code;
  $('copy-code').disabled = !current.code;
  $('add-panel').hidden = !host;
  setText('peers-title', host ? '참가자' : '월드를 연 친구');
  setText('public-address', current.public || '확인 중'); setText('udp-port', String(current.udp_port));
  setText('max-peers-tag', `최대 ${current.max_peers}명`);
  if (document.activeElement !== $('live-max-peers') && $('live-max-peers').dataset.saved !== String(current.max_peers)) {
    $('live-max-peers').value = current.max_peers; $('live-max-peers').dataset.saved = String(current.max_peers);
  }
  const guideKey = [current.role, current.listen_port].join(':');
  if (guideSignature !== guideKey) {
    guideSignature = guideKey;
    setText('guide-title', host ? '코드는 서로 한 번씩.' : '내 코드도 보내야 해요.');
    const steps = host ? [['내 코드를 보내기', '친구와의 개인 대화창에 붙여넣으세요.'], ['돌아온 코드 등록하기', '친구가 보낸 참가 코드를 아래에 넣으세요.'], ['게임은 켜 두기', '친구는 자기 화면의 게임 주소로 들어옵니다.']]
      : [['내 참가 코드 보내기', '월드를 연 친구가 등록해야 연결됩니다.'], ['연결됨 기다리기', '두 사람 모두 FreeP2P를 켜 두세요.'], ['게임에서 직접 연결', '127.0.0.1:' + current.listen_port + '를 입력하세요.']];
    $('guide-steps').replaceChildren();
    for (const [title, description] of steps) {
      const li = element('li'); li.append(element('b', '', title), element('span', '', description)); $('guide-steps').append(li);
    }
  }
  renderNext(); renderPeers(current.peers);
  const logKey = JSON.stringify(current.events);
  if (logSignature !== logKey) {
    logSignature = logKey; $('events').replaceChildren();
    for (const event of current.events.slice(-6).reverse()) {
      const li = element('li'); li.append(element('time', '', event.time), element('span', '', event.message)); $('events').append(li);
    }
  }
}
async function refresh(force = false) {
  if (pendingRefresh) {
    if (!force) return pendingRefresh;
    await pendingRefresh;
  }
  if (appExited || locked) return;
  pendingRefresh = (async () => {
    try {
      const data = await api('state');
      if (!appExited && !locked) { setOffline(false); render(data); }
    } catch { if (!appExited && !locked) setOffline(true); }
  })();
  try { await pendingRefresh; } finally { pendingRefresh = null; }
}
$('refresh-connection').onclick = () => refresh(true);
if (!token) showLocked();
else { refresh(); setInterval(refresh, 1500); }
