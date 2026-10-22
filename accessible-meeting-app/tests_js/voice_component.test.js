const {JSDOM, VirtualConsole} = require("jsdom"); const vc = new VirtualConsole(); vc.sendTo(console); const fs = require("fs");
const html = fs.readFileSync(__dirname + "/../components/voice_assistant/frontend/index.html","utf8");
const sent = [], spoken = []; let recInstances = [];
const dom = new JSDOM(html, {runScripts:"dangerously", pretendToBeVisual:true, virtualConsole: vc, url:"http://localhost/",
  beforeParse(w){
    w.parent.postMessage = (m)=>{ sent.push(m); };           // window.parent === window in jsdom top-level; capture protocol
    w.postMessage = (m)=>{ sent.push(m); };
    class SR { constructor(){ this.started=false; recInstances.push(this);} start(){this.started=true;} abort(){this.started=false; this.aborted=true;} }
    w.webkitSpeechRecognition = SR;
    w.SpeechSynthesisUtterance = function(t){ this.text=t; };
    w.speechSynthesis = { speak(u){ spoken.push(u.text); setTimeout(()=>u.onend && u.onend(), 5); }, cancel(){}, getVoices(){return [];} };
    w.AudioContext = function(){ return {createOscillator(){return {frequency:{},connect(){},start(){},stop(){}}},createGain(){return {gain:{},connect(){}}},destination:{},close(){}} };
  }});
const w = dom.window; const sleep = ms => new Promise(r=>setTimeout(r,ms));
const render = (args)=> w.dispatchEvent(new w.MessageEvent("message",{data:{type:"streamlit:render",args}}));
(async()=>{
  const log=(k,ok)=>console.log((ok?"PASS":"FAIL")+"  "+k);
  log("announces componentReady", sent.some(m=>m.type==="streamlit:componentReady"));
  render({queue:[{id:1,text:"Voice assistant ready. Say create account."},{id:2,beep:true},{id:3,text:"Second sentence."}],listening:true,lang:"en-US",rate:1.0,sid:"abc"});
  await sleep(30);
  log("nothing spoken before the user presses start (browser gesture rule)", spoken.length===0);
  w.document.getElementById("toggle").click(); await sleep(700);
  log("after Start: queued text is spoken in order", spoken[0]&&spoken[0].startsWith("Voice assistant ready") && spoken.includes("Second sentence."));
  await sleep(100);
  log("recognition starts only AFTER speaking finished (no echo)", recInstances.length>=1 && recInstances[recInstances.length-1].started===true);
  const rec = recInstances[recInstances.length-1];
  const before = spoken.length;
  // simulate a final recognition result
  rec.onresult({resultIndex:0, results:[Object.assign([{transcript:"create account", confidence:0.93}],{isFinal:true})]});
  const val = sent.filter(m=>m.type==="streamlit:setComponentValue").pop();
  log("final speech is sent to Python", val && val.value.type==="speech" && val.value.text==="create account" && val.value.id);
  // Python replies with a new queue item; old ones must not be repeated
  render({queue:[{id:1,text:"Voice assistant ready. Say create account."},{id:2,beep:true},{id:3,text:"Second sentence."},{id:4,text:"What is your full name?"}],listening:true,lang:"en-US",rate:1,sid:"abc"});
  await sleep(400);
  log("only the NEW item is spoken (no repeats)", spoken.slice(before).join("|")==="What is your full name?");
  // pause from python
  render({queue:[{id:4,text:"x"}],listening:false,lang:"en-US",rate:1,sid:"abc"}); await sleep(30);
  log("listening=false stops recognition", rec.aborted===true || recInstances[recInstances.length-1].started===false);
  // new session id resets the 'already spoken' counter
  const n=spoken.length; render({queue:[{id:1,text:"New session greeting"}],listening:true,lang:"en-US",rate:1,sid:"zzz"}); await sleep(400);
  log("new session id => queue spoken again", spoken.length>n && spoken[spoken.length-1]==="New session greeting");
  // unsupported browser
  const dom2 = new JSDOM(html,{runScripts:"dangerously",url:"http://localhost/",beforeParse(w2){ w2.postMessage=(m)=>sent.push(m); w2.speechSynthesis={speak(){},cancel(){},getVoices(){return[]}}; }});
  dom2.window.document.getElementById("toggle").click();
  log("unsupported browser reports it", sent.some(m=>m.value&&m.value.type==="unsupported"));
  process.exit(0);
})();
