// Run with: node --test tests/session-expiry.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const html=fs.readFileSync('app/static/index.html','utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
new vm.Script(script); // Also syntax-check the complete served frontend.
function setup(){
  const elements=new Map();
  const storage=new Map([['mvt_token','expired'],['mvt_user','{}'],['other','keep']]);
  const context=vm.createContext({Headers,Error,sessionStorage:{removeItem:k=>storage.delete(k)},
    $:id=>{if(!elements.has(id)){const classes=new Set(id==='authPanel'?['hidden']:[]);elements.set(id,{classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),contains:x=>classes.has(x)},focus(){this.focused=true}})}return elements.get(id)},
    msg:(id,text)=>context.$(id).textContent=text,setStatus(){},closeWelcome(){},closeVisitPhotos(){},
    fetch:async()=>({status:401})});
  vm.runInContext("let token='expired',user={},managerMode=false,adminKey='',master=[],perfData=null;"+
    script.slice(script.indexOf('const SESSION_EXPIRED_MESSAGE'),script.indexOf('async function pinLogin'))+'\n'+
    script.match(/function logout\(\)\{[^\n]+/)[0],context);
  return {context,storage,run:code=>vm.runInContext(code,context)};
}
test('401 clears session, hides dashboard, shows login and focuses PIN',async()=>{
  const {context,storage,run}=setup();
  await assert.rejects(run("api('/stats')"),/session has expired/);
  assert.equal(run('token'), '');assert.equal(run('user'),null);
  assert.equal(storage.has('mvt_token'),false);assert.equal(storage.has('mvt_user'),false);assert.equal(storage.get('other'),'keep');
  assert.equal(context.$('app').classList.contains('hidden'),true);
  assert.equal(context.$('authPanel').classList.contains('hidden'),false);
  assert.match(context.$('authMsg').textContent,/Please log in again/);assert.equal(context.$('pin').focused,true);
});
test('login and admin-key 401 responses leave bearer session alone',async()=>{
  const {run}=setup();
  for(const headers of [{},{'X-API-Key':'wrong'}])await run(`sessionFetch('/auth/login',{headers:${JSON.stringify(headers)}})`);
  assert.equal(run('token'),'expired');
});
test('403, server errors and network failure do not log out',async()=>{
  const {context,run}=setup();
  for(const status of [200,403,500]){context.fetch=async()=>({status});await run("sessionFetch('/stats',{headers:{Authorization:'Bearer expired'}})");}
  context.fetch=async()=>{throw Error('Network failure')};
  await assert.rejects(run("api('/stats')"),/Network failure/);assert.equal(run('token'),'expired');
});
test('late 401 from old session cannot log out a newer login',async()=>{
  const {context,run}=setup();let finish;context.fetch=()=>new Promise(resolve=>finish=resolve);
  const pending=run("api('/stats')");run("token='new-login'");finish({status:401});
  await assert.rejects(pending,/Session changed/);assert.equal(run('token'),'new-login');
});
test('simultaneous 401s clear once and reject late responses',async()=>{
  const {run}=setup();const results=await Promise.allSettled([run("api('/stats')"),run("api('/visits')")]);
  assert.ok(results.every(r=>r.status==='rejected'));assert.equal(run('token'),'');
});
