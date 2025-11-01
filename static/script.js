// Add your JavaScript here
// static/script.js
async function post(path, form) {
  const res = await fetch(path, {method:'POST', body: form});
  return res.json();
}
async function getJSON(path) {
  const res = await fetch(path);
  return res.json();
}

/* --- Dashboard auth helpers --- */
function showRegister(){ document.getElementById('auth_box').innerHTML = `<input id="reg_username" placeholder="username"/><input id="reg_password" placeholder="password" type="password"/><button onclick="register()">Register</button>`; }

async function register() {
  const u = document.getElementById('reg_username').value, p = document.getElementById('reg_password').value;
  if(!u||!p) return alert('fill');
  const fd = new FormData(); fd.append('username', u); fd.append('password', p);
  const j = await post('/api/register', fd);
  if(j.ok) alert('registered'); else alert(JSON.stringify(j));
}

async function login(){
  const u = document.getElementById('login_username')?.value || document.getElementById('username')?.value;
  const p = document.getElementById('login_password')?.value || document.getElementById('password')?.value;
  if(!u||!p) return alert('fill');
  const fd = new FormData(); fd.append('username', u); fd.append('password', p);
  const j = await post('/api/login', fd);
  if(j.access_token){
    localStorage.setItem('vp_token', j.access_token);
    localStorage.setItem('vp_user', JSON.stringify(j.user));
    alert('login ok');
    location.href = '/';
  } else alert(JSON.stringify(j));
}

function logout(){ localStorage.removeItem('vp_token'); localStorage.removeItem('vp_user'); location.href='/'; }

/* --- task helpers --- */
function computeCoinsNeeded() {
  const visits = Number(document.getElementById('visits_input')?.value || 0);
  getJSON('/api/settings').then(js => {
    const vpc = js.VISITS_PER_COIN || 1000;
    document.getElementById('coins_needed').innerText = Math.ceil(visits / vpc);
  });
}
document.addEventListener('input', (e) => { if(e.target && e.target.id==='visits_input') computeCoinsNeeded(); });

async function startTask(){
  const token = localStorage.getItem('vp_token');
  if(!token) return alert('login');
  const uid = document.getElementById('uid_input').value;
  const visits = Number(document.getElementById('visits_input').value || 0);
  if(!uid || visits<=0) return alert('fill uid/visits');
  const fd = new FormData(); fd.append('token', token); fd.append('uid', uid); fd.append('visits', visits);
  const j = await post('/api/tasks/start', fd);
  if(j.ok){ alert('Started '+j.task_id); loadTasks(); } else alert(JSON.stringify(j));
}

async function stopTask(id){
  const token = localStorage.getItem('vp_token');
  if(!token) return alert('login');
  const fd = new FormData(); fd.append('token', token);
  const j = await post('/api/tasks/' + id + '/stop', fd);
  if(j.ok) { alert('stop requested'); setTimeout(loadTasks,1500); } else alert(JSON.stringify(j));
}

async function loadTasks(){
  const token = localStorage.getItem('vp_token');
  if(!token) return;
  const res = await fetch('/api/tasks?token='+encodeURIComponent(token));
  const j = await res.json();
  const tasks = j.tasks || [];
  let html = '<table style="width:100%"><thead><tr><th>ID</th><th>UID</th><th>Req</th><th>Coins</th><th>Status</th><th>Gained</th><th>Act</th></tr></thead><tbody>';
  for(const t of tasks){
    const gained = (t.last_successful||0) - (t.start_successful||0);
    html += `<tr><td>${t.id}</td><td>${t.uid}</td><td>${t.requested_visits}</td><td>${t.coins_deducted}</td><td>${t.status}</td><td>${gained}</td><td><button onclick="stopTask(${t.id})">Stop</button></td></tr>`;
  }
  html += '</tbody></table>';
  const el = document.getElementById('tasks_area'); if(el) el.innerHTML = html;
}

/* --- admin helpers --- */
let admin_pass = null;
async function adminLogin(){
  const u = document.getElementById('admin_user').value, p = document.getElementById('admin_pass').value;
  if(!u||!p) return alert('fill admin creds');
  admin_pass = p;
  loadUsers(); loadRedeems();
}
async function loadUsers(){
  if(!admin_pass) return;
  const res = await fetch('/api/admin/users?admin_pass='+encodeURIComponent(admin_pass));
  const j = await res.json();
  if(j.error) return alert(JSON.stringify(j));
  let html = '<table style="width:100%"><thead><tr><th>ID</th><th>Username</th><th>Coins</th><th>Visits</th><th>Action</th></tr></thead><tbody>';
  for(const u of j.users){
    html += `<tr><td>${u.id}</td><td>${u.username}</td><td>${u.coins}</td><td>${u.total_visits||0}</td><td><button onclick="promptAdd(${u.id})">Add</button></td></tr>`;
  }
  html += '</tbody></table>';
  document.getElementById('users_area').innerHTML = html;
}
function promptAdd(uid){ const coins = prompt('coins to add'); if(!coins) return; document.getElementById('a_uid').value = uid; document.getElementById('a_coins').value = coins; adminAddCoins(); }
async function adminAddCoins(){
  if(!admin_pass) return alert('login');
  const uid = document.getElementById('a_uid').value, coins = document.getElementById('a_coins').value;
  const fd = new FormData(); fd.append('admin_pass', admin_pass); fd.append('coins', coins);
  const res = await fetch('/api/admin/users/' + uid + '/add_coins', { method:'POST', body: fd });
  const j = await res.json();
  if(j.ok){ alert('added'); loadUsers(); } else alert(JSON.stringify(j));
}
async function loadRedeems(){
  if(!admin_pass) return;
  const res = await fetch('/api/admin/redeems?admin_pass='+encodeURIComponent(admin_pass));
  const j = await res.json();
  if(j.error) return alert(JSON.stringify(j));
  let html = '<table style="width:100%"><thead><tr><th>ID</th><th>User</th><th>Amount</th><th>Code</th><th>Status</th></tr></thead><tbody>';
  for(const r of j.redeems){ html += `<tr><td>${r.id}</td><td>${r.user_id}</td><td>${r.amount}</td><td>${r.code}</td><td>${r.status}</td></tr>`; }
  html += '</tbody></table>';
  document.getElementById('redeems_area').innerHTML = html;
}
async function approveRedeem(){
  if(!admin_pass) return alert('login');
  const rid = document.getElementById('rid').value;
  const fd = new FormData(); fd.append('admin_pass', admin_pass);
  const res = await fetch('/api/admin/redeems/' + rid + '/approve', { method:'POST', body: fd });
  const j = await res.json();
  if(j.ok){ alert('approved ' + j.credited + ' coins'); loadRedeems(); loadUsers(); } else alert(JSON.stringify(j));
}

/* --- initial actions --- */
window.addEventListener('load', () => {
  computeCoinsNeeded();
  const token = localStorage.getItem('vp_token');
  if(token) { loadTasks(); setInterval(loadTasks, 10000); }
});