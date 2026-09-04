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
check("config: empty gives defaults", Model.parseConfig(""), { persistAcrossReboot: true, soundPath: "", soundEnabled: true, challengePhrase: DEFAULT, agents: {}, schedule: { enabled: false, warnSeconds: 120, maxLockMinutes: 30, gapSeconds: 45, windows: [] }, activity: { enabled: false, breakAfterMinutes: 60, idleResetMinutes: 5, snoozeMinutes: 15 } });
check("config: malformed gives defaults", Model.parseConfig("{oh no"), { persistAcrossReboot: true, soundPath: "", soundEnabled: true, challengePhrase: DEFAULT, agents: {}, schedule: { enabled: false, warnSeconds: 120, maxLockMinutes: 30, gapSeconds: 45, windows: [] }, activity: { enabled: false, breakAfterMinutes: 60, idleResetMinutes: 5, snoozeMinutes: 15 } });
check("config: a json array gives defaults", Model.parseConfig("[]"), { persistAcrossReboot: true, soundPath: "", soundEnabled: true, challengePhrase: DEFAULT, agents: {}, schedule: { enabled: false, warnSeconds: 120, maxLockMinutes: 30, gapSeconds: 45, windows: [] }, activity: { enabled: false, breakAfterMinutes: 60, idleResetMinutes: 5, snoozeMinutes: 15 } });
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
check("activity: an hour by default", Model.parseActivity({}).breakAfterMinutes, 60);
check("activity: cannot be set to nag constantly", ACT({ breakAfterMinutes: 0 }).breakAfterMinutes, 5);
check("activity: nor to never fire", ACT({ breakAfterMinutes: 99999 }).breakAfterMinutes, 480);
check("activity: junk falls back", ACT({ breakAfterMinutes: "soon" }).breakAfterMinutes, 60);
check("activity: snooze has a floor", ACT({ snoozeMinutes: 0 }).snoozeMinutes, 1);

// --- the clock ---
const cfg = ACT({ breakAfterMinutes: 60, idleResetMinutes: 5, snoozeMinutes: 15 });
check("clock: time at the keyboard accumulates",
      runFor(cfg, fresh, 30, false).activeMs, 30 * MIN);
check("clock: being away does not count as working",
      runFor(cfg, fresh, 30, true).activeMs, 0);
// A short pause is not a break.
check("clock: a two minute pause does not reset it",
      runFor(cfg, runFor(cfg, fresh, 40, false), 2, true).activeMs, 40 * MIN);
check("clock: five minutes away is the break",
      runFor(cfg, runFor(cfg, fresh, 40, false), 5, true).activeMs, 0);
check("clock: coming back starts the idle stretch over",
      runFor(cfg, runFor(cfg, fresh, 40, false), 1, false).idleMs, 0);

// A machine that slept, or a clock that jumped. Not time spent working.
check("clock: a jump forward is not work",
      Model.activityTick(cfg, { activeMs: 30 * MIN, idleMs: 0 }, false, 3 * 3600000).activeMs, 0);
check("clock: a negative delta is ignored",
      Model.activityTick(cfg, { activeMs: 5 * MIN, idleMs: 0 }, false, -9999).activeMs, 5 * MIN);
check("clock: junk state does not crash",
      Model.activityTick(cfg, null, false, MIN).activeMs, MIN);

// --- when it speaks ---
const worked = runFor(cfg, fresh, 60, false);
check("suggest: after the configured stretch",
      Model.activityDecision(cfg, worked, 0, 1000).action, "suggest");
check("suggest: and says how long", Model.activityDecision(cfg, worked, 0, 1000).activeMinutes, 60);
check("suggest: not before", Model.activityDecision(cfg, runFor(cfg, fresh, 59, false), 0, 1000).action, "none");
check("suggest: never while disabled",
      Model.activityDecision(Model.parseActivity({ breakAfterMinutes: 60 }), worked, 0, 1000).action, "none");
// They are already away; that is the break.
check("suggest: not while they are away",
      Model.activityDecision(cfg, { activeMs: 90 * MIN, idleMs: MIN }, 0, 1000).action, "none");

// --- and when it stays quiet ---
const t = 10 * 3600000;
check("snooze: quiet just after asking",
      Model.activityDecision(cfg, worked, t, t + 5 * MIN).action, "none");
check("snooze: speaks again once it has passed",
      Model.activityDecision(cfg, worked, t, t + 16 * MIN).action, "suggest");
check("snooze: never asked before, so it may ask",
      Model.activityDecision(cfg, worked, 0, t).action, "suggest");

check("config: activity is carried through",
      Model.parseConfig('{"activity":{"enabled":true,"breakAfterMinutes":90}}').activity.breakAfterMinutes, 90);
check("config: no activity block is a disabled one",
      Model.parseConfig("{}").activity.enabled, false);
check("config: junk activity does not throw",
      Model.parseConfig('{"activity":7}').activity.enabled, false);

// -----------------------------------------------------------------------------

if (failures > 0) {
  console.error(`\n${failures} of ${checks} checks failed`);
  process.exit(1);
}
console.log(`${checks} checks passed`);