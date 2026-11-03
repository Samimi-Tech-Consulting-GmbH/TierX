const $ = id => document.getElementById(id);
let observerToken = "", target = "", uiOrigin = "", cards = [];
const escape = value => String(value).replace(/[&<>"']/g, character => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[character]));
const json = value => escape(JSON.stringify(value, null, 2));
const sample = {result:{host:"SANDBOX-ENDPOINT-01",src:"192.0.2.10",dest:"198.51.100.20",user:"synthetic.user",process:"powershell.exe",severity:"4",rule_name:"Synthetic sandbox alert",rule_id:"sandbox-1",_time:new Date().toISOString()}};
$("payload").value = JSON.stringify(sample, null, 2);
fetch("/config").then(response => response.json()).then(config => { target = config.target; uiOrigin = config.ui_origin || target; $("target").textContent = "Target: " + target; });
async function request(path, {method="GET", body, token=observerToken, signal, identity}={}) {
  const response = await fetch("/proxy" + path, {method, signal, headers:{"Content-Type":"application/json", ...(token?{Authorization:"Bearer " + token}:{}), ...(identity?{"Idempotency-Key":identity}:{})},body:body===undefined?undefined:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw Object.assign(new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail)), {status:response.status,body:result});
  return result;
}
$("login").onsubmit = async event => { event.preventDefault(); const controls = [...event.currentTarget.elements]; controls.forEach(control => control.disabled=true);
  try { const result = await request("/api/v1/auth/login", {method:"POST", body:{email:$("email").value,password:$("password").value},token:""}); observerToken=result.access_token; const me=await request("/api/v1/auth/me"); $("session").textContent="Observing as " + me.email; }
  catch(error){$("session").textContent=error.message;} finally{$("password").value="";controls.forEach(control=>control.disabled=false);} };
$("disconnect").onclick=()=>{observerToken="";$("entry-token").value="";cards.forEach(card=>stop(card,"CANCELLED"));$("session").textContent="Disconnected";render();};
$("format").onclick=()=>{try{$("payload").value=JSON.stringify(JSON.parse($("payload").value),null,2);}catch(error){$("message").textContent=error.message;}};
$("unique").onclick=()=>{try{const payload=JSON.parse($("payload").value);if(!payload.result)throw new Error("This example expects result._time; adjust your raw payload for your workflow schema.");payload.result._time=new Date().toISOString();payload.result.rule_id="sandbox-"+crypto.randomUUID();$("payload").value=JSON.stringify(payload,null,2);}catch(error){$("message").textContent=error.message;}};
const remaining=card=>Math.max(0,card.remaining-(card.started==null?0:performance.now()-card.started));
function stop(card,state){card.remaining=remaining(card);card.started=null;card.state=state;card.generation++;clearTimeout(card.timer);card.controller?.abort();}
function remove(card){stop(card,"CANCELLED");cards=cards.filter(value=>value!==card);render();}
function watch(card,fresh=false){stop(card,"WATCHING");if(fresh)card.remaining=300000;card.started=performance.now();const generation=card.generation;
  async function poll(){if(card.generation!==generation)return;if(remaining(card)<=0){stop(card,"TIMED_OUT");render();return;}card.controller=new AbortController();
    try{const result=await request(`/api/v2/tenants/${card.tenant}/runs/${card.run}`,{signal:card.controller.signal});if(card.generation!==generation)return;card.latest=result;card.error="";card.refreshed=new Date().toLocaleTimeString();if(["SUCCEEDED","SUCCEEDED_WITH_WARNINGS"].includes(result.state))stop(card,"COMPLETED");else if(["FAILED","CANCELLED"].includes(result.state))stop(card,"FAILED");}
    catch(error){if(card.generation!==generation)return;card.error=error.message;if([401,403].includes(error.status)){stop(card,"PAUSED");if(error.status===401)observerToken="";}}
    render();if(card.state==="WATCHING"&&card.generation===generation)card.timer=setTimeout(poll,5000);
  }poll();render();}
function add(accepted,tenant,response){if(cards.length===5)remove(cards[cards.length-1]);const card={id:crypto.randomUUID(),tenant,run:accepted.run_id,alert:accepted.alert_id,response,remaining:300000,started:null,state:"WATCHING",generation:0};cards.unshift(card);watch(card);}
async function send(pair=false){const buttons=[$("send"),$("duplicate")];buttons.forEach(button=>button.disabled=true);try{
  const match=$('path').value.trim().match(/^\/api\/v2\/workflows\/[a-z0-9][a-z0-9_-]{0,63}\/tenants\/([a-zA-Z0-9_-]+)\/ingest$/);if(!match)throw new Error("Enter a fixed workflow ingestion path, not a host URL.");
  const payload=JSON.parse($("payload").value);if(!payload||Array.isArray(payload)||typeof payload!=="object")throw new Error("Alert must be one JSON object.");
  for(let index=0;index<(pair?2:1);index++){const accepted=await request($("path").value.trim(),{method:"POST",body:payload,token:$("entry-token").value,identity:crypto.randomUUID()});add(accepted,match[1],accepted);$("message").textContent="Accepted " + accepted.alert_id + ". Watching independently.";}
}catch(error){$("message").textContent=error.message;}finally{buttons.forEach(button=>button.disabled=false);}}
$("send").onclick=()=>send();$("duplicate").onclick=()=>send(true);$("clear").onclick=()=>{cards.forEach(card=>stop(card,"CANCELLED"));cards=[];render();};
function render(){
  const opened = new Set([...(document.querySelectorAll?.("[data-detail][open]") || [])].map(element=>element.dataset.detail));
  $("cards").innerHTML=cards.map(card=>{
    const run=card.latest, version=run?.workflow_version?.definition_ref||run?.definition_ref||"Awaiting flow version";
    return `<article class="card" data-card="${card.id}"><h3>${escape(card.alert)}</h3>
      <p class="${card.state==="WATCHING"?"watching":card.state==="COMPLETED"?"success":""}">${card.state==="WATCHING"?'<i class="spinner"></i> ':""}${card.state} · <span data-remaining="${card.id}">${Math.ceil(remaining(card)/1000)}s</span> remaining · refreshed ${escape(card.refreshed||"never")}</p>
      <p><strong>Flow version: ${escape(version)}</strong> · app ${escape(run?.release_version||"unknown")} · ${escape(run?.release_sha?.slice(0,8)||"")}</p>
      ${card.error?`<p class="failure">${escape(card.error)}</p>`:""}
      <div class="buttons"><button data-action="${card.state==="WATCHING"?"pause":"resume"}">${card.state==="WATCHING"?"Pause":"Resume / watch again"}</button><button data-action="cancel">Cancel watching</button><button data-action="remove">Remove</button><a href="${escape(uiOrigin)}/dashboard/${escape(card.tenant)}/workflows/runs/${escape(card.run)}" target="_blank" rel="noopener noreferrer">Open full node debug</a></div>
      <details data-detail="${card.id}:accepted"><summary>Acceptance response</summary><pre>${json(card.response)}</pre></details>
      ${(run?.nodes||[]).map(node=>`<details data-detail="${card.id}:${escape(node.job_id)}"><summary>${escape(node.label||node.node_id)} · ${escape(node.node_type||"node")} · ${escape(node.state)} · route ${escape(node.port||"—")}</summary><p>${escape(node.definition_ref||run.definition_ref||"")} · attempts ${node.attempt_count||0} · elapsed ${node.node_elapsed_ms==null?"—":(node.node_elapsed_ms/1000).toFixed(1)+"s"}</p><h4>Safe input</h4><pre>${json(node.input_snapshot)}</pre><h4>Safe output</h4><pre>${json(node.output_snapshot||node.output)}</pre><h4>Decisions / errors</h4><pre>${json({decisions:node.decisions,selection:node.selection,error:node.error,wait_reason:node.wait_reason})}</pre></details>`).join("")}
      <details data-detail="${card.id}:latest"><summary>Latest run response</summary><pre>${json(run)}</pre></details></article>`;
  }).join("");
  for(const element of document.querySelectorAll?.("[data-detail]") || []) element.open=opened.has(element.dataset.detail);
}
$("cards").onclick=event=>{const button=event.target.closest("button[data-action]");if(!button)return;const card=cards.find(card=>card.id===button.closest("[data-card]").dataset.card);if(!card)return;const action=button.dataset.action;if(action==="remove")remove(card);else if(action==="pause")stop(card,"PAUSED");else if(action==="cancel")stop(card,"CANCELLED");else watch(card,["TIMED_OUT","CANCELLED","FAILED","COMPLETED"].includes(card.state));render();};
setInterval(()=>{for(const card of cards){const element=document.querySelector(`[data-remaining="${card.id}"]`);if(element)element.textContent=Math.ceil(remaining(card)/1000)+"s";if(card.state==="WATCHING"&&remaining(card)<=0){stop(card,"TIMED_OUT");render();}}},1000);
