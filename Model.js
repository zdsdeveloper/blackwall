.pragma library

// Pure helpers for the Blackwall plugin. Kept out of the QML so the lock
// surface stays declarative and this arithmetic can be reasoned about (and
// eyeballed) on its own.

var MIN_SECONDS = 30
var MAX_SECONDS = 12 * 3600
var WARN_MINUTES = 30

function clamp(value, low, high) {
  if (!isFinite(value)) return low
  return value < low ? low : (value > high ? high : value)
}

// Presets offered on the bar menu. Anything past the last one has to come in
// through the custom field, which is where the long-lock warning lives.
var PRESET_MINUTES = [5, 10, 15, 30]

function needsWarning(minutes) {
  return Number(minutes) > WARN_MINUTES
}

function secondsForMinutes(minutes) {
  var n = Math.round(Number(minutes) * 60)
  return Math.round(clamp(n, MIN_SECONDS, MAX_SECONDS))
}

function pad(n) {
  return n < 10 ? "0" + n : String(n)
}

// Remaining time as it appears on the lock screen. Seconds are rounded up so
// a freshly engaged 5:00 lock reads "05:00" rather than "04:59".
function formatRemaining(milliseconds) {
  var total = Math.max(0, Math.ceil(Number(milliseconds) / 1000))
  var hours = Math.floor(total / 3600)
  var minutes = Math.floor((total % 3600) / 60)
  var seconds = total % 60
  if (hours > 0) return hours + ":" + pad(minutes) + ":" + pad(seconds)
  return pad(minutes) + ":" + pad(seconds)
}

// Human phrasing for menu labels and the confirmation copy.
function formatDuration(minutes) {
  var n = Math.round(Number(minutes))
  if (!isFinite(n) || n <= 0) return "0 min"
  if (n < 60) return n + " min"
  var hours = Math.floor(n / 60)
  var rest = n % 60
  var head = hours + (hours === 1 ? " hour" : " hours")
  return rest === 0 ? head : head + " " + rest + " min"
}

// Wall-clock deadline is the source of truth, not an accumulated tick count,
// so a suspend/resume or a shell restart cannot shorten or extend a lock.
function parseDeadline(raw) {
  var value = Number(String(raw || "").trim())
  return isFinite(value) && value > 0 ? value : 0
}

// State file: { version, deadline, bootId }. Files written before the boot id
// existed are a bare number; they parse with an empty bootId, which reads as
// "boot unknown" and takes the conservative branch on resume.
function parseState(raw) {
  var text = String(raw || "").trim()
  if (text === "") return { deadline: 0, bootId: "" }

  try {
    var parsed = JSON.parse(text)
    if (parsed && typeof parsed === "object") {
      return {
        deadline: parseDeadline(parsed.deadline),
        bootId: String(parsed.bootId || "")
      }
    }
  } catch (e) {
    // Fall through to the legacy bare-number form.
  }

  return { deadline: parseDeadline(text), bootId: "" }
}

// User config: { version, persistAcrossReboot }. Anything unreadable defaults
// to persisting, which matches the behaviour the plugin shipped with.
// What a breach challenge asks to be typed when the config does not say. There
// is always a phrase, and it is never empty: a challenge nobody can answer is
// just a lock with extra steps.
var DEFAULT_CHALLENGE_PHRASE = "I chose this wall"

// Does what was typed answer the challenge?
//
// Case and surrounding whitespace are forgiven deliberately. The friction is
// meant to come from having to type the sentence at all -- at 2am, while the
// wall is on the screen -- not from fighting the shift key. Interior spacing is
// NOT collapsed: the phrase is the operator's own words and they should get
// back exactly what they wrote.
//
// Lives here rather than in the overlay so it can be tested without a compositor.
function phraseMatches(typed, expected) {
  var a = String(typed === undefined || typed === null ? "" : typed).trim().toLowerCase()
  var b = String(expected === undefined || expected === null ? "" : expected).trim().toLowerCase()
  // An empty expectation can never be answered, so it must never be satisfied
  // either -- otherwise a config that failed to load would open the challenge
  // to the empty string.
  return b !== "" && a === b
}

function parseConfig(raw) {
  var defaults = {
    persistAcrossReboot: true,
    soundPath: "",
    soundEnabled: true,
    challengePhrase: DEFAULT_CHALLENGE_PHRASE,
    agents: {},
    // Derived, never written out by hand. A literal here drifted from
    // parseSchedule the moment that grew a field, which is the same shape of
    // fault as a key the parser knows and the writer does not: two places
    // holding the same truth, and only one of them updated.
    schedule: parseSchedule({}),
    activity: parseActivity({})
  }
  var text = String(raw || "").trim()
  if (text === "") return defaults

  try {
    var parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== "object") return defaults
    return {
      persistAcrossReboot: parsed.persistAcrossReboot !== false,
      // Empty means "look in sounds/". An explicit path wins over it.
      soundPath: String(parsed.soundPath || ""),
      // Anything that is not literally false leaves the sound on, which is
      // the behaviour the plugin shipped with and the one that fails safe:
      // a config that will not parse should not silently mute the wall.
      soundEnabled: parsed.soundEnabled !== false,
      // Falls back rather than ever landing empty, for the same reason.
      challengePhrase: String(parsed.challengePhrase || "").trim()
        || DEFAULT_CHALLENGE_PHRASE,
      // { "046d:405e": "ZAMIL" } -- a pointing device's USB id to the name
      // the station greets. Anything that is not a plain object reads as no
      // agents configured rather than taking the config down with it.
      agents: (parsed.agents && typeof parsed.agents === "object"
               && !Array.isArray(parsed.agents)) ? parsed.agents : {},
      schedule: parseSchedule(parsed.schedule),
      activity: parseActivity(parsed.activity)
    }
  } catch (e) {
    return defaults
  }
}

// ------------------------------------------------------------- the station

// One ledger entry as a line on the station's tail.
//
// The detail column carries whatever that kind of entry is actually about --
// the domain for an add, the reason for a breach, the repaired file for a
// drift. A log that printed only the kind would be a list of nouns.
// The three columns of a console line, kept apart so a caller can show some
// and hide others. The detail column is the only one that carries a domain
// name -- in `domain` directly, and inside a breach reason -- which is what
// makes it the column the station redacts.
function stationLogParts(entry) {
  if (!entry || typeof entry !== "object")
    return { stamp: "", kind: "", detail: "" }
  var kind = String(entry.kind || "?")
  var at = Number(entry.at)
  var stamp = "--:--:--"
  if (isFinite(at) && at > 0) {
    var d = new Date(at * 1000)
    stamp = pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
  }
  var detail = ""
  if (entry.domain) {
    detail = String(entry.domain)
  } else if (entry.reasons && entry.reasons.length) {
    detail = String(entry.reasons[0])
  } else if (entry.targets && entry.targets.length) {
    detail = entry.targets.join(", ")
  }
  return { stamp: stamp, kind: kind, detail: detail }
}

// Blocks standing in for text that is not to be read at a glance.
//
// The run is quantised rather than matching the original length exactly: a
// redaction the same width as what it hides tells a reader how long the word
// was, and with a list of known sites that is most of the way to telling them
// which one it was.
function redact(text) {
  var s = String(text === null || text === undefined ? "" : text)
  if (s === "") return ""
  var n = Math.min(40, Math.max(4, Math.ceil(s.length / 4) * 4))
  var out = ""
  for (var i = 0; i < n; i++) out += "\u2588"
  return out
}

// `censor` is optional and defaults off, so every existing caller is
// unchanged. With it set, the detail column -- the only one that carries a
// domain name -- comes back as blocks.
function stationLogLine(entry, censor) {
  var parts = stationLogParts(entry)
  if (parts.stamp === "" && parts.kind === "") return ""
  // Padded so the kinds line up into a column. A tail that jitters left and
  // right is harder to skim than one that does not.
  var kindCell = parts.kind
  while (kindCell.length < 9) kindCell += " "
  var detail = censor ? redact(parts.detail) : parts.detail
  return parts.stamp + "  " + kindCell
    + (detail === "" ? "" : "  " + detail)
}

// ---------------------------------------------------------------- animation

var TAU = Math.PI * 2

// The ripple is one travelling wave sampled per horizontal slice: `index` is
// the slice, `count` the total, `phase` the animated 0..TAU driver. Slices
// share the wave, so brightness and horizontal displacement stay in step and
// the wall reads as one surface flexing rather than N independent bands.
function waveAt(index, count, phase, wavelength) {
  var span = count > 1 ? index / (count - 1) : 0
  return Math.sin(phase + span * TAU * (wavelength || 1.6))
}

// 0..1 brightness for a slice. `breath` (0..1) lifts the whole wall on the
// inhale so the ripple never fully dies down between pulses.
function intensityAt(index, count, phase, breath) {
  var wave = waveAt(index, count, phase)
  var lifted = 0.5 + 0.5 * wave
  return clamp(0.18 + 0.52 * lifted + 0.30 * Number(breath || 0), 0, 1)
}

// Horizontal displacement in pixels for a slice, scaled by the breath so the
// wall visibly swells and settles.
function offsetAt(index, count, phase, amplitude, breath) {
  return waveAt(index, count, phase) * Number(amplitude || 0) * (0.55 + 0.45 * Number(breath || 0))
}

// ------------------------------------------------- the reconnection sequence
//
// When the countdown reaches zero the wall does not simply vanish — it opens,
// and the sequence below is that opening. Everything is expressed as
// fractions of one 0..1 progress value so the visuals, the audio fade, and
// the shatter all stay locked to the same clock and cannot drift apart.
//
// Phases, by fraction of the sequence:
//
//   0.00 .. 0.16   breach   the wall registers the hit; BREACH DETECTED
//   0.16 .. 0.70   press    faces come up against it, the meter fills
//   0.70 .. 0.88   surge    everything peaks, the wall goes white-hot
//   0.88 .. 1.00   shatter  the rows fly apart and collapse to black
var RELEASE_MS = 4600

var BREACH_END = 0.16
var PRESS_END  = 0.70
var SURGE_END  = 0.88

function releasePhase(p) {
  if (p <= 0) return "idle"
  if (p < BREACH_END) return "breach"
  if (p < PRESS_END) return "press"
  if (p < SURGE_END) return "surge"
  return "shatter"
}

// 0..1 position within an arbitrary span of the sequence, clamped at both
// ends so callers can write `phaseSpan(p, SURGE_END, 1)` without guarding.
function phaseSpan(p, from, to) {
  if (to <= from) return 0
  return clamp((p - from) / (to - from), 0, 1)
}

// Multiplier on the glitch field. Spikes on the breach, settles, climbs
// through the press, peaks on the surge, then falls away to nothing as the
// picture collapses.
function glitchBoost(p) {
  if (p <= 0) return 1
  var phase = releasePhase(p)
  if (phase === "breach") {
    // Hard hit, then a partial recovery — the wall absorbing the blow.
    var b = phaseSpan(p, 0, BREACH_END)
    return 1 + 2.0 * Math.sin(b * Math.PI) + 0.3 * b
  }
  if (phase === "press") return 1.3 + 0.5 * phaseSpan(p, BREACH_END, PRESS_END)
  if (phase === "surge") return 1.8 + 1.6 * phaseSpan(p, PRESS_END, SURGE_END)
  // Shatter: the field dies with the image.
  return 3.4 * (1 - phaseSpan(p, SURGE_END, 1))
}

// Ripple amplitude multiplier — the wall flexes harder as it gives way.
function rippleBoost(p) {
  if (p <= 0) return 1
  var phase = releasePhase(p)
  if (phase === "breach") return 1 + 3.0 * Math.sin(phaseSpan(p, 0, BREACH_END) * Math.PI)
  if (phase === "press") return 1.4 + 1.1 * phaseSpan(p, BREACH_END, PRESS_END)
  if (phase === "surge") return 2.5 + 3.5 * phaseSpan(p, PRESS_END, SURGE_END)
  return 6.0
}

// 0..1: how far the wall has bleached from red toward white-hot. The colour
// shift is what sells "thinning" — a red wall going pale is a wall you can
// nearly see through.
function bleach(p) {
  if (p <= 0) return 0
  var phase = releasePhase(p)
  if (phase === "breach") return 0.25 * phaseSpan(p, 0, BREACH_END)
  if (phase === "press") return 0.25 + 0.25 * phaseSpan(p, BREACH_END, PRESS_END)
  return 0.5 + 0.35 * phaseSpan(p, PRESS_END, SURGE_END)
}

// Deterministic per-slice randomness for the shatter, so a row always flies
// the same way rather than reshuffling every frame.
function shatterSeed(index) {
  var v = Math.sin((index + 1) * 12.9898) * 43758.5453
  return v - Math.floor(v)
}

// How far a row has flown, in multiples of its own width. Quadratic so the
// break starts slow and then lets go.
function shatterOffset(index, p, width) {
  var t = phaseSpan(p, SURGE_END, 1)
  if (t <= 0) return 0
  var seed = shatterSeed(index)
  var direction = seed < 0.5 ? -1 : 1
  var speed = 0.22 + 0.85 * seed
  return direction * speed * t * t * width
}

// Rows also part vertically, away from the middle of the wall, so the break
// opens outward instead of only sliding sideways.
function shatterDrift(index, count, p, height) {
  var t = phaseSpan(p, SURGE_END, 1)
  if (t <= 0) return 0
  var mid = (count - 1) / 2
  var fromCentre = count > 1 ? (index - mid) / mid : 0
  return fromCentre * (0.55 + 0.5 * shatterSeed(index + 31)) * t * t * height
}

function shatterFade(index, p) {
  var t = phaseSpan(p, SURGE_END, 1)
  if (t <= 0) return 1
  // Rows let go at slightly different moments.
  var stagger = 0.18 * shatterSeed(index + 97)
  var linear = clamp(1 - (t - stagger) / (1 - stagger), 0, 1)
  return linear * linear
}

// Block-style meter, in the same vocabulary as the logo: "████████░░░░░░░░".
function progressBlocks(fraction, cells) {
  var total = Math.max(1, Math.round(cells || 28))
  var filled = Math.round(clamp(fraction, 0, 1) * total)
  var out = ""
  for (var i = 0; i < total; i++) out += (i < filled ? "█" : "░")
  return out
}

// The meter tracks the press phase, not the whole sequence: it is full by the
// time the surge starts, so the last second reads as consequence rather than
// as a progress bar still counting.
function releaseMeter(p) {
  return clamp(phaseSpan(p, 0, SURGE_END), 0, 1)
}

// How strongly the things on the other side are pressing, 0..1. They are
// barely there when the wall first takes the hit, hardest against it through
// the press and surge, and gone once it comes apart — whatever was behind it
// is through by then, and lingering ghosts would undercut the shatter.
function facePressure(p) {
  if (p <= 0) return 0
  var phase = releasePhase(p)
  if (phase === "breach") return 0.30 * phaseSpan(p, 0, BREACH_END)
  if (phase === "press") return 0.30 + 0.70 * phaseSpan(p, BREACH_END, PRESS_END)
  if (phase === "surge") return 1.0
  return 1.0 - phaseSpan(p, SURGE_END, 1)
}


// ---------------------------------------------------------------- the agent
//
// The station greets whoever is at it by recognising their pointing device.
//
// This RECOGNISES. It does not authenticate, and nothing anywhere is gated on
// it. Anyone holding that mouse is greeted by that name, a USB id is four
// bytes anyone can claim, and the file listing them is world-readable. It is a
// nameplate on a door, not a lock -- and in a plugin whose whole subject is
// enforcement it is worth being exact about which of the two a thing is.

// The pointing devices the kernel currently knows about, parsed out of
// /proc/bus/input/devices.
//
// Never raises: a boot sequence that dies on an unfamiliar kernel format would
// take the window with it, and the honest answer to an unreadable device list
// is an empty one.
function parsePointers(raw) {
  var text = String(raw || "")
  if (text === "") return []
  var out = []
  var blocks = text.split(/\n\s*\n/)
  for (var i = 0; i < blocks.length; i++) {
    var block = blocks[i]
    // A pointing device is one the kernel gave a mouse handler to. That
    // catches the touchpad as well as the mouse, which is correct -- both are
    // pointers, and it is the configured id that picks one out, not this.
    if (!/H:\s*Handlers=[^\n]*\bmouse\d/.test(block)) continue
    var ids = block.match(/I:[^\n]*Vendor=([0-9a-fA-F]{1,4})\s+Product=([0-9a-fA-F]{1,4})/)
    if (!ids) continue
    var name = block.match(/N:\s*Name="([^"]*)"/)
    // Uniq is the device's own address where it has one -- a Unifying
    // receiver's pairing address, a Bluetooth MAC. Most devices leave it
    // blank, which is why it is carried alongside vendor:product rather than
    // instead of it.
    var uniq = block.match(/U:\s*Uniq=(\S+)/)
    out.push({
      id: (ids[1] + ":" + ids[2]).toLowerCase(),
      uniq: uniq ? uniq[1].toLowerCase() : "",
      name: name ? name[1] : ""
    })
  }
  return out
}

// The first pointer with a name against it, or "" for none.
function identifyAgent(pointers, agents) {
  if (!agents || typeof agents !== "object") return ""
  if (!pointers || !pointers.length) return ""
  // Both sides are lowercased before comparing. The device id is normalised
  // on the way out of parsePointers, but the config is hand-written, and
  // whether someone typed 046D or 046d must not decide whether they are
  // recognised.
  // Object.create(null), not {}. A plain object inherits from
  // Object.prototype, so a lookup of "__proto__" -- or "constructor", or
  // "toString" -- finds something truthy that was never configured, and a
  // device is free to advertise any of them as its address. The greeting
  // would then be a JavaScript object rendered as [object Object]. Nothing is
  // gated on this, so it is a cosmetic failure, but it is one a USB device
  // gets to choose, and a map keyed by attacker-supplied strings should not
  // have inherited keys in it.
  var byId = Object.create(null)
  for (var key in agents) {
    if (agents.hasOwnProperty(key) && agents[key])
      byId[String(key).toLowerCase()] = String(agents[key])
  }
  for (var i = 0; i < pointers.length; i++) {
    var p = pointers[i]
    if (!p) continue
    // Uniq first: vendor:product names a model, and every M720 on earth is
    // 046d:405e. Uniq names the device. A blank one is skipped rather than
    // looked up, or three devices with no address between them would all
    // match a config that happened to carry an empty key.
    if (p.uniq) {
      var byUniq = byId[String(p.uniq).toLowerCase()]
      if (byUniq) return byUniq
    }
    if (p.id) {
      var name = byId[String(p.id).toLowerCase()]
      if (name) return name
    }
  }
  return ""
}


// ------------------------------------------------------------- the schedule
//
// Windows of time the wall closes by itself: a bedtime, a standing commitment,
// anything recurring. Kept as pure functions over a Date so every awkward case
// -- crossing midnight, a window that only runs on some days, the moment one
// window ends and another begins -- is decided here and can be tested without
// a clock.
//
// Windows can come from config or be handed in by another plugin. The
// scheduler does not care which, which is what lets something else own a
// domain it understands better -- prayer times, say, which are astronomical
// and depend on where you are.

// Known limits, so they are known rather than lurking. All three were found
// by review and all three are wall-clock consequences rather than bugs in the
// arithmetic here:
//
//   * The clock going BACKWARDS extends a lock. remainingMs is deadline minus
//     Date.now(), so an NTP correction or a manual change backwards inflates
//     what is left. A monotonic clock would fix it, but the deadline is also
//     persisted across reboots as wall-clock time, so that is a larger change
//     than it looks and is not made here.
//
//   * DST spring-forward skips an hour, and a window contained entirely in the
//     skipped hour never fires that day. 02:00-03:00 on the changeover, once a
//     year, in this timezone.
//
//   * DST fall-back repeats an hour, so a window can be briefly re-evaluated
//     against a time it has already seen. The capped stretches and the gap
//     make this survivable rather than serious.
//
// None of them can extend a lock past maxLockMinutes at a stretch, which is
// what the cap is for.

var DAY_KEYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]

// "23:30" -> 1410. Anything unparseable is -1, which never matches.
function minutesOfDay(text) {
  var m = /^\s*(\d{1,2})\s*:\s*(\d{2})\s*$/.exec(String(text || ""))
  if (!m) return -1
  var h = Number(m[1]), min = Number(m[2])
  if (!isFinite(h) || !isFinite(min)) return -1
  if (h < 0 || h > 23 || min < 0 || min > 59) return -1
  return h * 60 + min
}

function normaliseWindow(raw) {
  if (!raw || typeof raw !== "object") return null
  var start = minutesOfDay(raw.start)
  var end = minutesOfDay(raw.end)
  if (start < 0 || end < 0 || start === end) return null

  // `days` names the days a window STARTS on, not every day it touches. A
  // bedtime from 23:30 Friday to 06:00 Saturday is a Friday window; saying
  // otherwise would either miss Friday night or add an unwanted Saturday one.
  var days = []
  if (Array.isArray(raw.days)) {
    for (var i = 0; i < raw.days.length; i++) {
      var k = String(raw.days[i] || "").slice(0, 3).toLowerCase()
      var at = DAY_KEYS.indexOf(k)
      if (at >= 0 && days.indexOf(at) < 0) days.push(at)
    }
  }
  // No days named means every day, which is the useful default for a bedtime.
  if (days.length === 0) days = [0, 1, 2, 3, 4, 5, 6]

  return {
    label: String(raw.label || "Scheduled"),
    start: start,
    end: end,
    days: days.sort(function (a, b) { return a - b }),
    // 23:30 -> 06:00 wraps; 09:00 -> 17:00 does not.
    wraps: end < start
  }
}

function parseSchedule(raw) {
  // Anything unusable is treated as an empty schedule and then built the same
  // way as a real one, rather than short-circuiting to a literal. That literal
  // existed, and it drifted the moment this function grew a field -- the third
  // time in this file that the same truth written in two places has gone out
  // of step. One construction path, so there is nothing to keep in step.
  if (!raw || typeof raw !== "object") raw = {}
  var windows = []
  if (Array.isArray(raw.windows)) {
    for (var i = 0; i < raw.windows.length; i++) {
      var w = normaliseWindow(raw.windows[i])
      if (w) windows.push(w)
    }
  }
  var warn = Number(raw.warnSeconds)
  var cap = Number(raw.maxLockMinutes)
  var gap = Number(raw.gapSeconds)
  return {
    enabled: raw.enabled === true,
    // Clamped: no warning at all is a lock that arrives out of nowhere, and an
    // hour of warning is not a warning.
    warnSeconds: isFinite(warn) ? clamp(Math.round(warn), 0, 900) : 120,

    // The safety valve, and the reason it exists.
    //
    // A scheduled lock runs for what is left of its window, and a window
    // entered wrong costs exactly that. A bedtime typed 23:30-06:00 with the
    // wrong days locked this machine for 226 minutes in a single tick, from a
    // test written to avoid doing that.
    //
    // So a lock is taken in stretches of at most maxLockMinutes, with
    // gapSeconds of daylight between them. A window you meant still holds --
    // it re-engages as soon as the gap closes, and you would have to
    // deliberately intervene every stretch to escape it. A window you did not
    // mean costs one stretch, and then hands you a moment to turn it off.
    //
    // The gap is the whole point. A cap that re-engaged instantly would be
    // continuous lockout with extra steps.
    maxLockMinutes: isFinite(cap) ? clamp(Math.round(cap), 1, 720) : 30,
    gapSeconds: isFinite(gap) ? clamp(Math.round(gap), 5, 600) : 45,
    windows: windows
  }
}

// How long the next scheduled stretch should run, in minutes: what is left of
// the window, but never more than the cap.
function scheduledStretch(minutesLeft, maxLockMinutes) {
  var left = Math.floor(Number(minutesLeft))
  if (!isFinite(left) || left < 1) return 0
  var cap = Math.floor(Number(maxLockMinutes))
  if (!isFinite(cap) || cap < 1) cap = 30
  return Math.min(left, cap)
}

// How many minutes into the week a moment is, 0 = Sunday 00:00.
//
// Minute resolution: seconds are dropped. Everything downstream inherits it,
// so a window can be entered up to a minute late and a lock can outlive its
// window by under a minute. Both are inside engage's own 30s floor and neither
// is worth carrying seconds through the whole file to avoid.
function weekMinutes(date) {
  return date.getDay() * 1440 + date.getHours() * 60 + date.getMinutes()
}

// Every occurrence of a window in the week, as [openMinute, closeMinute) pairs
// on the same 0..10080 line. A wrapping window can run past the end of the
// week, which is why the close is allowed to exceed 10080.
function windowSpans(w) {
  var out = []
  for (var i = 0; i < w.days.length; i++) {
    var open = w.days[i] * 1440 + w.start
    var length = w.wraps ? (1440 - w.start) + w.end : (w.end - w.start)
    out.push({ open: open, close: open + length, label: w.label })
  }
  return out
}

// The window covering this moment, or null.
function activeWindowAt(windows, date) {
  if (!windows || !windows.length) return null
  var now = weekMinutes(date)
  for (var i = 0; i < windows.length; i++) {
    var spans = windowSpans(windows[i])
    for (var j = 0; j < spans.length; j++) {
      var s = spans[j]
      // Checked at +10080 as well, so a window that started late last week
      // and runs into this one is still found.
      if ((now >= s.open && now < s.close) ||
          (now + 10080 >= s.open && now + 10080 < s.close)) {
        return { label: s.label, endsInMinutes: Math.ceil(
          (now >= s.open ? s.close - now : s.close - (now + 10080))) }
      }
    }
  }
  return null
}

// The next window due to open, and how long until it does.
function nextWindowAt(windows, date) {
  if (!windows || !windows.length) return null
  var now = weekMinutes(date)
  var best = null
  for (var i = 0; i < windows.length; i++) {
    var spans = windowSpans(windows[i])
    for (var j = 0; j < spans.length; j++) {
      var s = spans[j]
      // This week's occurrence if it is still ahead, otherwise next week's.
      var until = s.open - now
      if (until < 0) until += 10080
      if (best === null || until < best.inMinutes)
        best = { label: s.label, inMinutes: until }
    }
  }
  return best
}


// What the scheduler should do at this instant.
//
// Pulled out of the QML deliberately. The decision to take someone's screen
// away is the most consequential thing this plugin does automatically, and
// while it lived inside a Timer handler it could not be tested at all -- which
// is how a window entered wrong came to engage for 226 minutes in a single
// tick. Here it is a pure function of its inputs and every branch is reachable
// from a test.
//
// The caller supplies:
//   schedule   what parseSchedule produced
//   windows    every window in force, from config and from providers alike
//   now        a Date
//   holding    whether the wall is already up, for any reason
//   gapUntilMs epoch ms before which no new stretch may be taken
//
// It returns one of:
//   { action: "none" }
//   { action: "warn", label, inMinutes }
//   { action: "lock", label, minutes, gapUntilMs }
//
// It never returns "lock" while holding, never for longer than the cap, and
// never inside the gap.
function scheduleDecision(schedule, windows, now, holding, gapUntilMs) {
  var none = { action: "none" }
  if (!schedule || schedule.enabled !== true) return none
  if (!windows || !windows.length) return none
  // Duck-typed, not `instanceof Date`. A Date built in one JS realm is not an
  // instance of another realm's Date, and this file is a QML JavaScript
  // library evaluated in its own scope -- so the check can quietly answer
  // false for a perfectly good Date and the scheduler simply declines to act,
  // silently and for ever. Caught by a test harness that has the same split.
  if (!now || typeof now.getTime !== "function") return none
  var nowCheck = now.getTime()
  if (typeof nowCheck !== "number" || !isFinite(nowCheck)) return none

  var nowMs = now.getTime()
  var active = activeWindowAt(windows, now)

  if (active) {
    // Already behind the wall: the window will still be there when it falls.
    if (holding) return none
    // Inside the daylight between stretches. This is the recovery path and it
    // is deliberate.
    if (isFinite(gapUntilMs) && nowMs < gapUntilMs) return none

    var minutes = scheduledStretch(active.endsInMinutes, schedule.maxLockMinutes)
    if (minutes < 1) return none
    return {
      action: "lock",
      label: active.label,
      minutes: minutes,
      // The stretch, then the gap.
      gapUntilMs: nowMs + minutes * 60000 + schedule.gapSeconds * 1000
    }
  }

  // Nothing is open. Warn if something is about to be.
  if (holding) return none
  var next = nextWindowAt(windows, now)
  if (!next) return none
  if (next.inMinutes * 60 > schedule.warnSeconds) return none
  return { action: "warn", label: next.label, inMinutes: next.inMinutes }
}


// -------------------------------------------------------- the activity clock
//
// How long you have been at the machine without a break, and when to say so.
//
// This one only ever suggests. The scheduler takes the screen because a window
// you set says so; this watches how long you have been going and offers. A
// tracker that locked you out on its own judgement would be a different and
// much worse thing, and nothing here can engage the wall.
//
// Idle comes from ext-idle-notify via Quickshell's IdleMonitor, so "away" is
// the compositor's answer rather than a guess from mouse polling.

function parseActivity(raw) {
  if (!raw || typeof raw !== "object") raw = {}
  var after = Number(raw.breakAfterMinutes)
  var reset = Number(raw.idleResetMinutes)
  var snooze = Number(raw.snoozeMinutes)
  var grace = Number(raw.demandGraceSeconds)
  return {
    // Off unless asked for. A machine that starts making demands the day it
    // updates is a machine people switch features off on.
    enabled: raw.enabled === true,

    // Whether the break is a suggestion or a fact.
    //
    // Suggesting was the first version of this and it was the wrong one: a
    // notification you can wave away is one you wave away at hour four, which
    // is exactly when it mattered. Enforced, the choice you are offered is how
    // long the break is, not whether you take it.
    enforced: raw.enforced !== false,

    // Three hours at the machine without a real break. Long enough not to
    // interrupt a morning's work, short enough that a whole evening cannot
    // disappear. Floor of 30 so it cannot be set to something punitive by
    // accident, ceiling of 8 hours because past that it is not a break.
    breakAfterMinutes: isFinite(after) ? clamp(Math.round(after), 30, 480) : 180,

    // How long away counts as the break having happened, and so resets the
    // count. Fifteen minutes: long enough that making tea does not reset a
    // three hour stretch, short enough that a real walk away does.
    idleResetMinutes: isFinite(reset) ? clamp(Math.round(reset), 5, 120) : 15,

    // Only used when suggesting. An enforced break does not get snoozed.
    snoozeMinutes: isFinite(snooze) ? clamp(Math.round(snooze), 1, 240) : 15,

    // How long the demand waits for an answer before choosing the shortest
    // break itself. Without this, ignoring the window is a way out of it.
    demandGraceSeconds: isFinite(grace) ? clamp(Math.round(grace), 15, 600) : 90
  }
}

// The break lengths offered, in minutes. The shortest is what an unanswered
// demand settles on, so it is first.
var BREAK_CHOICES = [15, 20, 30]

function breakSeconds(minutes) {
  var m = Math.round(Number(minutes))
  if (!isFinite(m)) m = BREAK_CHOICES[0]
  // Through the same clamp the wall uses for any other lock.
  return secondsForMinutes(m)
}

// Advance the clock by `deltaMs`. Pure: takes a state, returns a new one.
//
//   activeMs  time at the machine since the last real break
//   idleMs    time away in the current stretch, 0 while active
function activityTick(cfg, state, isIdle, deltaMs) {
  var activeMs = Number(state && state.activeMs) || 0
  var idleMs = Number(state && state.idleMs) || 0
  var delta = Number(deltaMs)
  if (!isFinite(delta) || delta < 0) delta = 0
  // A jump forward -- the machine slept, or the clock moved -- is not time
  // spent working. Anything past a minute in one tick is treated as away.
  if (delta > 60000) {
    return { activeMs: 0, idleMs: idleMs + delta }
  }

  if (isIdle) {
    idleMs += delta
    // Away long enough to count as the break itself.
    if (idleMs >= cfg.idleResetMinutes * 60000) activeMs = 0
    return { activeMs: activeMs, idleMs: idleMs }
  }
  return { activeMs: activeMs + delta, idleMs: 0 }
}

// Whether a break is due, and whether it is a suggestion or a demand.
function activityDecision(cfg, state, lastPromptMs, nowMs) {
  var none = { action: "none", activeMinutes: 0 }
  if (!cfg || cfg.enabled !== true) return none
  var activeMs = Number(state && state.activeMs) || 0
  var minutes = Math.floor(activeMs / 60000)
  if (activeMs < cfg.breakAfterMinutes * 60000) return none
  // Not while they are already away -- they are having the break.
  if (Number(state && state.idleMs) > 0) return none

  // An enforced break is not snoozed. The snooze exists so a suggestion that
  // was declined does not ask again a minute later; there is nothing to
  // decline here, and honouring it would mean an ignored demand bought a
  // quarter of an hour of not being asked.
  if (cfg.enforced === true) return { action: "demand", activeMinutes: minutes }

  var last = Number(lastPromptMs) || 0
  var now = Number(nowMs) || 0
  if (last > 0 && now - last < cfg.snoozeMinutes * 60000) return none
  return { action: "suggest", activeMinutes: minutes }
}

// What the activity clock reads right now, for a surface that shows it.
//
// The service advances the clock every fifteen seconds, which is the right
// cadence for deciding something and the wrong one for showing it: a countdown
// that sits still for fifteen seconds and then drops fifteen at once reads as
// broken. This projects the state forward to `nowMs` exactly the way the next
// tick will -- the same jump guard included, so a machine that slept does not
// show an hour at the desk that nobody spent there.
//
// Pure, and it advances nothing. The state it is handed stays the service's;
// this only says what that state means at this instant.
function activityReadout(cfg, state, lastTickMs, nowMs, isAway) {
  var out = {
    enabled: false,
    away: false,
    activeMs: 0,
    activeMinutes: 0,
    breakAfterMs: 0,
    untilBreakMs: 0,
    untilBreakMinutes: 0,
    // 0..1 of the stretch spent. What a filling bar draws.
    fraction: 0,
    due: false,
    idleMs: 0,
    // While away: how much longer before being away counts as the break and
    // the stretch goes back to zero.
    resetInMs: 0
  }
  if (!cfg || cfg.enabled !== true) return out
  out.enabled = true
  out.away = isAway === true

  var activeMs = Number(state && state.activeMs) || 0
  var idleMs = Number(state && state.idleMs) || 0
  var last = Number(lastTickMs) || 0
  var now = Number(nowMs) || 0
  var since = last > 0 ? now - last : 0
  if (!(since > 0)) since = 0

  var resetMs = Math.max(0, Number(cfg.idleResetMinutes) || 0) * 60000

  if (since > 60000) {
    // The tick's own reading of a gap this size: the machine was not being
    // worked at, whatever the idle monitor says about this instant.
    idleMs += since
    activeMs = 0
  } else if (out.away) {
    idleMs += since
    if (resetMs > 0 && idleMs >= resetMs) activeMs = 0
  } else {
    activeMs += since
    idleMs = 0
  }

  var afterMs = Math.max(0, Number(cfg.breakAfterMinutes) || 0) * 60000
  out.activeMs = activeMs
  out.activeMinutes = Math.floor(activeMs / 60000)
  out.idleMs = idleMs
  out.resetInMs = Math.max(0, resetMs - idleMs)
  out.breakAfterMs = afterMs
  out.untilBreakMs = Math.max(0, afterMs - activeMs)
  out.untilBreakMinutes = Math.ceil(out.untilBreakMs / 60000)
  out.fraction = afterMs > 0 ? clamp(activeMs / afterMs, 0, 1) : 0
  out.due = afterMs > 0 && activeMs >= afterMs
  return out
}

// The activity count as it was last written down.
//
// Shaped like parseState and defensive for the same reason: this file lives at
// a predictable path, and anything at all can be sitting in it.
function parseActivityState(raw) {
  var none = { activeMs: 0, idleMs: 0, at: 0 }
  var text = String(raw || "").trim()
  if (text === "") return none
  try {
    var parsed = JSON.parse(text)
    if (!parsed || typeof parsed !== "object") return none
    var active = Number(parsed.activeMs)
    var idle = Number(parsed.idleMs)
    var at = Number(parsed.at)
    return {
      activeMs: isFinite(active) && active > 0 ? active : 0,
      idleMs: isFinite(idle) && idle > 0 ? idle : 0,
      at: isFinite(at) && at > 0 ? at : 0
    }
  } catch (e) {
    return none
  }
}

// What the count should be when the shell comes back up.
//
// Without this a shell restart handed out a fresh stretch, and the shell
// restarts on a theme change or any edit to a plugin -- which made the one
// thing that is not supposed to be a choice into a choice, and an easy one.
//
// The rule is the tick's rule, applied to the whole gap at once: time the
// shell was not running is time away from the machine, because there is no
// honest way to call it anything else. Away long enough and being away was
// the break, so the stretch is gone; short of that it is picked up where it
// was left. A reboot needs no special case -- the machine being off is the
// longest kind of away there is, and if it was off for two minutes then two
// minutes is all that is owed to it.
function restoreActivity(cfg, saved, nowMs) {
  var out = { activeMs: 0, idleMs: 0, gapMs: 0, kept: false }
  if (!cfg || cfg.enabled !== true) return out

  var s = saved || {}
  var at = Number(s.at) || 0
  var activeMs = Number(s.activeMs) || 0
  var idleMs = Number(s.idleMs) || 0
  if (!(at > 0) || !(activeMs > 0)) return out

  var gap = (Number(nowMs) || 0) - at
  // A clock that moved backwards buys nothing. The strict reading is the
  // right one here: the alternative is that setting the clock back is a way
  // of putting the break off.
  if (!(gap > 0)) gap = 0
  out.gapMs = gap

  var resetMs = Math.max(0, Number(cfg.idleResetMinutes) || 0) * 60000
  idleMs += gap
  // Away long enough that being away was the break.
  if (resetMs > 0 && idleMs >= resetMs) return out

  out.activeMs = activeMs
  out.idleMs = idleMs
  out.kept = true
  return out
}
