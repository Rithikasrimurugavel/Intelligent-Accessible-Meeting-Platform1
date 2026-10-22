const {JSDOM, VirtualConsole} = require("jsdom"); const fs = require("fs");
const vc = new VirtualConsole();
const html = fs.readFileSync(__dirname + "/../components/video_meeting/frontend/index.html", "utf8");
const sent = [];
const dom = new JSDOM(html, {runScripts: "dangerously", pretendToBeVisual: true, url: "http://localhost/", virtualConsole: vc,
  beforeParse(w) { w.parent.postMessage = (m) => sent.push(m); w.HTMLCanvasElement.prototype.getContext = () => null; }});
const w = dom.window, T = w.__sign_test;
const render = a => w.dispatchEvent(new w.MessageEvent("message", {data: {type: "streamlit:render", args: a}}));
const values = () => sent.filter(m => m.type === "streamlit:setComponentValue").map(m => m.value);

// Synthetic hand: ext = [thumb, index, middle, ring, pinky]; thumb: "up" | "down" | "side"
function hand(cx, cy, ext, thumb = "side") {
  const lm = Array.from({length: 21}, () => ({x: cx, y: cy}));
  lm[0] = {x: cx, y: cy}; const mcpX = [0, -0.03, 0, 0.03, 0.06];
  [[5, 6, 8, 1], [9, 10, 12, 2], [13, 14, 16, 3], [17, 18, 20, 4]].forEach(([m, p, t, i]) => {
    const x = cx + mcpX[i];
    lm[m] = {x, y: cy - 0.1}; lm[p] = {x, y: cy - 0.17}; lm[t] = {x, y: ext[i] ? cy - 0.26 : cy - 0.1};
  });
  lm[9] = {x: cx, y: cy - 0.1}; lm[17] = {x: cx + 0.06, y: cy - 0.07};
  lm[2] = {x: cx - 0.05, y: cy - 0.02};
  if (ext[0]) {
    if (thumb === "up") { lm[3] = {x: cx - 0.08, y: cy - 0.08}; lm[4] = {x: cx - 0.08, y: cy - 0.16}; }
    else if (thumb === "down") { lm[3] = {x: cx - 0.08, y: cy + 0.04}; lm[4] = {x: cx - 0.08, y: cy + 0.12}; }
    else { lm[3] = {x: cx - 0.09, y: cy - 0.04}; lm[4] = {x: cx - 0.15, y: cy - 0.06}; }
  } else { lm[3] = {x: cx - 0.04, y: cy - 0.05}; lm[4] = {x: cx - 0.01, y: cy - 0.06}; }
  return lm;
}
// Build ~30 fps frames lasting `secs`, with a motion function giving the hand centre
function clip(ext, thumb, secs, motion, t0 = 0) {
  const out = []; for (let t = 0; t <= secs; t += 1 / 30) { const [dx, dy] = motion(t); out.push(T.buildFrame([hand(0.5 + dx, 0.6 + dy, ext, thumb)], t0 + t)); } return out;
}
const still = () => [0, 0];
const wave = t => [0.2 * Math.sin(t * 2 * Math.PI * 2.5), 0];
const nod = t => [0, 0.15 * Math.sin(t * 2 * Math.PI * 2)];
const circle = t => [0.15 * Math.cos(t * 2 * Math.PI * 1.2), 0.15 * Math.sin(t * 2 * Math.PI * 1.2)];
const down = t => [0, 0.3 * t];
const OPEN = [1, 1, 1, 1, 1], FIST = [0, 0, 0, 0, 0], POINT = [0, 1, 0, 0, 0];

let fails = 0;
const log = (k, ok) => { if (!ok) fails++; console.log((ok ? "PASS" : "FAIL") + "  " + k); };
const word = f => { const r = T.analyze(f); return r && r.word; };

render({sentence_pause: 3});
log("componentReady sent", sent.some(m => m.type === "streamlit:componentReady"));
log("camera NOT started automatically (privacy)", values().length === 0);
log("no frame capture / image upload path in the component", !/toDataURL/.test(html));

log("HELLO  (open hand waving)", word(clip(OPEN, "side", 1.4, wave)) === "HELLO");
log("STOP   (open hand held still)", word(clip(OPEN, "side", 1.2, still)) === "STOP");
log("PLEASE (open hand circling)", word(clip(OPEN, "side", 1.6, circle)) === "PLEASE");
log("THANK YOU (open hand sweeping down)", word(clip(OPEN, "side", 1.2, down)) === "THANK YOU");
log("YES    (fist nodding)", word(clip(FIST, "side", 1.4, nod)) === "YES");
log("NO     (index wagging)", word(clip(POINT, "side", 1.4, wave)) === "NO");
log("YOU    (index still)", word(clip(POINT, "side", 1.2, still)) === "YOU");
log("GOOD   (thumb up still)", word(clip([1, 0, 0, 0, 0], "up", 1.2, still)) === "GOOD");
log("BAD    (thumb down still)", word(clip([1, 0, 0, 0, 0], "down", 1.2, still)) === "BAD");
log("I LOVE YOU (thumb+index+pinky)", word(clip([1, 1, 0, 0, 1], "side", 1.2, still)) === "I LOVE YOU");
log("WATER  (three fingers still)", word(clip([0, 1, 1, 1, 0], "side", 1.2, still)) === "WATER");
log("a fist held still is NOT a word (no false positives)", word(clip(FIST, "side", 1.4, still)) === null);
log("too-short movement is ignored", word(clip(OPEN, "side", 0.3, wave)) === null);

// taught word: record a "sample", then it must match a fresh repeat and NOT a different sign
const sample = T.featureSeq(clip(OPEN, "side", 1.4, wave));
T.setTemplates({meeting: [sample]});
const rep = clip(OPEN, "side", 1.4, t => [0.2 * Math.sin(t * 2 * Math.PI * 2.5 + 0.1), 0], 10);
const m1 = T.matchCustom(rep, {meeting: [sample]}, 0.30, rep[rep.length - 1].t);
log("taught word is matched on a repeat of the same sign", m1 && m1.word === "MEETING");
const other = clip(POINT, "side", 1.4, still, 20);
log("taught word is NOT matched for a different sign", T.matchCustom(other, {meeting: [sample]}, 0.30, other[other.length - 1].t) === null);

// live stream -> words -> sentence, end to end through onResult (real-time path)
T.setTemplates({});
function feed(fr) { fr.forEach(f => T.onResult([f.hand ? hand(f.hand.cx, f.hand.cy, f.hand.ext.map(Boolean), "side") : null].filter(Boolean), f.t)); }
function feedAt(ext, thumb, secs, motion, t0) { for (let t = 0; t <= secs; t += 1 / 30) { const [dx, dy] = motion(t); T.onResult([hand(0.5 + dx, 0.6 + dy, ext, thumb)], t0 + t); } }
function feedNone(secs, t0) { for (let t = 0; t <= secs; t += 1 / 30) T.onResult([], t0 + t); }
feedNone(0.5, 100);
feedAt(OPEN, "side", 1.6, wave, 100.5);          // HELLO
feedNone(0.6, 102.2);
feedAt(POINT, "side", 1.6, still, 102.8);        // YOU
const before = T.state().words.slice();
log("words appear live while the camera runs (before any sentence is sent)", before.join(",") === "HELLO,YOU" && !values().some(b => b.events.some(e => e.t === "sign")));
feedNone(3.4, 104.5);
const signs = values().flatMap(b => b.events).filter(e => e.t === "sign");
log("hands down ~3 s => whole sentence sent once", signs.length === 1 && signs[0].words.join(" ") === "HELLO YOU");
log("sentence buffer is cleared after sending", T.state().words.length === 0);
process.exit(fails ? 1 : 0);
