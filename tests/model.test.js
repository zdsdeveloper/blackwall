// Unit tests for Model.js, the plugin's pure logic.
//
// Run:  node tests/model.test.js
//
// Model.js is a QML JavaScript library, so it opens with `.pragma library` --
// not valid JavaScript anywhere else. The harness strips that one directive and
// evaluates the rest in a VM context, which is enough to reach every function
// in it without Qt, a compositor, or a running shell.
//
// This exists because the alternative was nothing without a compositor. It is
// no longer the whole suite: the QML half runs under `qmltestrunner` (see
// tests/run-qml-tests.sh), which does live here after all -- in the Qt bindir
// rather than on PATH, which is why this file once claimed it was not
// installed. What still rests on somebody looking at it is the part neither
// runner can judge: layout, colour, and whether the thing reads.

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
check("config: empty gives defaults", Model.parseConfig(""), { persistAcrossReboot: true, soundPath: "", soundEnabled: true, challengePhrase: DEFAULT, agents: {}, schedule: { enabled: false, warnSeconds: 120, maxLockMinutes: 30, gapSeconds: 45, windows: [] }, activity: { enabled: false, enforced: true, breakAfterMinutes: 180, idleResetMinutes: 15, snoozeMinutes: 15, demandGraceSeconds: 90 } });
check("config: malformed gives defaults", Model.parseConfig("{oh no"), { persistAcrossReboot: true, soundPath: "", soundEnabled: true, challengePhrase: DEFAULT, agents: {}, schedule: { enabled: false, warnSeconds: 120, maxLockMinutes: 30, gapSeconds: 45, windows: [] }, activity: { enabled: false, enforced: true, breakAfterMinutes: 180, idleResetMinutes: 15, snoozeMinutes: 15, demandGraceSeconds: 90 } });
check("config: a json array gives defaults", Model.parseConfig("[]"), { persistAcrossReboot: true, soundPath: "", soundEnabled: true, challengePhrase: DEFAULT, agents: {}, schedule: { enabled: false, warnSeconds: 120, maxLockMinutes: 30, gapSeconds: 45, windows: [] }, activity: { enabled: false, enforced: true, breakAfterMinutes: 180, idleResetMinutes: 15, snoozeMinutes: 15, demandGraceSeconds: 90 } });
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

// ----------------------------------------------------------- the station tail

// The detail column has to carry what the entry is actually about, or the tail
// is a list of nouns with no subjects.
const AT = new Date(2026, 0, 2, 3, 4, 5).getTime() / 1000;
check("tail: an add names the domain", Model.stationLogLine({ kind: "added", at: AT, domain: "x.com" }), "03:04:05  added      x.com");
check("tail: a breach names the reason", Model.stationLogLine({ kind: "breach", at: AT, reasons: ["unit: masked"], targets: ["hosts"] }), "03:04:05  breach     unit: masked");
check("tail: a drift names the file", Model.stationLogLine({ kind: "drift", at: AT, targets: ["hosts", "zen_policy"] }), "03:04:05  drift      hosts, zen_policy");
check("tail: a bare kind stands alone", Model.stationLogLine({ kind: "ack", at: AT }), "03:04:05  ack      ");
check("tail: a missing timestamp does not crash", Model.stationLogLine({ kind: "ack" }), "--:--:--  ack      ");
check("tail: a non-entry is empty, not a crash", Model.stationLogLine(null), "");
check("tail: a string is not an entry", Model.stationLogLine("breach"), "");

// ---------------------------------------------------------------- the ripple

// Every slice samples one shared wave, which is what makes the wall read as a
// single surface flexing rather than N independent bands.
check("ripple: a single slice is stable", Model.waveAt(0, 1, 0, 1.6), Math.sin(0));
check("ripple: intensity stays in range", Model.intensityAt(3, 12, 1.2, 1) <= 1, true);
check("ripple: intensity never goes negative", Model.intensityAt(3, 12, 4.7, 0) >= 0, true);
check("ripple: no amplitude, no offset", Model.offsetAt(2, 8, 1.0, 0, 1), 0);

// ------------------------------------------------------------- the redaction
//
// The station hides the contained list until it is asked to show it. That is
// only worth anything if the console hides the same names, since every add
// puts one there in plain text.

const P = Model.stationLogParts;
check("parts: an add splits into three", P({ kind: "added", at: AT, domain: "x.com" }),
      { stamp: "03:04:05", kind: "added", detail: "x.com" });
check("parts: a breach puts the reason in detail", P({ kind: "breach", at: AT, reasons: ["unit: masked"] }).detail, "unit: masked");
check("parts: targets fall back into detail", P({ kind: "drift", at: AT, targets: ["hosts", "zen_policy"] }).detail, "hosts, zen_policy");
check("parts: a bare kind has no detail", P({ kind: "ack", at: AT }).detail, "");
check("parts: a non-entry is empty, not a crash", P(null), { stamp: "", kind: "", detail: "" });
// stationLogLine is now built from the parts; it must not have changed.
check("parts: the line is still assembled the same way",
      Model.stationLogLine({ kind: "added", at: AT, domain: "x.com" }),
      "03:04:05  added      x.com");

check("redact: nothing stays nothing", Model.redact(""), "");
check("redact: null is not a crash", Model.redact(null), "");
check("redact: undefined is not a crash", Model.redact(undefined), "");
// Quantised, not exact: a block run the same width as the word tells a reader
// how long it was, and against a list of known sites that is most of the way
// to telling them which one.
check("redact: length is quantised up to a multiple of four", Model.redact("abcde").length, 8);
check("redact: a short word still gets a floor", Model.redact("a").length, 4);
check("redact: long details are capped", Model.redact("x".repeat(400)).length, 40);
check("redact: it is blocks", /^█+$/.test(Model.redact("hello")), true);
// The load-bearing property: nothing of the original survives.
check("redact: the original never appears in the output",
      Model.redact("xvideos.com").indexOf("x"), -1);

check("censor: off by default, so old callers are unchanged",
      Model.stationLogLine({ kind: "added", at: AT, domain: "x.com" }),
      "03:04:05  added      x.com");
check("censor: on hides the domain but keeps the time and the kind",
      Model.stationLogLine({ kind: "added", at: AT, domain: "xvideos.com" }, true),
      "03:04:05  added      \u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588");
check("censor: a breach reason is a detail too, and reasons name domains",
      Model.stationLogLine({ kind: "breach", at: AT, reasons: ["0.0.0.0 xnxx.com missing"] }, true)
        .indexOf("xnxx"), -1);
check("censor: a line with no detail is unchanged by it",
      Model.stationLogLine({ kind: "ack", at: AT }, true), "03:04:05  ack      ");

// --------------------------------------------------------------- the agent
//
// Recognition, not authentication. Nothing is gated on any of this -- the
// tests below are about the station greeting the right person, not about
// keeping the wrong one out, and no test here should ever be read as the
// second thing.

const DEVICES = [
  'I: Bus=0003 Vendor=046d Product=405e Version=0111',
  'N: Name="Logitech M720 Triathlon"',
  'U: Uniq=18-c3-2d-77',
  'H: Handlers=sysrq kbd leds event5 mouse1 ',
  '',
  'I: Bus=0018 Vendor=06cb Product=ce17 Version=0100',
  'N: Name="SYNA32B5:00 06CB:CE17 Touchpad"',
  'H: Handlers=event11 mouse3 ',
  '',
  'I: Bus=0003 Vendor=1d6b Product=0002 Version=0206',
  'N: Name="Some Keyboard"',
  'H: Handlers=kbd event2 ',
  ''
].join('\n');

const pointers = Model.parsePointers(DEVICES);
check("pointers: only devices with a mouse handler", pointers.length, 2);
check("pointers: the mouse is identified by vendor:product", pointers[0].id, "046d:405e");
check("pointers: the name comes along", pointers[0].name, "Logitech M720 Triathlon");
check("pointers: the touchpad is a pointer too", pointers[1].id, "06cb:ce17");
// A keyboard has no mouse handler and must not be offered as a pointer.
check("pointers: a keyboard is not a pointer", pointers.map(p => p.id).indexOf("1d6b:0002"), -1);
check("pointers: nothing is not a crash", Model.parsePointers(""), []);
check("pointers: null is not a crash", Model.parsePointers(null), []);
check("pointers: garbage is not a crash", Model.parsePointers("!!! not a device list"), []);

check("agent: a configured mouse is recognised",
      Model.identifyAgent(pointers, { "046d:405e": "ZAMIL" }), "ZAMIL");
// Case in the config must not decide whether you are recognised.
check("agent: the id match is case-insensitive",
      Model.identifyAgent(pointers, { "046D:405E": "ZAMIL" }), "ZAMIL");
check("agent: an unconfigured mouse is nobody",
      Model.identifyAgent(pointers, { "1111:2222": "SOMEONE" }), "");
check("agent: no agents configured is nobody",
      Model.identifyAgent(pointers, {}), "");
check("agent: no pointers is nobody",
      Model.identifyAgent([], { "046d:405e": "ZAMIL" }), "");
check("agent: a non-object agent map is not a crash",
      Model.identifyAgent(pointers, null), "");
check("agent: it skips unconfigured devices to find a configured one",
      Model.identifyAgent(pointers, { "06cb:ce17": "TOUCHPAD" }), "TOUCHPAD");

check("config: agents default to none", Model.parseConfig("").agents, {});
check("config: agents are carried",
      Model.parseConfig('{"agents":{"046d:405e":"ZAMIL"}}').agents,
      { "046d:405e": "ZAMIL" });
// An array is an object in JavaScript, and indexing it by a USB id yields
// undefined -- which would read as "nobody" rather than as a broken config.
check("config: an agents array is treated as none",
      Model.parseConfig('{"agents":[1,2]}').agents, {});
check("config: a scalar agents field is treated as none",
      Model.parseConfig('{"agents":"zamil"}').agents, {});

// Uniq names the device; vendor:product only names the model, and every
// M720 on earth carries the same one.
check("pointers: a device address is carried when there is one",
      pointers[0].uniq, "18-c3-2d-77");
check("pointers: a device with no address reports an empty one",
      pointers[1].uniq, "");
check("agent: the device address is matched",
      Model.identifyAgent(pointers, { "18-c3-2d-77": "ZAMIL" }), "ZAMIL");
check("agent: the address match is case-insensitive",
      Model.identifyAgent(pointers, { "18-C3-2D-77": "ZAMIL" }), "ZAMIL");
// The address is the more specific of the two, so it decides.
check("agent: the address wins over the model id",
      Model.identifyAgent(pointers, { "18-c3-2d-77": "ZAMIL", "046d:405e": "ANYONE" }),
      "ZAMIL");
// The one that would really hurt: three devices here have no address, and an
// empty key must not sweep all of them in.
check("agent: an empty config key matches no addressless device",
      Model.identifyAgent(pointers, { "": "NOBODY" }), "");
check("agent: an addressless device still matches on its model id",
      Model.identifyAgent([{ id: "06cb:ce17", uniq: "", name: "Touchpad" }],
                          { "06cb:ce17": "TOUCHPAD" }), "TOUCHPAD");

// A device is free to advertise any string as its address, including the ones
// that name things on Object.prototype. None of them were ever configured.
check("agent: a device claiming __proto__ is nobody",
      Model.identifyAgent([{ id: "046d:405e", uniq: "__proto__", name: "hostile" }],
                          { "18-c3-2d-77": "ZAMIL" }), "");
check("agent: a device claiming constructor is nobody",
      Model.identifyAgent([{ id: "1111:2222", uniq: "constructor", name: "hostile" }],
                          { "18-c3-2d-77": "ZAMIL" }), "");
check("agent: a device claiming toString as its model id is nobody",
      Model.identifyAgent([{ id: "toString", uniq: "", name: "hostile" }], {}), "");
// And the real one still works alongside them.
check("agent: a hostile device does not shadow a configured one",
      Model.identifyAgent([{ id: "1111:2222", uniq: "__proto__", name: "hostile" },
                           { id: "046d:405e", uniq: "18-c3-2d-77", name: "M720" }],
                          { "18-c3-2d-77": "ZAMIL" }), "ZAMIL");

// The sound toggle. Off by choice, never off by accident.
check("sound: on by default", Model.parseConfig("").soundEnabled, true);
check("sound: can be turned off", Model.parseConfig('{"soundEnabled":false}').soundEnabled, false);
check("sound: absent leaves it on", Model.parseConfig('{"soundPath":"/x.mp3"}').soundEnabled, true);
// Anything that is not literally false leaves it on: a config that will not
// parse cleanly must not silently mute the wall.
check("sound: a junk value leaves it on", Model.parseConfig('{"soundEnabled":"no"}').soundEnabled, true);
check("sound: null leaves it on", Model.parseConfig('{"soundEnabled":null}').soundEnabled, true);
check("sound: malformed config leaves it on", Model.parseConfig("{oh no").soundEnabled, true);

// ------------------------------------------------------------- the schedule
//
// Windows the wall closes by itself. The awkward parts are all about time
// rather than about locking: a window that crosses midnight, one that only
// runs on some days, and one that started last week and is still open.

const SCHED = (w) => Model.parseSchedule({ enabled: true, windows: w }).windows;
// 2026-09-04 is a Friday.
const at = (day, h, m) => new Date(2026, 8, day, h, m);
// Null-safe on purpose. Reaching straight for `.label` throws on a null
// return, which crashes the whole file instead of failing one check -- so a
// regression reports as a stack trace with everything after it unrun, and the
// grep you wrote to read the results hides it. Ask for the label, get the
// label or null.
const labelAt = (w, d) => { const a = Model.activeWindowAt(w, d); return a ? a.label : null; };

check("time: a clock time becomes minutes", Model.minutesOfDay("23:30"), 1410);
check("time: midnight is zero", Model.minutesOfDay("00:00"), 0);
check("time: junk never matches", Model.minutesOfDay("nope"), -1);
check("time: an impossible hour never matches", Model.minutesOfDay("25:00"), -1);
check("time: an impossible minute never matches", Model.minutesOfDay("10:75"), -1);
check("time: empty never matches", Model.minutesOfDay(""), -1);

// --- shape ---
check("window: a wrapping window is marked as one",
      SCHED([{ start: "23:30", end: "06:00" }])[0].wraps, true);
check("window: a same-day window is not",
      SCHED([{ start: "09:00", end: "17:00" }])[0].wraps, false);
check("window: no days named means every day",
      SCHED([{ start: "09:00", end: "17:00" }])[0].days.length, 7);
check("window: days are matched loosely",
      SCHED([{ start: "09:00", end: "17:00", days: ["Monday", "WED"] }])[0].days, [1, 3]);
// A window of zero length is not a window.
check("window: start equal to end is dropped",
      SCHED([{ start: "09:00", end: "09:00" }]).length, 0);
check("window: an unparseable time is dropped",
      SCHED([{ start: "banana", end: "17:00" }]).length, 0);
check("window: a non-object is dropped", SCHED([null, 7, "x"]).length, 0);

// --- when it is on ---
const night = SCHED([{ label: "Bedtime", start: "23:30", end: "06:00" }]);
check("active: inside, before midnight", labelAt(night, at(4, 23, 40)), "Bedtime");
check("active: inside, after midnight", labelAt(night, at(5, 2, 0)), "Bedtime");
check("active: just before it opens", labelAt(night, at(4, 23, 29)), null);
check("active: exactly as it opens", labelAt(night, at(4, 23, 30)), "Bedtime");
// The close is exclusive, so a window ending at 06:00 is over at 06:00.
check("active: exactly as it closes", labelAt(night, at(5, 6, 0)), null);
check("active: well outside", labelAt(night, at(5, 12, 0)), null);
check("active: how long is left", Model.activeWindowAt(night, at(5, 5, 30)).endsInMinutes, 30);

// --- the one that is easy to get wrong ---
// `days` names the day a window STARTS. A Friday bedtime runs into Saturday
// morning; it is not a Saturday window, and Saturday night is not one either.
const friOnly = SCHED([{ label: "Fri", start: "23:30", end: "06:00", days: ["fri"] }]);
check("days: Friday night is on", labelAt(friOnly, at(4, 23, 45)), "Fri");
check("days: Saturday morning is still that window", labelAt(friOnly, at(5, 3, 0)), "Fri");
check("days: Saturday night is not", labelAt(friOnly, at(5, 23, 45)), null);
check("days: Thursday night is not", labelAt(friOnly, at(3, 23, 45)), null);

// A Saturday window running into Sunday crosses the end of the week, which is
// a different arithmetic path from every other day.
const satOnly = SCHED([{ label: "Sat", start: "23:30", end: "06:00", days: ["sat"] }]);
check("week: Saturday night is on", labelAt(satOnly, at(5, 23, 45)), "Sat");
check("week: Sunday morning wraps the week end", labelAt(satOnly, at(6, 2, 0)), "Sat");
check("week: Sunday night is not", labelAt(satOnly, at(6, 23, 45)), null);

// --- what is next ---
check("next: later today", Model.nextWindowAt(night, at(4, 22, 0)).inMinutes, 90);
check("next: while one is open, the next is tomorrow's",
      Model.nextWindowAt(night, at(5, 2, 0)).inMinutes, 1290);
check("next: a weekly window wraps round to next week",
      Model.nextWindowAt(friOnly, at(5, 12, 0)).inMinutes, 6 * 1440 + 690);
check("next: nothing scheduled is nothing next", Model.nextWindowAt([], at(4, 12, 0)), null);

// --- the settings around it ---
check("schedule: off by default", Model.parseSchedule({}).enabled, false);
check("schedule: junk is off", Model.parseSchedule(null).enabled, false);
check("schedule: warning defaults to two minutes", Model.parseSchedule({}).warnSeconds, 120);
// No warning is a lock out of nowhere; an hour of warning is not a warning.
check("schedule: warning is clamped low", Model.parseSchedule({ warnSeconds: -50 }).warnSeconds, 0);
check("schedule: warning is clamped high", Model.parseSchedule({ warnSeconds: 99999 }).warnSeconds, 900);

check("config: a schedule is carried through",
      Model.parseConfig('{"schedule":{"enabled":true,"windows":[{"start":"23:30","end":"06:00"}]}}').schedule.windows.length, 1);
check("config: no schedule is a disabled one",
      Model.parseConfig("{}").schedule.enabled, false);
// The same failure that nearly ate `agents`: a key the parser knows and the
// writer does not is a key that gets deleted on the next save.
check("config: a junk schedule does not throw",
      Model.parseConfig('{"schedule":42}').schedule.windows.length, 0);

// --- the safety valve ---
//
// A scheduled lock used to run for whatever was left of its window, so a
// window entered wrong cost exactly that: a mistyped bedtime took this machine
// for 226 minutes in one tick. Locks are taken in capped stretches with a gap
// between them, so a mistake costs one stretch and then hands you a moment.

check("cap: defaults to half an hour", Model.parseSchedule({}).maxLockMinutes, 30);
check("cap: a gap by default", Model.parseSchedule({}).gapSeconds, 45);
check("cap: can be raised", Model.parseSchedule({ maxLockMinutes: 90 }).maxLockMinutes, 90);
check("cap: cannot be zero", Model.parseSchedule({ maxLockMinutes: 0 }).maxLockMinutes, 1);
check("cap: cannot exceed twelve hours", Model.parseSchedule({ maxLockMinutes: 99999 }).maxLockMinutes, 720);
// A gap of zero would be continuous lockout with extra steps.
check("cap: the gap has a floor", Model.parseSchedule({ gapSeconds: 0 }).gapSeconds, 5);
check("cap: the gap has a ceiling", Model.parseSchedule({ gapSeconds: 99999 }).gapSeconds, 600);
check("cap: junk falls back", Model.parseSchedule({ maxLockMinutes: "lots" }).maxLockMinutes, 30);

check("stretch: a short window is taken whole", Model.scheduledStretch(12, 30), 12);
check("stretch: a long window is capped", Model.scheduledStretch(226, 30), 30);
check("stretch: exactly the cap", Model.scheduledStretch(30, 30), 30);
check("stretch: under a minute is not worth a lock", Model.scheduledStretch(0, 30), 0);
check("stretch: a negative is not a lock", Model.scheduledStretch(-5, 30), 0);
check("stretch: junk is not a lock", Model.scheduledStretch("soon", 30), 0);
// The 226 minutes that started this, under the default cap.
check("stretch: the bedtime that caused this now costs 30, not 226",
      Model.scheduledStretch(226, Model.parseSchedule({}).maxLockMinutes), 30);

// ------------------------------------------------- the scheduler's decision
//
// The most consequential thing this plugin does without being asked. While it
// lived inside a Timer handler it could not be tested, which is how a window
// entered wrong came to take the machine for 226 minutes in one tick.

const SCH = (o) => Model.parseSchedule(Object.assign({ enabled: true }, o));
const decide = (sch, now, holding, gap) =>
  Model.scheduleDecision(sch, sch.windows, now, holding, gap === undefined ? 0 : gap);

// Thursday 23:30 -> Friday 06:00. `at(4,...)` is Friday.
const thu = SCH({ windows: [{ label: "Bedtime", start: "23:30", end: "06:00", days: ["thu"] }] });

check("decide: the incident locks, but only for the cap",
      decide(thu, at(4, 2, 0), false).minutes, 30);
check("decide: and it is the right window", decide(thu, at(4, 2, 0), false).label, "Bedtime");
// 240 minutes were left. The cap is what stands between a mistyped window and
// an evening.
check("decide: it does not take the whole remainder",
      decide(thu, at(4, 2, 0), false).minutes < 240, true);
check("decide: nothing while already behind the wall",
      decide(thu, at(4, 2, 0), true).action, "none");
check("decide: nothing inside the gap",
      decide(thu, at(4, 2, 0), false, at(4, 2, 0).getTime() + 60000).action, "none");
check("decide: the gap is the stretch plus the configured daylight",
      decide(thu, at(4, 2, 0), false).gapUntilMs
        - at(4, 2, 0).getTime(), 30 * 60000 + 45 * 1000);

// --- refusing to act ---
check("decide: a disabled schedule does nothing",
      Model.scheduleDecision(Model.parseSchedule({ windows: [] }), thu.windows, at(4, 2, 0), false, 0).action, "none");
check("decide: no windows, nothing to do", decide(SCH({ windows: [] }), at(4, 2, 0), false).action, "none");
// Realm-safe: `instanceof Date` answers false for a Date from another JS
// context, and this file is a QML library evaluated in its own scope. A guard
// that got this wrong would decline to act for ever, silently.
check("decide: junk instead of a date does nothing", decide(thu, "tuesday", false).action, "none");
check("decide: an invalid date does nothing", decide(thu, new Date("nonsense"), false).action, "none");
check("decide: null does nothing", decide(thu, null, false).action, "none");

// --- short windows ---
const brief = SCH({ windows: [{ label: "Brief", start: "10:00", end: "10:05" }] });
check("decide: a short window is taken whole", decide(brief, at(4, 10, 1), false).minutes, 4);
// The scheduler works to the minute -- weekMinutes drops seconds -- so the
// last whole minute is still taken, and the lock can outlive its window by
// under a minute. That is within engage's own 30s floor and not worth chasing;
// what matters is that it stops at the boundary rather than running on.
check("decide: the last whole minute is still taken",
      decide(brief, at(4, 10, 4), false).minutes, 1);
check("decide: nothing once the window has closed",
      decide(brief, at(4, 10, 5), false).action, "none");

// --- warning ---
const soon = SCH({ windows: [{ label: "Soon", start: "10:00", end: "11:00" }], warnSeconds: 120 });
check("decide: warns just before it opens", decide(soon, at(4, 9, 59), false).action, "warn");
check("decide: the warning names the window", decide(soon, at(4, 9, 59), false).label, "Soon");
check("decide: no warning when it is still far off", decide(soon, at(4, 9, 30), false).action, "none");
check("decide: no warning while already locked", decide(soon, at(4, 9, 59), true).action, "none");
// Once it is open, locking is the answer rather than warning about it.
check("decide: an open window locks rather than warns", decide(soon, at(4, 10, 30), false).action, "lock");

// ------------------------------------------- the config round trip, checked
//
// Three times now a key has existed in parseConfig and not in the writer, and
// each time the next save of any unrelated setting silently deleted it:
// `soundPath` was the first, `agents` the second (which would have erased the
// operator's own agent the moment they flipped a toggle), and an empty
// schedule literal the third. A comment above writeConfig warns about exactly
// this and did not prevent any of them.
//
// So the writer is read from disk and checked against the parser. This is the
// only test here that reaches outside Model.js, and it earns that.

const serviceSrc = fs.readFileSync(path.join(__dirname, "..", "Service.qml"), "utf8");
const writeBlock = (() => {
  const start = serviceSrc.indexOf("configFile.write(JSON.stringify({");
  if (start < 0) return null;
  // To the closing of the stringify call.
  const end = serviceSrc.indexOf("}, null, 2)", start);
  return end < 0 ? null : serviceSrc.slice(start, end);
})();

check("round trip: the writer was found in Service.qml", writeBlock !== null, true);

if (writeBlock) {
  // Top-level keys the writer emits.
  const written = new Set(
    [...writeBlock.matchAll(/^\s{6}([A-Za-z_][A-Za-z0-9_]*)\s*:/gm)].map(m => m[1]));
  const parsed = Object.keys(Model.parseConfig("{}"));
  const missing = parsed.filter(k => !written.has(k));
  check("round trip: every key the parser produces is also written",
        missing, []);
}

// ------------------------------------------------------ the activity clock
//
// Suggests a break; never takes one. Nothing here can engage the wall, and the
// tests below are as much about it staying quiet as about it speaking up -- a
// reminder that nags is a reminder that gets switched off.

const ACT = (o) => Model.parseActivity(Object.assign({ enabled: true }, o));
const MIN = 60000;
// Run the clock for n minutes, a minute at a time, as the real tick does.
function runFor(cfg, state, minutes, idle) {
  for (let i = 0; i < minutes; i++) state = Model.activityTick(cfg, state, idle, MIN);
  return state;
}
const fresh = { activeMs: 0, idleMs: 0 };

check("activity: off unless asked for", Model.parseActivity({}).enabled, false);
check("activity: enforced unless told otherwise", Model.parseActivity({}).enforced, true);
check("activity: three hours by default", Model.parseActivity({}).breakAfterMinutes, 180);
check("activity: fifteen minutes away is the break", Model.parseActivity({}).idleResetMinutes, 15);
check("activity: cannot be set to interrupt constantly", ACT({ breakAfterMinutes: 1 }).breakAfterMinutes, 30);
check("activity: nor to never fire", ACT({ breakAfterMinutes: 99999 }).breakAfterMinutes, 480);
check("activity: junk falls back", ACT({ breakAfterMinutes: "soon" }).breakAfterMinutes, 180);
check("activity: suggesting must be asked for explicitly", ACT({ enforced: false }).enforced, false);
// Ignoring the window must not be a way out of it, so the grace is bounded.
check("activity: the grace has a floor", ACT({ demandGraceSeconds: 0 }).demandGraceSeconds, 15);
check("activity: and a ceiling", ACT({ demandGraceSeconds: 99999 }).demandGraceSeconds, 600);

check("breaks: the shortest is offered first", Model.BREAK_CHOICES[0], 15);
check("breaks: a choice becomes seconds the wall accepts", Model.breakSeconds(20), 1200);
check("breaks: junk becomes the shortest", Model.breakSeconds("ages"), 900);

const cfg = ACT({ breakAfterMinutes: 180, idleResetMinutes: 15 });
check("clock: time at the keyboard accumulates", runFor(cfg, fresh, 30, false).activeMs, 30 * MIN);
check("clock: being away does not count as working", runFor(cfg, fresh, 30, true).activeMs, 0);
// Making tea is not a break; walking away is.
check("clock: a five minute pause does not reset a long stretch",
      runFor(cfg, runFor(cfg, fresh, 120, false), 5, true).activeMs, 120 * MIN);
check("clock: fifteen minutes away is the break",
      runFor(cfg, runFor(cfg, fresh, 120, false), 15, true).activeMs, 0);
check("clock: coming back starts the idle stretch over",
      runFor(cfg, runFor(cfg, fresh, 40, false), 1, false).idleMs, 0);
check("clock: a jump forward is not work",
      Model.activityTick(cfg, { activeMs: 30 * MIN, idleMs: 0 }, false, 3 * 3600000).activeMs, 0);
check("clock: a negative delta is ignored",
      Model.activityTick(cfg, { activeMs: 5 * MIN, idleMs: 0 }, false, -9999).activeMs, 5 * MIN);
check("clock: junk state does not crash", Model.activityTick(cfg, null, false, MIN).activeMs, MIN);

const long = runFor(cfg, fresh, 180, false);
check("demand: after three hours", Model.activityDecision(cfg, long, 0, 1000).action, "demand");
check("demand: and says how long it has been", Model.activityDecision(cfg, long, 0, 1000).activeMinutes, 180);
check("demand: not before", Model.activityDecision(cfg, runFor(cfg, fresh, 179, false), 0, 1000).action, "none");
check("demand: never while disabled",
      Model.activityDecision(Model.parseActivity({ breakAfterMinutes: 180 }), long, 0, 1000).action, "none");
check("demand: not while they are already away",
      Model.activityDecision(cfg, { activeMs: 200 * MIN, idleMs: MIN }, 0, 1000).action, "none");
// The load-bearing one. Ignoring the window must not buy a quarter of an hour
// of not being asked, or ignoring it is the way out of it.
const justAsked = 10 * 3600000;
check("demand: ignoring it does not buy quiet",
      Model.activityDecision(cfg, long, justAsked, justAsked + MIN).action, "demand");

const soft = ACT({ breakAfterMinutes: 180, enforced: false });
check("suggest: only when enforcement is turned off", Model.activityDecision(soft, long, 0, 1000).action, "suggest");
check("suggest: and that one does snooze",
      Model.activityDecision(soft, long, justAsked, justAsked + MIN).action, "none");
check("suggest: speaking again once the snooze has passed",
      Model.activityDecision(soft, long, justAsked, justAsked + 16 * MIN).action, "suggest");

// ------------------------------------------------- what the station reads off it
//
// The station draws this thirty times a second off a state the service only
// advances every fifteen. Everything here is about that gap.

const READ = (over, state, lastTick, now, away) =>
  Model.activityReadout(ACT(Object.assign({ enabled: true, breakAfterMinutes: 180 }, over || {})),
                        state, lastTick, now, away);

const OFF = Model.parseActivity({ breakAfterMinutes: 180 });
check("readout: off when breaks are off",
      Model.activityReadout(OFF, { activeMs: MIN }, 0, 0, false).enabled, false);
check("readout: and reads zero rather than the banked count",
      Model.activityReadout(OFF, { activeMs: 90 * MIN }, 0, 0, false).activeMs, 0);

// The whole reason this function exists: between ticks it keeps counting.
check("readout: projects the seconds since the last tick",
      READ({}, { activeMs: 60 * MIN, idleMs: 0 }, 1000, 1000 + 9000).activeMs, 60 * MIN + 9000);
check("readout: with no tick yet it shows what is banked",
      READ({}, { activeMs: 60 * MIN, idleMs: 0 }, 0, 5000).activeMs, 60 * MIN);
check("readout: a clock that went backwards does not subtract",
      READ({}, { activeMs: 60 * MIN, idleMs: 0 }, 9000, 1000).activeMs, 60 * MIN);

// The same guard the tick applies. A machine that slept did not spend that
// time at the desk, and showing four banked hours after a suspend would be a
// lie in the direction that matters.
check("readout: a jump past a minute is a machine that slept",
      READ({}, { activeMs: 170 * MIN, idleMs: 0 }, 1000, 1000 + 3 * 3600000).activeMs, 0);
check("readout: and it is counted as time away",
      READ({}, { activeMs: 170 * MIN, idleMs: 0 }, 1000, 1000 + 3 * 3600000).idleMs, 3 * 3600000);

// Away holds the count where it is rather than advancing it.
check("readout: away does not add to the stretch",
      READ({}, { activeMs: 60 * MIN, idleMs: 0 }, 1000, 1000 + 9000, true).activeMs, 60 * MIN);
check("readout: away adds to the time away",
      READ({}, { activeMs: 60 * MIN, idleMs: 0 }, 1000, 1000 + 9000, true).idleMs, 9000);
check("readout: away long enough is the break, and the stretch is gone",
      READ({ idleResetMinutes: 15 }, { activeMs: 60 * MIN, idleMs: 14 * MIN }, 1000,
           1000 + 61000, true).activeMs, 0);
check("readout: and until then it says how much longer counts",
      READ({ idleResetMinutes: 15 }, { activeMs: 60 * MIN, idleMs: 10 * MIN }, 0, 0, true).resetInMs,
      5 * MIN);
check("readout: back at the desk clears the time away",
      READ({}, { activeMs: 60 * MIN, idleMs: 4 * MIN }, 1000, 1000 + 1000, false).idleMs, 0);

// The countdown itself.
check("readout: how long until the break is owed",
      READ({ breakAfterMinutes: 180 }, { activeMs: 170 * MIN, idleMs: 0 }, 0, 0).untilBreakMs, 10 * MIN);
check("readout: rounded up, so 9m01s left never reads as 9",
      READ({ breakAfterMinutes: 180 }, { activeMs: 170 * MIN + 59000, idleMs: 0 }, 0, 0).untilBreakMinutes, 10);
check("readout: the stretch as a fraction, for the bar",
      READ({ breakAfterMinutes: 180 }, { activeMs: 90 * MIN, idleMs: 0 }, 0, 0).fraction, 0.5);
check("readout: not due before the hour is up",
      READ({ breakAfterMinutes: 180 }, { activeMs: 179 * MIN, idleMs: 0 }, 0, 0).due, false);
check("readout: due on the minute it is owed",
      READ({ breakAfterMinutes: 180 }, { activeMs: 180 * MIN, idleMs: 0 }, 0, 0).due, true);
check("readout: past due, the countdown floors at zero rather than going negative",
      READ({ breakAfterMinutes: 180 }, { activeMs: 400 * MIN, idleMs: 0 }, 0, 0).untilBreakMs, 0);
check("readout: and the bar stays full rather than overflowing",
      READ({ breakAfterMinutes: 180 }, { activeMs: 400 * MIN, idleMs: 0 }, 0, 0).fraction, 1);

check("readout: junk state does not crash",
      READ({}, null, 0, 0).activeMs, 0);
check("readout: junk config is simply off",
      Model.activityReadout(null, { activeMs: 90 * MIN }, 0, 0, false).enabled, false);

// It agrees with the thing that acts on it. A station saying "due" while the
// service declines to demand would be the readout lying about the rule.
const dueState = { activeMs: 180 * MIN, idleMs: 0 };
check("readout: due agrees with the decision that acts",
      [READ({}, dueState, 0, 0).due,
       Model.activityDecision(ACT({ enabled: true, breakAfterMinutes: 180 }), dueState, 0, 1000).action],
      [true, "demand"]);

// ------------------------------------------------------- what counts as away
//
// The bug this closes: sitting still through a film. The compositor is asked
// whether an input device has been touched, and for two hours the answer was
// no -- so the stretch never grew and the fifteen minute reset kept firing.
// The one case the whole feature exists for was the one case it could not see.

check("away: idle with nothing playing is away", Model.awayNow(true, false), true);
check("away: idle with something playing is not", Model.awayNow(true, true), false);
check("away: touching things is never away", Model.awayNow(false, false), false);
check("away: nor is touching things while it plays", Model.awayNow(false, true), false);
check("away: an unknown answer is not treated as away",
      [Model.awayNow(undefined, undefined), Model.awayNow(null, null)], [false, false]);

// The load-bearing one, run through the clock rather than asserted on the
// rule. Two hours of film: no keyboard, no mouse, something playing the whole
// time. The stretch must be two hours, not zero.
{
  const film = ACT({ breakAfterMinutes: 180, idleResetMinutes: 15 });
  let state = { activeMs: 0, idleMs: 0 };
  for (let i = 0; i < 120; i++)
    state = Model.activityTick(film, state, Model.awayNow(true, true), MIN);
  check("away: two hours of film is two hours at the machine",
        Math.floor(state.activeMs / 60000), 120);
  check("away: and the reset never fired", state.idleMs, 0);

  // The same two hours with nothing playing is somebody who left.
  let gone = { activeMs: 0, idleMs: 0 };
  for (let i = 0; i < 120; i++)
    gone = Model.activityTick(film, gone, Model.awayNow(true, false), MIN);
  check("away: two hours of nothing is two hours away", gone.activeMs, 0);
}

// And that the service feeds the clock this answer rather than the raw idle
// flag. Silent otherwise: the count would simply be wrong, slowly.
const tickBody = (() => {
  const start = serviceSrc.indexOf("function activityTick(");
  if (start < 0) return null;
  const end = serviceSrc.indexOf("\n  }", start);
  return end < 0 ? null : serviceSrc.slice(start, end);
})();

check("away: the service tick was found in Service.qml", tickBody !== null, true);
if (tickBody) {
  check("away: the clock is fed the media-aware answer",
        tickBody.includes("root.awayFromPost"), true);
  check("away: and not the raw idle flag",
        tickBody.includes("idleWatch.isIdle"), false);
}

// ------------------------------------------- carrying the count across a restart
//
// The shell restarts on a theme change or any plugin edit. Until this existed,
// each one handed out a fresh three hours -- which made the one thing that is
// deliberately not a choice into a choice.

check("saved: nothing written is nothing to carry",
      Model.parseActivityState(""), { activeMs: 0, idleMs: 0, at: 0 });
check("saved: junk in the file is nothing to carry",
      Model.parseActivityState("}{ not json"), { activeMs: 0, idleMs: 0, at: 0 });
check("saved: a JSON scalar is not a state either",
      Model.parseActivityState("42"), { activeMs: 0, idleMs: 0, at: 0 });
check("saved: negatives and nonsense are read as zero",
      Model.parseActivityState('{"activeMs":-5,"idleMs":"x","at":0}'),
      { activeMs: 0, idleMs: 0, at: 0 });
check("saved: a real one round-trips",
      Model.parseActivityState('{"version":1,"activeMs":5400000,"idleMs":0,"at":1000}'),
      { activeMs: 90 * MIN, idleMs: 0, at: 1000 });

const RCFG = ACT({ breakAfterMinutes: 180, idleResetMinutes: 15 });
const SAVED = (activeMinutes, at, idleMinutes) =>
  ({ activeMs: activeMinutes * MIN, idleMs: (idleMinutes || 0) * MIN, at: at });

// The one that matters: a quick restart keeps the stretch.
check("restore: a shell restart does not hand out a fresh stretch",
      Model.restoreActivity(RCFG, SAVED(147, 1000), 1000 + 20000).activeMs, 147 * MIN);
check("restore: and says so",
      Model.restoreActivity(RCFG, SAVED(147, 1000), 1000 + 20000).kept, true);
check("restore: the gap counts as time away",
      Model.restoreActivity(RCFG, SAVED(147, 1000), 1000 + 20000).idleMs, 20000);

// Away long enough is the break, however the machine spent it.
check("restore: away past the reset and the stretch is gone",
      Model.restoreActivity(RCFG, SAVED(147, 1000), 1000 + 16 * MIN).activeMs, 0);
check("restore: which is not the same as having carried nothing",
      Model.restoreActivity(RCFG, SAVED(147, 1000), 1000 + 16 * MIN).gapMs, 16 * MIN);
check("restore: an overnight shutdown is simply a long time away",
      Model.restoreActivity(RCFG, SAVED(179, 1000), 1000 + 9 * 3600000).kept, false);
// A fast reboot is a short absence and nothing more. The machine being off is
// the longest kind of away there is; two minutes of it is worth two minutes.
check("restore: a two minute reboot keeps the stretch",
      Model.restoreActivity(RCFG, SAVED(179, 1000), 1000 + 2 * MIN).activeMs, 179 * MIN);
// Idle already banked before the restart adds to the gap rather than being
// dropped: eleven minutes away then a five minute restart is sixteen away.
check("restore: idle already banked is not forgotten",
      Model.restoreActivity(RCFG, SAVED(147, 1000, 11), 1000 + 5 * MIN).kept, false);

// A stretch that was already owed is still owed. Restarting the shell is not
// how you get out of a break.
//
// Not on the restored state itself: that carries the gap as time away, and a
// decision never demands while they are away -- they would be having the
// break. It fires on the first tick that finds them back at the machine, one
// tick and fifteen seconds after the shell came up, which is the same answer
// arrived at honestly.
const owed = Model.restoreActivity(RCFG, SAVED(200, 1000), 1000 + MIN);
const backAtIt = Model.activityTick(RCFG, { activeMs: owed.activeMs, idleMs: owed.idleMs }, false, 15000);
check("restore: a break already owed is not waved off by restarting",
      [owed.kept, Model.activityDecision(RCFG, backAtIt, 0, 1000).action],
      [true, "demand"]);

check("restore: a clock moved backwards buys nothing",
      Model.restoreActivity(RCFG, SAVED(147, 9 * MIN), MIN).activeMs, 147 * MIN);
check("restore: nothing saved is a fresh start",
      Model.restoreActivity(RCFG, SAVED(0, 1000), 5000).kept, false);
check("restore: no timestamp is not trusted",
      Model.restoreActivity(RCFG, SAVED(147, 0), 5000).kept, false);
check("restore: junk does not crash",
      Model.restoreActivity(RCFG, null, 5000).activeMs, 0);
check("restore: nothing is carried while breaks are off",
      Model.restoreActivity(Model.parseActivity({ breakAfterMinutes: 180 }), SAVED(147, 1000), 2000).kept,
      false);

// The same round-trip check the config gets, for the same reason: a key the
// writer emits and the parser ignores is a stretch that silently stops
// carrying, and nothing about the running shell would look wrong.
const activityWrite = (() => {
  const start = serviceSrc.indexOf("activityFile.write(JSON.stringify({");
  if (start < 0) return null;
  const end = serviceSrc.indexOf("}) +", start);
  return end < 0 ? null : serviceSrc.slice(start, end);
})();

check("round trip: the activity writer was found in Service.qml", activityWrite !== null, true);

// Switching the reminders off is judged by the same rule as a restart, and for
// the same reason: off means nobody is counting, which is indistinguishable
// from the shell not being there. The service routes both through
// restoreActivity, so the rule below is the rule the toggle gets.
//
// The toggle used to zero the count on the way out and start from zero on the
// way back, which made it a switch that bought a fresh three hours.
const t0 = 10 * 3600000;
check("toggle: a flick keeps the stretch",
      Model.restoreActivity(RCFG, SAVED(147, t0), t0 + 90000).activeMs, 147 * MIN);
check("toggle: off long enough to have had a break is a break",
      Model.restoreActivity(RCFG, SAVED(147, t0), t0 + 16 * MIN).kept, false);
check("toggle: off, restarted, on -- still the same stretch",
      Model.restoreActivity(RCFG, SAVED(147, t0), t0 + 4 * MIN).activeMs, 147 * MIN);

// And that the service actually routes it that way. A silent failure
// otherwise: the toggle would look identical and quietly hand out three hours.
const toggleBody = (() => {
  const start = serviceSrc.indexOf("function setActivityEnabled(");
  if (start < 0) return null;
  const end = serviceSrc.indexOf("\n  }", start);
  return end < 0 ? null : serviceSrc.slice(start, end);
})();

check("toggle: setActivityEnabled was found in Service.qml", toggleBody !== null, true);

if (toggleBody) {
  check("toggle: switching on picks the count back up rather than starting it",
        toggleBody.includes("applySavedCount"), true);
  check("toggle: and nothing on that path zeroes the count",
        toggleBody.includes("resetActivityCount"), false);
  // The stamp on the way out is what the gap on the way back is measured
  // from. Without it the gap runs from the last tick, which understates how
  // long the switch was off by up to the tick interval -- and, worse, keeps
  // running from a stale mark if it is off for days.
  check("toggle: switching off stamps the record",
        toggleBody.includes("persistActivity"), true);
}

if (activityWrite) {
  const written = new Set(
    [...activityWrite.matchAll(/^\s{6}([A-Za-z_][A-Za-z0-9_]*)\s*:/gm)].map(m => m[1]));
  // `version` is written and deliberately not read back: the reader is
  // defensive about every field anyway, so there is nothing for it to gate.
  written.delete("version");
  const read = Object.keys(Model.parseActivityState("{}"));
  check("round trip: everything the restore reads is also written",
        read.filter(k => !written.has(k)), []);
  check("round trip: and nothing is written that the restore ignores",
        [...written].filter(k => read.indexOf(k) === -1), []);
}

// -----------------------------------------------------------------------------

if (failures > 0) {
  console.error(`\n${failures} of ${checks} checks failed`);
  process.exit(1);
}
console.log(`${checks} checks passed`);