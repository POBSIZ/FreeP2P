'use strict';
const $ = id => document.getElementById(id);
const fragment = location.hash.slice(1);
if (fragment) { sessionStorage.setItem('freep2p-token', fragment); history.replaceState(null, '', '/'); }
const token = sessionStorage.getItem('freep2p-token') || '';
let role = 'host', current = null, toastTimer, polling = false, peerSignature = '', logSignature = '';
const labels = {punching:'연결 시도 중', handshaking:'암호화 연결 중', connected:'연결됨', failed:'연결 실패', closed:'종료됨'};
function toast(message) { $('toast').textContent = message; $('toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500); }
async function api(path, body) {
  const res = await fetch('/api/' + path, {method:body === undefined ? 'GET' : 'POST', headers:{'Authorization':'Bearer '+token, 'Content-Type':'application/json'}, body:body === undefined ? undefined : JSON.stringify(body)});
  if (res.status === 401) { $('locked').hidden=false; $('setup').hidden=true; $('workspace').hidden=true; throw new Error('터미널의 전체 실행 주소로 다시 열어 주세요.'); }
  let value; try { value=await res.json(); } catch { throw new Error('로컬 프로그램의 응답을 확인할 수 없습니다.'); }
  if (!res.ok) throw new Error(value.error || '요청을 처리하지 못했습니다.');
  return value;
}
function setRole(next) {
  role=next;
  for (const r of ['host','guest']) { $('choose-'+r).classList.toggle('selected',r===role); $('choose-'+r).setAttribute('aria-pressed',String(r===role)); }
  $('max-peers-field').hidden=role!=='host'; $('max-peers').disabled=role!=='host'; $('host-code-field').hidden=role==='host'; $('host-code').required=role==='guest';
  $('name').value=role==='host' ? '나의 월드' : '플레이어';
  $('port-title').textContent=role==='host' ? '게임에서 표시된 LAN 포트' : '이 PC의 게임 접속 포트';
  $('port-help').textContent=role==='host' ? '게임에서 Esc → LAN 서버 열기 후 표시되는 숫자예요.' : '보통 25565를 사용합니다. 이미 사용 중이면 다른 숫자를 선택하세요.';
  $('start-hint').textContent=role==='host' ? '먼저 마인크래프트에서 월드를 열어 주세요.' : '호스트의 코드를 붙여넣고, 내 참가 코드도 호스트에게 보내 주세요.';
  $('start-button').textContent=role==='host' ? '호스트 시작 →' : '참가 준비 →';
  $('start-error').hidden=true;
}
$('choose-host').onclick=()=>setRole('host'); $('choose-guest').onclick=()=>setRole('guest');
$('start-form').onsubmit=async e=>{e.preventDefault();$('start-button').disabled=true;$('start-error').hidden=true;try {await api('start',{role,name:$('name').value.trim(),game_port:Number($('port').value),listen_port:Number($('port').value),host_code:$('host-code').value.trim(),max_peers:role==='host'?Number($('max-peers').value):16}); await refresh();} catch(err){$('start-error').textContent=err.message;$('start-error').hidden=false;}finally{$('start-button').disabled=false;}};
$('add-form').onsubmit=async e=>{e.preventDefault();$('add-button').disabled=true;$('add-error').hidden=true;try {await api('peers',{action:'add',code:$('guest-code').value.trim()});$('guest-code').value='';await refresh();}catch(err){$('add-error').textContent=err.message;$('add-error').hidden=false;}finally{$('add-button').disabled=false;}};
async function copy(text, field) {try {await navigator.clipboard.writeText(text);toast('복사했습니다.');}catch{if(field){field.focus();field.select();}toast('자동 복사를 사용할 수 없습니다. 선택된 텍스트를 직접 복사해 주세요.');}}
$('copy-code').onclick=()=>copy(current.code,$('own-code'));
$('copy-address').onclick=()=>copy('127.0.0.1:'+current.listen_port);
$('check-game').onclick=async()=>{try{toast((await api('check-game',{})).message);}catch(err){toast(err.message);}};
$('stop-button').onclick=()=>$('stop-dialog').showModal();
$('cancel-stop').onclick=()=>$('stop-dialog').close();
$('confirm-stop').onclick=async()=>{ $('confirm-stop').disabled=true;try{await api('stop',{});$('stop-dialog').close();peerSignature='';logSignature='';await refresh();}catch(err){toast(err.message);}finally{$('confirm-stop').disabled=false;}};
function element(tag, cls, text) {const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;}
function size(n) {return n<1024 ? n+' B' : n<1048576 ? (n/1024).toFixed(1)+' KB' : (n/1048576).toFixed(1)+' MB';}
function renderPeers(peers) {
  const sig=JSON.stringify(peers);if(sig===peerSignature)return;peerSignature=sig;
  $('peers').replaceChildren();
  if(!peers.length){const empty=element('div','empty');empty.append(element('span','empty-icon','◎'),element('div','', '아직 등록된 참가자가 없어요.'),element('div','', '친구의 참가 코드를 등록하면 여기에 표시됩니다.'));$('peers').append(empty);return;}
  for(const peer of peers){
    const row=element('div','peer-row'),top=element('div','peer-top');
    top.append(element('span','avatar',peer.name.slice(0,1)),element('strong','peer-name',peer.name),element('span','badge '+peer.state,labels[peer.state]||peer.state));
    row.append(top,element('div','peer-meta',`${peer.rtt===null?'RTT —':peer.rtt+' ms'} · 게임 연결 ${peer.streams}개 · ↑ ${size(peer.uploaded)}  ↓ ${size(peer.downloaded)}`));
    if(peer.error)row.append(element('p','peer-error',peer.error));
    const actions=element('div','peer-actions');
    for(const [action,label] of [['retry','다시 연결'],['remove','연결 해제']]){if(action==='retry'&&!['failed','closed'].includes(peer.state))continue;const b=element('button','text-button',label);b.onclick=async()=>{b.disabled=true;try{await api('peers',{action,id:peer.id});await refresh();}catch(err){toast(err.message);b.disabled=false;}};actions.append(b);}
    row.append(actions);$('peers').append(row);
  }
}
function render(data) {
  current=data.node;$('setup').hidden=!!current;$('workspace').hidden=!current;if(!current)return;
  const host=current.role==='host', connected=current.peers.filter(p=>p.state==='connected').length;
  $('mode-label').textContent=(host?'HOST SESSION':'GUEST SESSION')+(data.local_test?' / LOCAL TEST':'');
  $('world-name').textContent=current.name;
  $('session-description').textContent=host?'내 LAN 서버를 친구들과 직접 연결합니다.':'참가 코드를 호스트에게 보내고 연결 완료를 기다리세요.';
  $('node-state').textContent=current.status==='stun_failed'?'주소 확인 실패':current.status==='discovering'?'주소 확인 중':connected?'직접 연결됨':'코드 교환 대기';
  $('node-state-help').textContent=current.status==='stun_failed'?'UDP 차단 여부를 확인하세요. 자동 재시도 중입니다.':current.status==='discovering'?'공개 STUN 서버에서 외부 주소를 확인합니다.':connected?'게임 데이터가 암호화되어 직접 전달됩니다.':'양쪽에서 서로의 코드를 입력해야 합니다.';
  $('count-title').textContent=host?'연결된 참가자':'호스트 연결';$('peer-count').textContent=host?`${connected} / ${current.max_peers}`:connected?'연결됨':'대기 중';
  $('endpoint-title').textContent=host?'내 LAN 서버':'게임의 직접 연결에 입력';$('game-address').textContent='127.0.0.1:'+(host?current.game_port:current.listen_port);
  $('check-game').hidden=!host;$('copy-address').hidden=host;$('copy-address').disabled=!connected;
  $('code-title').textContent=host?'호스트 연결 코드':'내 참가 코드';$('code-help').textContent=host?'이 코드를 친구에게 보내 주세요. 친구가 보내 주는 참가 코드도 필요합니다.':'이 코드를 호스트에게 보내 주세요. 호스트가 등록하면 연결을 시작합니다.';
  if($('own-code').value!==current.code)$('own-code').value=current.code;
  $('copy-code').disabled=!current.code;$('add-panel').hidden=!host;$('peers-title').textContent=host?'참가자':'호스트';
  $('public-address').textContent=current.public||'확인 중';$('udp-port').textContent=current.udp_port;
  $('guide-title').textContent=host?'초대는 세 단계로.':'연결되면 게임으로.';
  const steps=host?[['호스트 코드를 공유해요','친구도 FreeP2P를 실행해 주세요.'],['친구의 참가 코드를 등록해요','양쪽 코드를 교환해야 연결됩니다.'],['게임에서 직접 연결해요','친구 화면에 표시된 로컬 주소로 접속해요.']]:[['내 참가 코드를 보내요','호스트가 이 코드를 등록해야 합니다.'],['연결됨 상태를 기다려요','직접 연결과 암호화 설정을 자동으로 진행해요.'],['로컬 주소로 게임에 접속해요','127.0.0.1:'+current.listen_port+'를 직접 연결에 입력해요.']];
  if($('guide-steps').dataset.role!==current.role){$('guide-steps').replaceChildren();for(const [title,desc] of steps){const li=element('li');li.append(element('b','',title),element('span','',desc));$('guide-steps').append(li);}$('guide-steps').dataset.role=current.role;}
  $('max-peers-tag').textContent=`최대 ${current.max_peers}명`;
  if(document.activeElement!==$('live-max-peers') && $('live-max-peers').dataset.saved!==String(current.max_peers)){$('live-max-peers').value=current.max_peers;$('live-max-peers').dataset.saved=String(current.max_peers);}
  renderPeers(current.peers);
  const sig=JSON.stringify(current.events);if(sig!==logSignature){logSignature=sig;$('events').replaceChildren();for(const event of current.events.slice(-6).reverse()){const li=element('li');li.append(element('time','',event.time),element('span','',event.message));$('events').append(li);}}
}
let appExited=false;
async function refresh(){if(polling||appExited)return;polling=true;try{render(await api('state'));}catch(err){if(!$('locked').hidden||appExited)return;toast(err.message);}finally{polling=false;}}
if(!token){$('locked').hidden=false;$('setup').hidden=true;}else{refresh();setInterval(refresh,1200);}

$('quit-app').disabled=!token;
$('quit-app').onclick=()=>$('quit-dialog').showModal();
$('cancel-quit').onclick=()=>$('quit-dialog').close();
$('confirm-quit').onclick=async()=>{
  $('confirm-quit').disabled=true;
  try{
    await api('shutdown',{});appExited=true;$('quit-dialog').close();
    $('setup').hidden=true;$('workspace').hidden=true;$('quit-app').disabled=true;
    const message=element('section','notice');
    message.append(element('h2','','FreeP2P가 종료되었습니다.'),element('p','','이 탭을 닫아도 됩니다. 다시 사용하려면 FreeP2P 실행 파일을 열어 주세요.'));
    document.querySelector('main').append(message);
  }catch(err){toast(err.message);$('confirm-quit').disabled=false;}
};

$('limit-form').onsubmit=async e=>{e.preventDefault();$('save-limit').disabled=true;$('limit-error').hidden=true;try{await api('settings',{max_peers:Number($('live-max-peers').value)});toast('최대 참가자 수를 변경했습니다.');await refresh();}catch(err){$('limit-error').textContent=err.message;$('limit-error').hidden=false;}finally{$('save-limit').disabled=false;}};
