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
    challengePhrase: DEFAULT_CHALLENGE_PHRASE,
    agents: {}
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
      // Falls back rather than ever landing empty, for the same reason.
      challengePhrase: String(parsed.challengePhrase || "").trim()
        || DEFAULT_CHALLENGE_PHRASE,
      // { "046d:405e": "ZAMIL" } -- a pointing device's USB id to the name
      // the station greets. Anything that is not a plain object reads as no
      // agents configured rather than taking the config down with it.
      agents: (parsed.agents && typeof parsed.agents === "object"
               && !Array.isArray(parsed.agents)) ? parsed.agents : {}
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
