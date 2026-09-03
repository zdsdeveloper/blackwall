// Unit tests for Model.js, the plugin's pure logic.
//
// Run:  node tests/model.test.js
//
// Model.js is a QML JavaScript library, so it opens with `.pragma library` --
// not valid JavaScript anywhere else. The harness strips that one directive and
// evaluates the rest in a VM context, which is enough to reach every function
// in it without Qt, a compositor, or a running shell.
//
// This exists because the alternative was nothing. Qt Quick Test needs
// `qmltestrunner`, which is not installed here, and a TestCase run under `qml6`
// silently executes no assertions at all -- a deliberately failing test exits 0.
// The declarative half of the QML (layout, colour, the countdown) still rests on
// somebody looking at it. The logic does not have to.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const source = fs
  .readFileSync(path.join(__dirname, "..", "Model.js"), "utf8")
  .replace(/^\s*\.pragma\s+\w+\s*$/gm, "");

const Model = {};
vm.createContext(Model);
vm.runInContext(source, Model);

let failures = 0;
let checks = 0;

function check(name, got, want) {
  checks++;
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  if (g !== w) {
    console.error(`FAIL  ${name}\n        got  ${g}\n        want ${w}`);
    failures++;
  }
}

// ---------------------------------------------------------------- the phrase
//
// The one piece of logic behind the breach challenge. Getting it wrong in the
// permissive direction means the challenge can be answered without answering
// it; in the strict direction it means a challenge that cannot be dismissed by
// the person it is asking.

check("phrase: exact", Model.phraseMatches("I chose this wall", "I chose this wall"), true);
check("phrase: case is forgiven", Model.phraseMatches("i CHOSE this WALL", "I chose this wall"), true);
check("phrase: surrounding space is forgiven", Model.phraseMatches("  I chose this wall \n", "I chose this wall"), true);
check("phrase: interior spacing is not collapsed", Model.phraseMatches("I  chose this wall", "I chose this wall"), false);
check("phrase: wrong words", Model.phraseMatches("let me through", "I chose this wall"), false);
check("phrase: empty answer", Model.phraseMatches("", "I chose this wall"), false);
// An expectation that never loaded must never be satisfiable, or a config that
// failed to read would open the challenge to the empty string.
check("phrase: empty expectation is unanswerable", Model.phraseMatches("", ""), false);
check("phrase: empty expectation rejects anything", Model.phraseMatches("whatever", ""), false);
check("phrase: null is not a crash", Model.phraseMatches(null, "I chose this wall"), false);
check("phrase: undefined is not a crash", Model.phraseMatches(undefined, undefined), false);

// ----------------------------------------------------------------- the state
//
// parseState decides whether a lock survives a reboot. A wrong answer here
// either resurrects a lock that should have died or drops one that should have
// held -- and the second is the one that matters.

check("state: empty is no lock", Model.parseState(""), { deadline: 0, bootId: "" });
check("state: null is no lock", Model.parseState(null), { deadline: 0, bootId: "" });
check("state: json form", Model.parseState('{"version":1,"deadline":1234,"bootId":"abc"}'), { deadline: 1234, bootId: "abc" });
// Files written before the boot id existed are a bare number. They must still
// parse, with an empty bootId, which reads as "boot unknown".
check("state: legacy bare number", Model.parseState("1234"), { deadline: 1234, bootId: "" });
check("state: malformed json falls back", Model.parseState("{not json"), { deadline: 0, bootId: "" });
check("state: negative deadline is no lock", Model.parseState('{"deadline":-5}'), { deadline: 0, bootId: "" });
check("state: non-numeric deadline is no lock", Model.parseState('{"deadline":"soon"}'), { deadline: 0, bootId: "" });
check("state: a json array is not a state file", Model.parseState("[1,2,3]"), { deadline: 0, bootId: "" });
check("state: missing bootId reads as unknown", Model.parseState('{"deadline":99}'), { deadline: 99, bootId: "" });

// ---------------------------------------------------------------- the config

const DEFAULT = Model.DEFAULT_CHALLENGE_PHRASE;
check("config: empty gives defaults", Model.parseConfig(""), { persistAcrossReboot: true, soundPath: "", challengePhrase: DEFAULT });
check("config: malformed gives defaults", Model.parseConfig("{oh no"), { persistAcrossReboot: true, soundPath: "", challengePhrase: DEFAULT });
check("config: a json array gives defaults", Model.parseConfig("[]"), { persistAcrossReboot: true, soundPath: "", challengePhrase: DEFAULT });
check("config: persist can be turned off", Model.parseConfig('{"persistAcrossReboot":false}').persistAcrossReboot, false);
// Anything that is not literally false persists, because persisting is the
// behaviour the plugin shipped with and the safer default.
check("config: absent persist stays on", Model.parseConfig("{}").persistAcrossReboot, true);
check("config: a custom phrase wins", Model.parseConfig('{"challengePhrase":"bismillah"}').challengePhrase, "bismillah");
check("config: a blank phrase falls back", Model.parseConfig('{"challengePhrase":"   "}').challengePhrase, DEFAULT);
check("config: sound path is carried", Model.parseConfig('{"soundPath":"/tmp/a.mp3"}').soundPath, "/tmp/a.mp3");

// ------------------------------------------------------------- the countdown

check("clock: zero", Model.formatRemaining(0), "00:00");
// Rounded up, so a freshly engaged 5:00 lock reads 05:00 rather than 04:59.
check("clock: rounds up", Model.formatRemaining(299001), "05:00");
check("clock: minutes and seconds", Model.formatRemaining(65000), "01:05");
check("clock: hours appear only when needed", Model.formatRemaining(3661000), "1:01:01");
check("clock: negative reads as zero", Model.formatRemaining(-5000), "00:00");

check("duration: minutes", Model.formatDuration(45), "45 min");
check("duration: an exact hour", Model.formatDuration(60), "1 hour");
check("duration: hours and minutes", Model.formatDuration(90), "1 hour 30 min");
check("duration: plural hours", Model.formatDuration(120), "2 hours");
check("duration: nonsense", Model.formatDuration(-1), "0 min");

// ------------------------------------------------------------------ clamping

check("clamp: inside", Model.clamp(5, 0, 10), 5);
check("clamp: below", Model.clamp(-1, 0, 10), 0);
check("clamp: above", Model.clamp(99, 0, 10), 10);
check("clamp: NaN takes the floor", Model.clamp(NaN, 3, 10), 3);

// A lock is never shorter than the minimum or longer than the maximum, however
// it was asked for -- the custom field on the bar menu reaches this directly.
check("span: a minute", Model.secondsForMinutes(1), 60);
check("span: under the floor is raised", Model.secondsForMinutes(0.1), 30);
check("span: over the ceiling is capped", Model.secondsForMinutes(99999), 12 * 3600);

// --------------------------------------------------------- the release curves
//
// Every phase of the reconnection sequence is a pure function of one 0..1
// progress value, which is what keeps the visuals, the audio fade and the
// shatter from drifting apart.

check("release: idle before it starts", Model.releasePhase(0), "idle");
check("release: opens on breach", Model.releasePhase(0.01), "breach");
check("release: press", Model.releasePhase(0.4), "press");
check("release: surge", Model.releasePhase(0.8), "surge");
check("release: shatter", Model.releasePhase(0.95), "shatter");
check("release: the end is shatter", Model.releasePhase(1), "shatter");

check("span: clamped low", Model.phaseSpan(0.0, 0.5, 1), 0);
check("span: clamped high", Model.phaseSpan(1.0, 0.5, 1), 1);
check("span: midpoint", Model.phaseSpan(0.75, 0.5, 1), 0.5);
// Callers write phaseSpan(p, X, Y) without guarding, so a degenerate span has
// to answer rather than divide by zero.
check("span: degenerate", Model.phaseSpan(0.5, 1, 1), 0);

// ---------------------------------------------------------------- the ripple

// Every slice samples one shared wave, which is what makes the wall read as a
// single surface flexing rather than N independent bands.
check("ripple: a single slice is stable", Model.waveAt(0, 1, 0, 1.6), Math.sin(0));
check("ripple: intensity stays in range", Model.intensityAt(3, 12, 1.2, 1) <= 1, true);
check("ripple: intensity never goes negative", Model.intensityAt(3, 12, 4.7, 0) >= 0, true);
check("ripple: no amplitude, no offset", Model.offsetAt(2, 8, 1.0, 0, 1), 0);

// -----------------------------------------------------------------------------

if (failures > 0) {
  console.error(`\n${failures} of ${checks} checks failed`);
  process.exit(1);
}
console.log(`${checks} checks passed`);
