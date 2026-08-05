"""Embedded single-page frontend + YAML serializer for the migration web UI."""

from __future__ import annotations

from typing import Any

from ..config import Config

# ---------------------------------------------------------------------------
# Friendly single-page UI (vanilla HTML/CSS/JS, no build step)
# ---------------------------------------------------------------------------
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>AWS 跨组织账户迁移 · 友好前端</title>
<style>
  :root{
    --bg:#0f172a; --panel:#1e293b; --panel2:#273449; --line:#334155;
    --txt:#e2e8f0; --muted:#94a3b8; --accent:#38bdf8; --accent2:#22d3ee;
    --ok:#34d399; --warn:#fbbf24; --err:#f87171; --pending:#64748b;
    --radius:14px;
  }
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
    "PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--txt);
    line-height:1.5}
  .wrap{max-width:1080px;margin:0 auto;padding:24px 20px 60px}
  header.top{display:flex;align-items:center;gap:14px;margin-bottom:8px}
  .logo{width:42px;height:42px;border-radius:12px;
    background:linear-gradient(135deg,var(--accent),var(--accent2));
    display:grid;place-items:center;font-weight:800;color:#06283d;font-size:20px}
  h1{font-size:22px;margin:0}
  .sub{color:var(--muted);font-size:13px;margin-bottom:22px}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);
    padding:18px 20px;margin-bottom:18px}
  .card h2{font-size:15px;margin:0 0 14px;display:flex;align-items:center;gap:8px}
  .pill{font-size:12px;padding:3px 10px;border-radius:999px;background:var(--panel2);
    border:1px solid var(--line);color:var(--muted)}
  .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
    gap:12px;margin-bottom:18px}
  .step{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    padding:14px;display:flex;flex-direction:column;gap:6px}
  .step .n{width:26px;height:26px;border-radius:50%;background:var(--panel2);
    display:grid;place-items:center;font-weight:700;font-size:13px;color:var(--accent)}
  .step .t{font-size:13px;font-weight:600}
  .step .d{font-size:12px;color:var(--muted)}
  .actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
  button{font:inherit;cursor:pointer;border:none;border-radius:10px;padding:10px 16px;
    font-weight:600;transition:.15s;color:#06283d}
  .btn-primary{background:linear-gradient(135deg,var(--accent),var(--accent2))}
  .btn-primary:disabled{opacity:.5;cursor:not-allowed}
  .btn-ghost{background:var(--panel2);color:var(--txt);border:1px solid var(--line)}
  .btn-sm{padding:7px 12px;font-size:13px}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th,td{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line)}
  th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
  .badge{font-size:12px;padding:2px 9px;border-radius:999px;font-weight:600;display:inline-block}
  .b-ok{background:rgba(52,211,153,.15);color:var(--ok)}
  .b-warn{background:rgba(251,191,36,.15);color:var(--warn)}
  .b-err{background:rgba(248,113,113,.15);color:var(--err)}
  .b-pending{background:rgba(100,116,139,.2);color:var(--muted)}
  .token{display:flex;align-items:center;gap:10px;font-size:13px;margin-bottom:4px}
  .dot{width:10px;height:10px;border-radius:50%}
  .dot.ok{background:var(--ok);box-shadow:0 0 8px var(--ok)}
  .dot.no{background:var(--err);box-shadow:0 0 8px var(--err)}
  .hint{font-size:12px;color:var(--muted)}
  code{background:var(--panel2);padding:2px 7px;border-radius:6px;font-size:12px}
  .form-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
  label{font-size:12px;color:var(--muted);display:block;margin-bottom:5px}
  input{width:100%;padding:9px 11px;border-radius:9px;border:1px solid var(--line);
    background:var(--panel2);color:var(--txt);font:inherit}
  input:focus{outline:none;border-color:var(--accent)}
  .sec-title{font-size:13px;font-weight:700;margin:14px 0 8px;color:var(--accent2)}
  .acct-row{display:grid;grid-template-columns:1fr 1fr;gap:10px}
  .log{background:#0b1220;border:1px solid var(--line);border-radius:12px;
    height:300px;overflow:auto;padding:12px 14px;font-family:ui-monospace,Menlo,Consolas,monospace;
    font-size:12.5px;line-height:1.6}
  .log .e{white-space:pre-wrap;word-break:break-word}
  .log .t{color:#475569;margin-right:8px}
  .log .INFO{color:#cbd5e1}.log .WARNING{color:var(--warn)}.log .ERROR{color:var(--err)}
  .log .DEBUG{color:#64748b}
  .toast{position:fixed;bottom:22px;left:50%;transform:translateX(-50%);
    background:var(--panel);border:1px solid var(--line);padding:11px 18px;border-radius:10px;
    box-shadow:0 10px 30px rgba(0,0,0,.4);font-size:13px;opacity:0;transition:.25s;pointer-events:none}
  .toast.show{opacity:1}
  .collapse-btn{background:none;border:none;color:var(--accent);cursor:pointer;font-size:13px;padding:0}
  details summary{cursor:pointer;color:var(--accent2);font-size:13px;font-weight:600}
</style>
</head>
<body>
<div class="wrap">
  <header class="top">
    <div class="logo">⇄</div>
    <div>
      <h1>AWS 跨组织账户迁移</h1>
    </div>
    <span class="pill" id="verPill" style="margin-left:auto" title="当前运行的代码版本（git commit）">ver …</span>
    <span class="pill" id="busyPill" style="display:none">运行中…</span>
  </header>
  <div class="sub">从新组织批量邀请旧组织账户 → 用旧组织 IAM Identity Center 登录门户取得各账户临时凭证 → 以目标账户身份接受邀请。</div>

  <!-- Steps overview -->
  <div class="steps">
    <div class="step"><div class="n">1</div><div class="t">配置</div><div class="d">填写新组织 / 旧组织 SSO / 目标账户</div></div>
    <div class="step"><div class="n">2</div><div class="t">发邀请</div><div class="d">新组织管理账户批量邀请</div></div>
    <div class="step"><div class="n">3</div><div class="t">SSO 登录</div><div class="d">旧组织用户登录访问门户</div></div>
    <div class="step"><div class="n">4</div><div class="t">接受邀请</div><div class="d">以目标账户临时凭证接受</div></div>
    <div class="step"><div class="n">5</div><div class="t">移入 OU</div><div class="d">可选：归入目标组织单元</div></div>
  </div>

  <!-- Config -->
  <div class="card">
    <h2>⚙️ 配置 <button class="collapse-btn" id="toggleCfg">[ 收起/展开 ]</button></h2>
    <div id="cfgBox">
      <!-- Credential auto-detect -->
      <div class="sec-title">🔑 AWS 凭证自动识别（可选）</div>
      <div style="display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap">
        <div style="flex:1;min-width:180px"><label>Access Key ID</label><input id="c_ak" placeholder="AKIA..." autocomplete="off"></div>
        <div style="flex:1;min-width:180px"><label>Secret Access Key</label><input id="c_sk" type="password" placeholder="••••..." autocomplete="off"></div>
        <div style="min-width:120px"><label>Region</label><input id="c_resolve_region" placeholder="us-east-1" value="us-east-1"></div>
        <button class="btn-primary btn-sm" id="btnResolve">自动识别 →</button>
      </div>
      <div class="hint" id="resolveHint" style="margin-top:5px"></div>

      <div class="sec-title" style="margin-top:14px">新组织管理账户</div>
      <div class="form-grid">
        <div><label>新组织管理账户 Profile</label><input id="c_mgmt_profile" placeholder="mgmt-new"></div>
        <div><label>新组织管理账户 ID</label><input id="c_mgmt_id" placeholder="111111111111"></div>
        <div><label>目标 OU ID（可选）</label><input id="c_ou" placeholder="ou-xxxx"></div>
      </div>
      <div class="sec-title">旧组织 IAM Identity Center (SSO)</div>
      <div class="form-grid">
        <div><label>Start URL</label><input id="c_start" placeholder="https://xxx.awsapps.com/start"></div>
        <div><label>SSO Region</label><input id="c_sso_region" placeholder="ap-southeast-1"></div>
        <div><label>角色 / Permission Set 名</label><input id="c_role" placeholder="AWSAdministratorAccess"></div>
        <div><label>AWS CLI Profile（SSO Login 用）</label><input id="c_aws_profile" placeholder="sso-old"></div>
      </div>
      <div class="sec-title">目标账户</div>
      <div id="acctList" class="acct-row"></div>
      <div class="actions" style="margin-top:10px">
        <button class="btn-ghost btn-sm" id="addAcct">+ 添加账户</button>
        <button class="btn-primary btn-sm" id="saveCfg">保存配置</button>
        <span class="hint" id="saveHint"></span>
      </div>

      <!-- Batch account import -->
      <div class="sec-title" style="margin-top:16px">📥 批量导入账户（txt / csv）</div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
        <button class="btn-ghost btn-sm" id="btnUploadAccts">📂 上传文件</button>
        <input type="file" id="acctFileInput" accept=".txt,.csv" style="display:none">
        <span class="hint">格式：</span>
        <select id="acctFmt" style="background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:7px;padding:5px 8px">
          <option value="auto">自动识别</option><option value="csv">CSV</option><option value="txt">纯文本</option>
        </select>
      </div>
      <textarea id="acctPaste" rows="4" placeholder="粘贴账户列表，每行一个 ID，或 `id,email` 格式：&#10;123456789012,user1@example.com&#10;987654321098&#10;...
或 CSV（自动识别）：&#10;123456789012,user1@example.com&#10;987654321098,user2@example.com" style="width:100%;background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:9px;padding:9px 11px;font:inherit;resize:vertical;box-sizing:border-box;line-height:1.5"></textarea>
      <div style="margin-top:8px">
        <button class="btn-primary btn-sm" id="btnParseAccts">预览并导入到账户列表</button>
        <span class="hint" id="parseHint"></span>
      </div>
      <div id="acctParsePreview" style="margin-top:8px"></div>
    </div>
  </div>

  <!-- Actions -->
  <div class="card">
    <h2>🚀 执行</h2>
    <div class="token">
      <span class="dot no" id="tokDot"></span>
      <span id="tokText">SSO token 状态检测中…</span>
    </div>
    <div class="hint" style="margin-bottom:12px">提示：点击「SSO Login」在新窗口运行登录命令，完成后点击「刷新 token」。</div>
    <div class="actions">
      <button class="btn-primary" id="btnSSOLogin">🔐 SSO Login</button>
      <button class="btn-ghost" id="btnInvite">① 发邀请</button>
      <button class="btn-ghost" id="btnAccept">④ 接受邀请</button>
      <button class="btn-ghost" id="btnMove">⑤ 移入 OU</button>
      <button class="btn-primary" id="btnRun">🚀 一键运行</button>
      <button class="btn-ghost btn-sm" id="btnRefreshTok">刷新 token</button>
      <button class="btn-ghost btn-sm" id="btnRefreshStatus">刷新状态</button>
      <button class="btn-ghost btn-sm" id="btnClear" style="color:var(--err);margin-left:auto">🗑 清空账户与状态</button>
    </div>
  </div>

  <!-- Account status -->
  <div class="card">
    <h2>📋 各账户状态</h2>
    <table>
      <thead><tr><th>账户 ID</th><th>Email</th><th>邀请</th><th>握手 ID</th><th>接受</th><th>移入 OU</th></tr></thead>
      <tbody id="acctBody"><tr><td colspan="6" class="hint">加载中…</td></tr></tbody>
    </table>
  </div>

  <!-- Live log -->
  <div class="card">
    <h2>📜 实时日志 <span class="pill">SSE</span></h2>
    <div class="log" id="log"></div>
  </div>

  <details style="margin-top:6px">
    <summary>查看 API / 故障排查说明</summary>
    <div class="hint" style="margin-top:10px;line-height:1.8">
      • 接受邀请需旧组织 SSO 角色具备 <code>organizations:AcceptHandshake</code> 权限。<br>
      • SSO 临时凭证有会话时长限制；大批量账户中途可能需重新 <code>aws sso login</code>。<br>
      • 状态保存在 <code>migration_state.json</code>，可断点续跑。<br>
      • 新组织须存在 ≥7 天；组织内创建的成员账户须创建 ≥4 天（受邀账户不受限）。
    </div>
  </details>
</div>

<div class="toast" id="toast"></div>

<script>
const $ = id => document.getElementById(id);
function toast(msg, ok=true){
  const t=$('toast'); t.textContent=msg; t.style.borderColor=ok?'var(--ok)':'var(--err)';
  t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),2600);
}
function badge(val, okText='是', noText='否'){
  if(val===true) return `<span class="badge b-ok">${okText}</span>`;
  if(val===false) return `<span class="badge b-err">${noText}</span>`;
  return `<span class="badge b-pending">待处理</span>`;
}

// ---- load config ----
async function loadConfig(){
  const r = await fetch('/api/config'); const c = await r.json();
  $('verPill').textContent = 'ver ' + (c.version||'?');
  $('c_mgmt_profile').value = c.new_org.management_account_profile||'';
  $('c_mgmt_id').value     = c.new_org.management_account_id||'';
  $('c_ou').value          = c.new_org.target_ou_id||'';
  $('c_start').value       = c.sso.start_url||'';
  $('c_sso_region').value   = c.sso.sso_region||'';
  $('c_role').value        = c.sso.role_name||'';
  $('c_aws_profile').value = c.sso.aws_profile||'';
  const list = $('acctList'); list.innerHTML='';
  (c.target_accounts||[]).forEach(a=>addAcctRow(a.id, a.email));
}
function addAcctRow(id='', email=''){
  const wrap=document.createElement('div'); wrap.className='acct-row';
  wrap.innerHTML=`<input placeholder="222222222222" value="${id}" class="a-id">
    <input placeholder="email@example.com" value="${email}" class="a-em">
    <button class="btn-ghost btn-sm" onclick="this.parentNode.remove()" style="grid-column:1/3">删除</button>`;
  $('acctList').appendChild(wrap);
}

// ---- save config ----
$('saveCfg').onclick = async ()=>{
  const accts=[]; document.querySelectorAll('#acctList .acct-row').forEach(row=>{
    const id=row.querySelector('.a-id').value.trim();
    const em=row.querySelector('.a-em').value.trim();
    if(id) accts.push({id, email:em});
  });
  const payload={
    new_org:{ management_account_profile:$('c_mgmt_profile').value.trim(),
              management_account_id:$('c_mgmt_id').value.trim(),
              target_ou_id:$('c_ou').value.trim() },
    sso:{ start_url:$('c_start').value.trim(), sso_region:$('c_sso_region').value.trim(),
          role_name:$('c_role').value.trim(), aws_profile:$('c_aws_profile').value.trim() },
    settings:{ region:'us-east-1' },
    target_accounts:accts
  };
  const r=await fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)});
  const j=await r.json();
  $('saveHint').textContent = j.ok?'已保存 ✓':('保存失败: '+j.error);
  toast(j.ok?'配置已保存':'保存失败', j.ok);
  loadStatus();
};
$('addAcct').onclick=()=>addAcctRow();

// ---- resolve credentials (auto-detect AK/SK) ----
async function resolveCredentials(){
  const ak=$('c_ak').value.trim();
  const sk=$('c_sk').value.trim();
  const region=$('c_resolve_region').value.trim()||'us-east-1';
  if(!ak){ toast('请填写 Access Key ID', false); return; }
  if(!sk){ toast('请填写 Secret Access Key', false); return; }
  $('resolveHint').textContent='识别中…';
  try{
    const r=await fetch('/api/resolve-credentials',{
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify({access_key_id:ak, secret_access_key:sk, region})
    });
    const j=await r.json();
    if(j.ok){
      $('resolveHint').innerHTML=
        `<span style="color:var(--ok)">&#10003; 识别成功！</span>`+
        ` 账户ID: <b>${j.account_id}</b>`+
        (j.in_org ? ` | <span style="color:var(--ok)">在组织中</span>` : ` | <span style="color:var(--warn)">未在组织</span>`)+
        (j.profile_created ? ' | 已在本机创建 CLI profile' : ' | 本机已有该 profile');
      $('c_mgmt_id').value=j.account_id;
      $('c_mgmt_profile').value=j.suggested_profile;
      toast('已自动填充配置并在本机创建 CLI profile');
    } else {
      $('resolveHint').innerHTML=`<span style="color:var(--err)">&#10007; ${j.error}</span>`;
      toast('识别失败: '+j.error, false);
    }
  }catch(e){ $('resolveHint').textContent='请求失败: '+e.message; }
}
$('btnResolve').onclick=resolveCredentials;

// ---- batch account parse + import ----
$('btnUploadAccts').onclick=()=>$('acctFileInput').click();
$('acctFileInput').onchange=async e=>{
  const file=e.target.files[0]; if(!file) return;
  const text=await file.text();
  $('acctPaste').value=text;
  toast('已加载 '+file.name+'，点击「预览并导入」继续');
};

async function parseAndImportAccts(){
  const content=$('acctPaste').value.trim();
  const fmt=$('acctFmt').value;
  if(!content){ toast('请粘贴或上传账户列表', false); return; }
  const r=await fetch('/api/parse-accounts',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({content, format:fmt})
  });
  const j=await r.json();
  if(!j.ok){ toast('解析失败: '+j.error, false); return; }
  const {accounts, errors}=j;
  if(!accounts.length){ toast('未解析到有效账户 ID', false); return; }

  // Show preview
  const preview=$('acctParsePreview');
  let html=`<table style="font-size:12px;width:auto">
    <thead><tr><th>#</th><th>账户 ID</th><th>Email</th></tr></thead><tbody>`;
  accounts.forEach((a,i)=>html+=`<tr><td>${i+1}</td><td><code>${a.id}</code></td><td>${a.email||'<span style="color:var(--muted)">-</span>'}</td></tr>`);
  html+='</tbody></table>';
  if(errors.length) html+=`<div class="hint" style="color:var(--warn);margin-top:6px">跳过 ${errors.length} 行: ${errors.slice(0,3).join('; ')}${errors.length>3?'...':''}</div>`;
  preview.innerHTML=html;

  // Append to account list
  accounts.forEach(a=>{
    // avoid duplicates
    const ids=[...document.querySelectorAll('.a-id')].map(i=>i.value.trim());
    if(!ids.includes(a.id)) addAcctRow(a.id, a.email);
  });
  $('parseHint').textContent=`已导入 ${accounts.length} 个账户（去重后追加到列表，保存配置后生效）`;
  toast(`已追加 ${accounts.length} 个账户，请检查后点击「保存配置」`);
}
$('btnParseAccts').onclick=parseAndImportAccts;

// ---- SSO Login ----
async function doSSOLogin(){
  const r=await fetch('/api/sso-login',{method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
  const j=await r.json();
  if(j.ok){
    toast(j.profile_status==='created' ? '已自动创建 SSO profile 并打开登录窗口'
        : j.profile_status==='updated' ? '已同步新 Start URL 到 profile 并打开登录窗口'
        : '已打开 SSO 登录窗口，请在窗口中完成认证');
  } else {
    if(j.need_profile){
      toast('请先填写「AWS CLI Profile」再点 SSO Login', false);
      $('c_aws_profile').focus();
    } else {
      toast('SSO Login 失败: '+j.error, false);
    }
  }
}
$('btnSSOLogin').onclick=doSSOLogin;

// ---- status ----
async function loadStatus(){
  const r=await fetch('/api/status'); const s=await r.json();
  $('busyPill').style.display = s.busy?'inline-block':'none';
  const body=$('acctBody'); body.innerHTML='';
  if(!s.accounts.length){ body.innerHTML='<tr><td colspan="6" class="hint">未配置目标账户</td></tr>'; return; }
  s.accounts.forEach(a=>{
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${a.id}</td><td>${a.email||''}</td>
      <td>${badge(a.invited,'已邀请')}</td>
      <td class="hint">${a.handshake_id||'-'}</td>
      <td>${badge(a.accepted,'已接受')}</td>
      <td>${badge(a.moved,'已移入')}</td>`;
    body.appendChild(tr);
  });
  ['btnInvite','btnAccept','btnMove','btnRun'].forEach(b=>$(b).disabled=s.busy);
}

// ---- token ----
async function loadToken(){
  try{
    const r=await fetch('/api/token'); const j=await r.json();
    $('tokDot').className='dot '+(j.present?'ok':'no');
    $('tokText').textContent = j.present?'SSO token 已就绪 ✓':'未检测到 SSO token（请先 `aws sso login`）';
  }catch(e){}
}
$('btnRefreshTok').onclick=loadToken;
$('btnRefreshStatus').onclick=()=>{loadStatus();loadToken();};

// ---- actions ----
async function doAction(action){
  const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({action})});
  const j=await r.json();
  if(j.ok){ toast('已启动：'+action); loadStatus(); }
  else toast('启动失败',false);
}
$('btnInvite').onclick=()=>doAction('invite');
$('btnAccept').onclick=()=>doAction('accept');
$('btnMove').onclick=()=>doAction('move');
$('btnClear').onclick=async()=>{
  if(!confirm('将清空配置中的全部目标账户，并删除所有账户的迁移状态记录（migration_state.json）。\n此操作不可恢复，确定继续？')) return;
  const r=await fetch('/api/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  const j=await r.json();
  if(j.ok){ toast('已清空目标账户与状态'); loadConfig(); loadStatus(); }
  else toast('清空失败: '+(j.error||''), false);
};
$('btnRun').onclick=()=>{ if(confirm('将依次执行：发邀请 → 接受邀请（需 SSO token）→ 移入 OU。\n确保已 `aws sso login`。继续？')) doAction('run'); };

// ---- collapse ----
$('toggleCfg').onclick=()=>{ const b=$('cfgBox'); b.style.display=b.style.display==='none'?'block':'none'; };

// ---- SSE log ----
const logEl=$('log');
function appendLog(e){
  const div=document.createElement('div'); div.className='e '+e.level;
  div.innerHTML=`<span class="t">${e.t}</span>${e.msg}`;
  logEl.appendChild(div); logEl.scrollTop=logEl.scrollHeight;
}
const es=new EventSource('/api/logs');
es.onmessage=ev=>{ try{ appendLog(JSON.parse(ev.data)); }catch(e){} };
es.onerror=()=>{}; // auto-reconnect

// init
loadConfig(); loadStatus(); loadToken();
setInterval(loadStatus, 5000);
</script>
</body>
</html>
"""


def config_to_yaml(cfg: Config) -> str:
    """Hand-rolled YAML writer producing a clean, human-editable file."""
    L: list[str] = []
    n = cfg.new_org
    L.append("# 跨组织 AWS 账户迁移 - 配置")
    L.append("new_organization:")
    L.append(f"  management_account_profile: {_q(n.management_account_profile)}")
    L.append(f"  management_account_id: {_q(n.management_account_id)}")
    L.append(f"  target_ou_id: {_q(n.target_ou_id)}")
    L.append(f"  move_poll_timeout: {n.move_poll_timeout}")
    L.append("")
    s = cfg.sso
    L.append("old_organization_sso:")
    L.append(f"  start_url: {_q(s.start_url)}")
    L.append(f"  sso_region: {_q(s.sso_region)}")
    L.append(f"  role_name: {_q(s.role_name)}")
    L.append(f"  aws_profile: {_q(getattr(s, 'aws_profile', ''))}")
    L.append(f"  access_token: {_q(s.access_token)}")
    L.append("")
    L.append("target_accounts:")
    if cfg.target_accounts:
        for a in cfg.target_accounts:
            L.append(f"  - id: {_q(a['id'])}")
            L.append(f"    email: {_q(a.get('email', ''))}")
    else:
        L.append("  []")
    L.append("")
    st = cfg.settings
    L.append("settings:")
    L.append(f"  region: {_q(st.region)}")
    L.append(f"  state_file: {_q(st.state_file)}")
    L.append(f"  poll_interval: {st.poll_interval}")
    L.append(f"  poll_max_attempts: {st.poll_max_attempts}")
    L.append("")
    return "\n".join(L)


def _q(v: Any) -> str:
    """Quote a scalar for YAML, escaping so the output always re-parses.

    Also strips one layer of quotes the user may have typed into a form field
    ("sso-old" -> sso-old), which previously produced unparseable ""..."" output.
    """
    if v is None:
        return '""'
    text = str(v).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'"):
        text = text[1:-1]
    text = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'
