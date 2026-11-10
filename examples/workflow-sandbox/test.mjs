import test from "node:test";
import assert from "node:assert/strict";
import { once } from "node:events";
import { createSandbox, allowed } from "./server.mjs";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
import { randomUUID } from "node:crypto";

async function watcherHarness() {
  const elements = new Map();
  const timers = new Map();
  let clock = 0, timerId = 0, calls = 0, outcome = "RUNNING";
  const context = vm.createContext({
    document: {getElementById(id) { if (!elements.has(id)) elements.set(id, {value:"",innerHTML:"",textContent:""}); return elements.get(id); }, querySelector:()=>null},
    performance: {now:()=>clock}, crypto:{randomUUID}, AbortController, Date,
    setTimeout(callback, delay) { timers.set(++timerId,{callback,at:clock+delay});return timerId; },
    clearTimeout(id) { timers.delete(id); }, setInterval() {},
    fetch: async path => ({ok:true,json:async()=>path==="/config"?{target:"http://127.0.0.1:8080"}:(calls++,{state:outcome,nodes:[]})}),
  });
  vm.runInContext(await readFile(new URL("app.js",import.meta.url),"utf8"),context);
  const settle=()=>new Promise(resolve=>setImmediate(resolve));
  return {context,timers,get calls(){return calls;},outcome(value){outcome=value;},
    async run(code){const value=vm.runInContext(code,context);await settle();return value;},
    async advance(ms){clock+=ms;const due=[...timers].filter(([,value])=>value.at<=clock);for(const[id,value]of due){timers.delete(id);await value.callback();}await settle();}};
}

test("watchers poll every five seconds, pause active time, resume and stop on terminal results",async()=>{
  const h=await watcherHarness();
  await h.run('add({run_id:"run",alert_id:"alert"},"tenant",{})');
  assert.equal(h.calls,1);
  await h.advance(4999);assert.equal(h.calls,1);
  await h.advance(1);assert.equal(h.calls,2);
  await h.run('stop(cards[0],"PAUSED")');
  const remaining=await h.run('remaining(cards[0])');
  await h.advance(120000);assert.equal(h.calls,2);assert.equal(await h.run('remaining(cards[0])'),remaining);
  h.outcome("STALLED");await h.run('watch(cards[0])');assert.equal(h.calls,3);
  assert.equal(await h.run('cards[0].state'),"WATCHING");
  h.outcome("SUCCEEDED");await h.advance(5000);
  assert.equal(await h.run('cards[0].state'),"COMPLETED");assert.equal(h.timers.size,0);
});

test("timeout, watch again, five-card eviction, cancellation and clear stop local timers",async()=>{
  const h=await watcherHarness();
  await h.run('add({run_id:"first",alert_id:"first"},"tenant",{})');
  await h.advance(300000);assert.equal(await h.run('cards[0].state'),"TIMED_OUT");
  await h.run('watch(cards[0],true)');assert.equal(await h.run('Math.ceil(remaining(cards[0]))'),300000);
  await h.run('globalThis.oldest=cards[0];for(let i=0;i<5;i++)add({run_id:"r"+i,alert_id:"a"+i},"tenant",{})');
  assert.equal(await h.run('cards.length'),5);assert.equal(await h.run('oldest.state'),"CANCELLED");
  assert.equal(await h.run('cards[0].alert'),"a4");
  await h.run('stop(cards[0],"CANCELLED")');assert.equal(await h.run('cards[0].state'),"CANCELLED");
  await h.run('document.getElementById("clear").onclick()');assert.equal(await h.run('cards.length'),0);assert.equal(h.timers.size,0);
});
test("only fixed ingestion, observer and login routes are allowed",()=>{
  assert(allowed("POST","/api/v2/workflows/triage/tenants/one/ingest"));
  assert(allowed("GET","/api/v2/tenants/one/runs/id"));
  for(const path of ["//evil.example", "/api/v2/admin/connectors", "/api/v1/admin/debug/ingest", "/api/v2/workflows/a/tenants/one/ingest/extra", "https://evil.example/api/v1/auth/login", "\\\\evil.example"]) assert.equal(allowed("POST",path),false);
  assert.throws(()=>createSandbox("https://user:password@example.com"));
  assert.throws(()=>createSandbox("http://example.com"));
});
test("proxy is fixed-origin, forwards only intended credentials, rejects redirects and foreign origins",async()=>{
  const calls=[];let redirect=false;
  const server=createSandbox("https://example.com",async(url,options)=>{calls.push({url:String(url),options});return new Response('{"run_id":"r","alert_id":"a"}',{status:redirect?302:202,headers:{"Content-Type":"application/json"}});});
  server.listen(0,"127.0.0.1");await once(server,"listening");
  const origin="http://127.0.0.1:"+server.address().port;
  try{
    const options={method:"POST",headers:{Authorization:"Bearer synthetic-entry", "Idempotency-Key":"delivery-one","Content-Type":"application/json"},body:"{}"};
    const path="/proxy/api/v2/workflows/triage/tenants/one/ingest";
    assert.equal((await fetch(origin+path,options)).status,202);
    assert.equal(calls[0].url,"https://example.com/api/v2/workflows/triage/tenants/one/ingest");
    assert.equal(calls[0].options.headers.Authorization,"Bearer synthetic-entry");
    assert.equal(calls[0].options.redirect,"manual");
    assert.equal((await fetch(origin+path,{...options,headers:{...options.headers,Origin:"https://evil.example"}})).status,403);
    assert.equal((await fetch(origin+path+"?destination=evil",options)).status,403);
    redirect=true;assert.equal((await fetch(origin+path,options)).status,502);
    assert.equal((await fetch(origin+"/config")).status,200);
  }finally{server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
});
