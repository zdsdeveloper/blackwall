import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Services.Mpris
import "Model.js" as Model

// Blackwall: a timed session lock with no authentication path.
//
// This owns the ext-session-lock surface, the countdown, and the state file.
// It is a `service` rather than part of the bar widget on purpose — bar
// widgets are instantiated once per monitor, and a session lock must be a
// process-wide singleton.
//
// There is deliberately no unlock method, on the IPC surface or anywhere
// else. The only ways out are the deadline passing and the recovery path
// documented in README.md, which needs a TTY.
Item {
  id: root

  // Injected by the shell's service loader.
  property var shell: null
  property string omarchyPath: ""

  readonly property string home: Quickshell.env("HOME")
  readonly property string stateDir: home + "/.local/state/omarchy/blackwall"
  readonly property string statePath: stateDir + "/deadline"
  readonly property string activityPath: stateDir + "/activity"
  readonly property string configPath: home + "/.config/omarchy/zds.blackwall.json"
  readonly property string soundDir: home + "/.config/omarchy/plugins/zds.blackwall/sounds"

  // The still of the desktop that the takeover tears apart.
  //
  // In the runtime directory, which is tmpfs: whatever happened to be on the
  // screen when the wall came up never reaches persistent storage. It is
  // removed the moment the takeover is done with it, again when the lock ends,
  // and again before each capture, so a crash mid-sequence cannot leave one
  // sitting there until reboot.
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR")
  readonly property string takeoverPath:
    root.runtimeDir !== "" ? root.runtimeDir + "/blackwall-takeover.png" : ""

  // No runtime directory, no takeover.
  //
  // The fallback here used to be /tmp, which on plenty of systems is a real
  // filesystem rather than tmpfs. That would put a full uncompressed
  // photograph of whatever was on the screen -- messages, mail, a banking tab
  // -- onto persistent storage, where a crash or a power cut between the
  // capture and the cleanup leaves it until someone notices. The cleanup is
  // reliable in every case except the ones where it is not, and those are
  // exactly the cases that matter.
  //
  // An animation is not worth that trade. Without somewhere in memory to put
  // the still, the wall comes up the way it always did.
  readonly property bool takeoverPossible: root.takeoverPath !== ""
  property url takeoverSource: ""
  property bool takeoverArmed: false

  // Taken from this file's own URL rather than assumed, so the guard is found
  // wherever the plugin was installed from.
  readonly property string pluginDir:
    decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")).replace(/\/$/, "")
  readonly property string guardScript: pluginDir + "/bin/blackwall-file-guard"

  // Where the ambience comes from, in priority order:
  //   1. `soundPath` in the config file, if it points at a readable file
  //   2. the first audio file in sounds/, whatever it is called
  //   3. nothing — the lock is silent
  //
  // No audio ships with the plugin, so (2) is what makes "drop a file in
  // sounds/" work without anyone having to rename it to match a constant.
  property string configuredSoundPath: ""
  property string resolvedSoundPath: ""
  readonly property bool soundAvailable: resolvedSoundPath !== ""

  // encodeURI, not plain concatenation: a filename with a space in it is
  // completely ordinary and would otherwise produce an unusable URL.
  readonly property string soundUrl: soundAvailable ? "file://" + encodeURI(resolvedSoundPath) : ""

  // Epoch milliseconds the lock lifts at. 0 means disengaged.
  property double deadline: 0
  property double now: Date.now()
  property bool stateLoaded: false

  readonly property double remainingMs: deadline > 0 ? Math.max(0, deadline - now) : 0
  readonly property bool engaged: deadline > 0 && remainingMs > 0

  // The reconnection sequence: the wall opening, not a countdown. It runs
  // after the deadline and before the session actually unlocks.
  property bool releasing: false
  property double releaseStartedAt: 0
  readonly property real releaseProgress: releasing && releaseStartedAt > 0
    ? Model.clamp((now - releaseStartedAt) / Model.RELEASE_MS, 0, 1)
    : 0

  // The session lock must be held for both — the countdown AND the ceremony.
  // Every guard that used to ask `engaged` asks this instead, or the wall
  // would drop the moment the timer hit zero and the sequence would play to
  // an empty room.
  readonly property bool holding: engaged || releasing

  // Total span of the current lock, kept for the progress ring on the overlay.
  property double engagedSpanMs: 0

  property string lastEvent: "init"
  property string lastEventAt: ""

  // "Persist Across Reboot", owned by ~/.config/omarchy/zds.blackwall.json.
  //
  // ON  — a lock outlives a reboot and resumes for whatever time is left.
  // OFF — the lock is session-only: a shell restart or crash inside the same
  //       boot still resumes it (restarting the shell must never be an escape
  //       hatch), but a reboot clears it.
  //
  // Telling those two apart is what `bootId` is for; see resumeFromState().
  property bool persistAcrossReboot: true

  // Whether the wall makes any noise at all. A drone that loops for the length
  // of a lock needs a way off.
  property bool soundEnabled: true

  // Round-tripped rather than used here: the panel reads it, but this is what
  // writes the file, and a key this file does not carry is a key this file
  // deletes the next time anything is saved.
  property var agents: ({})

  // ---- the schedule --------------------------------------------------------
  //
  // Windows the wall closes by itself. Two sources, deliberately kept apart:
  //
  //   `scheduleConfig.windows` are the operator's own, saved in the config
  //   file and edited by hand.
  //
  //   `providedWindows` are pushed in over IPC by another plugin and held only
  //   in memory. Prayer times will arrive this way -- they are astronomical,
  //   they depend on where you are and which calculation you follow, and none
  //   of that belongs in this file. A provider recomputes them daily and
  //   pushes; nothing here needs to understand them.
  //
  // Keeping the provided set out of the config file also means two writers
  // never fight over it.
  property var scheduleConfig: ({ enabled: false, warnSeconds: 120, windows: [] })

  // ---- the activity clock --------------------------------------------------
  //
  // How long at the machine without a break, and a nudge when it has been a
  // while. This one only ever suggests: nothing here engages the wall, and the
  // notification says so. A tracker that locked you out on its own judgement
  // would be a different and much worse thing.
  //
  // Idle comes from ext-idle-notify through Quickshell's IdleMonitor, so
  // "away" is the compositor's answer rather than a guess.
  property var activityConfig: ({ enabled: false, breakAfterMinutes: 60,
                                  idleResetMinutes: 5, snoozeMinutes: 15 })
  property var activityState: ({ activeMs: 0, idleMs: 0 })
  property double activityLastPrompt: 0
  property double activityLastTick: 0

  readonly property int activeMinutes:
    Math.floor((Number(root.activityState.activeMs) || 0) / 60000)

  // Whether anything is playing.
  //
  // The compositor is asked whether an input device has been touched, which is
  // a question a film answers wrong. This asks the other one, and MPRIS
  // answers it directly: a player that says it is playing is a player being
  // watched or listened to.
  //
  // A binding rather than a reading taken at tick time, so the station's
  // "held" line is true the moment the film is paused rather than up to
  // fifteen seconds later.
  readonly property bool mediaPlaying: {
    var model = Mpris.players
    var list = model ? model.values : null
    if (!list) return false
    for (var i = 0; i < list.length; i++) {
      if (list[i] && list[i].isPlaying === true) return true
    }
    return false
  }

  // Whether nobody is at the machine.
  //
  // Exposed because the station draws this clock, and "the count is held" is a
  // different thing to tell the operator than "the count is running" -- one of
  // them means the stretch on screen is going up as they read it. Reported as
  // false when nothing is counting, so an idle monitor that is switched off
  // cannot make the station say they walked away.
  readonly property bool awayFromPost:
    root.activityConfig.enabled === true
    && Model.awayNow(idleWatch.isIdle, root.mediaPlaying)

  IdleMonitor {
    id: idleWatch
    enabled: root.activityConfig.enabled === true
    // Short, so "away" is noticed promptly and the reset counts from close to
    // when they actually left. The threshold that matters is
    // idleResetMinutes, which is measured from here.
    timeout: 30
    // Something holding idle off -- a video playing -- means they are at the
    // machine, which is exactly what this is counting.
    respectInhibitors: true
  }

  Timer {
    interval: 15000
    repeat: true
    running: root.activityConfig.enabled === true
    onTriggered: root.activityTick()
  }

  function activityTick() {
    var now = Date.now()
    var delta = root.activityLastTick > 0 ? now - root.activityLastTick : 0
    root.activityLastTick = now
    if (delta <= 0) return

    root.activityState = Model.activityTick(root.activityConfig,
                                            root.activityState,
                                            root.awayFromPost, delta)

    // Written down whenever the minute on the count changes, which is once a
    // minute at the machine and not at all while they are away.
    //
    // Not writing while away is the point rather than a saving: the timestamp
    // on the last write is what the gap on the way back is measured from, so
    // a file that stopped being touched the moment they left is exactly the
    // record that says when they left.
    if (root.activityRestored
        && root.activeMinutes !== root.persistedActiveMinute) root.persistActivity()

    // Never while the wall is up: being locked out is not working, and a
    // notification nobody can see is a notification wasted.
    if (root.holding) return

    var call = Model.activityDecision(root.activityConfig, root.activityState,
                                      root.activityLastPrompt, now)
    if (call.action === "none") return
    root.activityLastPrompt = now
    logEvent("activity: " + call.activeMinutes + " min at the machine -- "
             + call.action)

    if (call.action === "suggest") {
      breakProc.command = ["notify-send", "-a", "Blackwall",
                           "You have been at this a while",
                           "Worth a break. Lock the wall from the bar if you want one."]
      breakProc.running = true
      return
    }

    // A demand. Close what they were doing first, then ask how long -- in that
    // order, because the demand window becomes the active one the moment it
    // appears and would otherwise be what gets closed.
    //
    // closewindow, not kill: it is the same request the window's own close
    // button sends, so anything with unsaved work still gets to say so. The
    // wall covers the screen a moment later regardless; closing is about the
    // video that would otherwise keep playing behind it.
    closeProc.command = ["bash", "-c",
      "addr=$(hyprctl activewindow -j | " +
      "python3 -c 'import json,sys\n" +
      "try:\n" +
      "    w = json.load(sys.stdin)\n" +
      "except Exception:\n" +
      "    raise SystemExit\n" +
      "if isinstance(w, dict) and w.get(\"class\") != \"org.quickshell\":\n" +
      "    print(w.get(\"address\", \"\"))' 2>/dev/null); " +
      "[ -n \"$addr\" ] && hyprctl dispatch closewindow address:$addr; true"]
    closeProc.running = true

    breakDemand.preview = false
    breakDemand.activeMinutes = call.activeMinutes
    breakDemand.graceSeconds = root.activityConfig.demandGraceSeconds
    breakDemand.demanding = true
  }

  Process { id: closeProc }

  BreakDemand {
    id: breakDemand
    monoFamily: "monospace"
    onChosen: function (minutes) {
      if (breakDemand.preview) {
        // A dry run answers and stops there. Nothing is reset, nothing is
        // engaged, and the clock carries on exactly as it was.
        logEvent("activity: preview answered " + minutes + " min -- discarded")
        breakDemand.preview = false
        return
      }
      logEvent("activity: break of " + minutes + " min")
      // The count restarts from the break, not from when the wall comes down:
      // the break is the reset.
      // Written down immediately rather than at the next tick. The wall is
      // about to come up for a quarter of an hour, and a shell that goes down
      // behind it must not come back to the stretch this break just paid off.
      root.resetActivityCount()
      root.engage(Model.breakSeconds(minutes))
    }
  }

  Process { id: breakProc }

  function setActivityEnabled(value) {
    var next = !!value
    if (next === (root.activityConfig.enabled === true) && root.configLoaded)
      return next
    var updated = ({})
    for (var k in root.activityConfig)
      if (root.activityConfig.hasOwnProperty(k)) updated[k] = root.activityConfig[k]
    updated.enabled = next
    root.activityConfig = updated
    root.activityLastPrompt = 0

    // Switching the reminders off does not pay off the stretch.
    //
    // It used to: the count went to zero on the way out and started again from
    // zero on the way back, so flicking the toggle bought a fresh three hours
    // -- the same hole a shell restart used to be, with a switch on it.
    //
    // Off is treated as exactly what it is: nobody watching. Nothing is
    // counted while it is off, because nothing is being counted; and when it
    // comes back on, the time it spent off is judged as time away by the same
    // rule a restart is. Flick it and the stretch is still there. Leave it off
    // long enough to have actually had a break, and a break is what you had.
    //
    // On the way out the record is stamped now, so the gap on the way back is
    // measured from the moment the watching stopped rather than from the last
    // tick before it.
    if (next) root.applySavedCount("switch")
    else root.persistActivity()

    writeConfig()
    logEvent("activity=" + next)
    return next
  }
  property var providedWindows: ({})

  readonly property var effectiveWindows: {
    var out = (root.scheduleConfig && root.scheduleConfig.windows) || []
    var merged = out.slice()
    for (var key in root.providedWindows) {
      if (!root.providedWindows.hasOwnProperty(key)) continue
      var set = root.providedWindows[key]
      for (var i = 0; i < set.length; i++) merged.push(set[i])
    }
    return merged
  }

  readonly property bool scheduleEnabled:
    root.scheduleConfig && root.scheduleConfig.enabled === true

  // The window covering right now, or null. Recomputed on the tick rather than
  // bound to a clock, so nothing here re-evaluates sixty times a second.
  property var activeWindow: null
  property var nextWindow: null

  // What has already been warned about, so a warning is given once per opening
  // rather than every fifteen seconds for the two minutes before it.
  property string warnedFor: ""
  // When the wall may next take a scheduled stretch. Set to the end of the
  // stretch plus the gap, so there is always a moment of daylight between one
  // and the next.
  //
  // The daylight is the recovery path, and it is the whole reason the cap
  // exists. A mistyped window took this machine for 226 minutes in one tick,
  // from a test written to avoid exactly that. Capped stretches with a gap
  // mean a window you meant still effectively holds -- you would have to
  // intervene deliberately every stretch to get out of it -- while a window
  // you did not mean costs one stretch and then hands you a chance to turn it
  // off.
  property double scheduleGapUntil: 0

  // Set while a lock this scheduler asked for is still up, so the daylight can
  // be measured from when the wall actually falls rather than from when it
  // went up.
  //
  // Arming the gap at engage time counts it down through the lock, and two
  // things then eat it. The release ceremony holds for RELEASE_MS after the
  // timer ends -- 4.6s of a gap whose floor is 5 -- leaving four tenths of a
  // second of daylight at the low end. And a machine that sleeps through a
  // lock wakes with the gap long expired, so the wall drops and takes itself
  // straight back with none at all. Both were found by review; neither is
  // reachable once the gap starts when the lock ends.
  property bool scheduleLockActive: false

  onHoldingChanged: {
    if (root.holding || !root.scheduleLockActive) return
    root.scheduleLockActive = false
    root.scheduleGapUntil = Date.now() + root.scheduleConfig.gapSeconds * 1000
    logEvent("schedule: " + root.scheduleConfig.gapSeconds + "s of daylight")
  }

  function scheduleKeyFor(entry) {
    return entry ? (entry.label + "@" + Math.floor(Date.now() / 60000 / 1440)) : ""
  }

  function scheduleTick() {
    if (!root.scheduleEnabled) {
      root.activeWindow = null
      root.nextWindow = null
      return
    }
    var now = new Date()
    var windows = root.effectiveWindows
    // Kept for the bar and the IPC readout; the decision below does not use
    // them, so what is shown and what is done cannot drift apart.
    root.activeWindow = Model.activeWindowAt(windows, now)
    root.nextWindow = Model.nextWindowAt(windows, now)

    // Every branch of this lives in Model.scheduleDecision, where it can be
    // tested. This function's only job is to carry out what it says.
    var call = Model.scheduleDecision(root.scheduleConfig, windows, now,
                                      root.holding, root.scheduleGapUntil)

    if (call.action === "lock") {
      // The decision hands back a gap measured from now; it is not used. The
      // gap is armed when the wall comes down, in onHoldingChanged.
      root.scheduleLockActive = true
      logEvent("schedule: " + call.label + " -- locking for " + call.minutes
               + " min of "
               + (root.activeWindow ? root.activeWindow.endsInMinutes : "?")
               + " remaining")
      root.engage(call.minutes * 60)
      return
    }

    if (call.action === "warn") {
      // Once per approach rather than every fifteen seconds through the whole
      // warning period.
      if (root.warnedFor === call.label) return
      root.warnedFor = call.label
      var mins = Math.max(1, call.inMinutes)
      logEvent("schedule: warning for " + call.label)
      warnProc.command = ["notify-send", "-u", "critical", "-a", "Blackwall",
                          "The Blackwall closes in " + mins
                          + (mins === 1 ? " minute" : " minutes"),
                          call.label + " -- save what you are doing."]
      warnProc.running = true
      return
    }

    // Nothing to do. Forget the warning once no window is near, so the next
    // approach warns again.
    //
    // The gap is deliberately NOT cleared here. Clearing it whenever no window
    // is open let a provider withdraw its window and push it back to wipe the
    // daylight and lock continuously -- and the same happens by accident with
    // two windows that abut. Daylight is daylight: it expires on its own, and
    // the most it can delay a genuine window is gapSeconds.
    if (!root.activeWindow) {
      if (!root.nextWindow
          || root.nextWindow.inMinutes * 60 > root.scheduleConfig.warnSeconds)
        root.warnedFor = ""
    }
  }

  Process { id: warnProc }

  Timer {
    // Fifteen seconds is fine: the warning is measured in minutes and a window
    // that opens fifteen seconds late is a window that opened.
    interval: 15000
    repeat: true
    running: root.scheduleEnabled
    triggeredOnStart: true
    onTriggered: root.scheduleTick()
  }
  property bool configLoaded: false

  // What a breach challenge asks to be typed. Owned by the same config file,
  // read here and never by the daemon: the daemon says only that a challenge is
  // due, never what it should say.
  property string challengePhrase: Model.DEFAULT_CHALLENGE_PHRASE

  // Cleared when the config path turns out to be something we refuse to touch,
  // which also stops us writing to it.
  property bool configWritable: true

  // This boot's kernel boot id, stamped into the state file so a resume can
  // tell "the shell restarted" from "the machine rebooted".
  property string bootId: ""
  property bool bootIdLoaded: false

  function logEvent(event) {
    lastEvent = String(event)
    lastEventAt = new Date().toISOString()
    console.log("blackwall " + lastEventAt + " " + lastEvent)
  }

  // ------------------------------------------------------------- engaging

  // `seconds` is clamped rather than rejected: a caller that asks for
  // something absurd gets the ceiling, not a silently ignored lock.
  function engage(seconds) {
    if (root.holding) {
      logEvent("engage-ignored: already " + (root.releasing ? "releasing" : "engaged"))
      return false
    }

    var span = Math.round(Model.clamp(Math.round(Number(seconds)), Model.MIN_SECONDS, Model.MAX_SECONDS)) * 1000
    root.now = Date.now()
    root.engagedSpanMs = span
    root.deadline = root.now + span
    persistDeadline()
    suppressCompetingLocks()
    logEvent("engaged for " + Math.round(span / 1000) + "s")
    captureThenLock()
    return true
  }

  // The desktop has to be photographed before the lock surface goes up,
  // because once it is up there is nothing else on screen to photograph.
  //
  // That puts a capture in front of the lock, so it is bounded twice over: the
  // capture is started and a watchdog armed, and whichever finishes first
  // takes the lock. A grim that fails, hangs, or is not installed costs the
  // watchdog's delay and no more, and the wall comes up with no takeover.
  // Measured at 22-31ms on this machine; the watchdog is 600.
  //
  // The lock is the product. The animation in front of it is not allowed to
  // become a way for the lock to not happen.
  property bool lockPending: false

  function captureThenLock() {
    root.takeoverSource = ""
    root.takeoverArmed = false
    root.lockPending = true

    if (!root.takeoverPossible) {
      logEvent("no runtime dir; locking without a takeover")
      lockNow(false)
      return
    }

    lockWatchdog.restart()
    // -l 0 skips PNG compression: a third of the time for a file that is
    // deleted within seconds anyway.
    captureProc.command = ["grim", "-l", "0", "-t", "png", root.takeoverPath]
    captureProc.running = true
  }

  function lockNow(withTakeover) {
    if (!root.lockPending) return
    root.lockPending = false
    lockWatchdog.stop()
    root.takeoverArmed = !!withTakeover
    root.takeoverSource = withTakeover
      ? Qt.resolvedUrl("file://" + root.takeoverPath) : ""
    takeSessionLock()
  }

  Process {
    id: captureProc
    onExited: function (code, status) {
      root.logEvent("takeover capture exit=" + code)
      root.lockNow(code === 0)
    }
  }

  Timer {
    id: lockWatchdog
    interval: 600
    repeat: false
    onTriggered: {
      root.logEvent("takeover capture timed out; locking without it")
      root.lockNow(false)
    }
  }

  // Called by the lock view when the tear has finished, and again whenever the
  // lock ends. Removing it twice is not a problem; leaving it once is.
  function discardTakeover() {
    root.takeoverSource = ""
    root.takeoverArmed = false
    if (!root.takeoverPossible) return
    discardProc.command = ["rm", "-f", root.takeoverPath]
    discardProc.running = true
  }

  Process { id: discardProc }

  // The countdown reaching zero starts the opening, it does not end the lock.
  // The state file is cleared here rather than at the end: the timer is
  // genuinely over at this point, so a crash mid-ceremony must not come back
  // as a resumed lock.
  function expire(reason) {
    if (root.deadline === 0 || root.releasing) return
    root.deadline = 0
    root.releasing = true
    root.releaseStartedAt = Date.now()
    clearDeadline()
    releaseWatchdog.restart()
    logEvent("reconnection sequence: " + (reason || "expired"))
  }

  // The only place the session is actually handed back.
  function finishRelease(reason) {
    if (!root.releasing && !sessionLock.locked) return
    discardTakeover()
    root.releasing = false
    root.releaseStartedAt = 0
    root.engagedSpanMs = 0
    reassertAttempts = 0
    audioClaims = 0
    releaseWatchdog.stop()
    sessionLock.locked = false
    restoreCompetingLocks()
    logEvent("released: " + (reason || "sequence complete"))
  }

  // A ceremony that can hang is a lock that never opens. If the progress
  // clock stalls for any reason — a stopped tick, a clock jump, a broken
  // binding — this fires anyway and hands the session back.
  Timer {
    id: releaseWatchdog
    interval: Model.RELEASE_MS + 2000
    repeat: false
    onTriggered: {
      if (!root.releasing) return
      root.logEvent("release watchdog fired")
      root.finishRelease("watchdog")
    }
  }

  function takeSessionLock() {
    if (sessionLock.locked) return
    sessionLock.locked = true
  }

  // One lock surface exists per monitor, and all of them instantiate the same
  // lock view. Exactly one gets to own the audio, or a two-monitor lock plays
  // the ambience twice, slightly out of phase.
  property int audioClaims: 0

  function claimAudio() {
    audioClaims += 1
    return audioClaims === 1
  }

  // ------------------------------------------------------- lock re-assertion
  //
  // The compositor can hand the session lock away — most plausibly to
  // omarchy.lock if something asks it to lock while we are up. Losing it
  // would put a password field in front of a Blackwall that has not expired,
  // which is exactly the escape hatch this plugin is not supposed to have.
  // So take it back, with a bounded number of attempts so a compositor that
  // genuinely refuses does not spin forever.
  property int reassertAttempts: 0
  readonly property int maxReassertAttempts: 20

  function reassert() {
    if (!root.holding) return
    if (sessionLock.locked) { reassertAttempts = 0; return }
    if (reassertAttempts >= maxReassertAttempts) {
      logEvent("reassert-gave-up after " + reassertAttempts + " attempts")
      return
    }
    reassertAttempts += 1
    logEvent("reassert attempt " + reassertAttempts)
    standDownOmarchyLock()
    sessionLock.locked = true
  }

  // omarchy.idle and omarchy.lock are sibling services with no ordering
  // guarantee against this one, so a lock resumed at startup can engage
  // before they exist. Keep retrying suppression until it takes.
  Timer {
    id: suppressRetryTimer
    interval: 500
    repeat: true
    running: root.holding && !root.suppressionSettled
    onTriggered: root.suppressCompetingLocks()
  }

  Timer {
    id: reassertTimer
    interval: 400
    repeat: false
    onTriggered: root.reassert()
  }

  // ------------------------------------------------ competing lock suppression

  property var idleService: null
  property var lockService: null
  property bool idleSuppressed: false
  // True once we have actually reached the idle service and made a decision,
  // so the retry timer below stops even when suppression turned out to be
  // unnecessary (the user was already holding the session awake).
  property bool suppressionSettled: false

  function resolveServices() {
    if (!shell || typeof shell.serviceFor !== "function") return
    idleService = shell.serviceFor("omarchy.idle")
    lockService = shell.serviceFor("omarchy.lock")
  }

  // Hold the idle cycle off while locked. Without this the idle monitor keeps
  // counting (there is no input during a lock, by design), fires at
  // `idle.lock`, and runs omarchy-system-lock on top of us.
  //
  // `persist: false` keeps this out of the stay-awake state file, so the
  // user's own stay-awake preference and its bar indicator are untouched.
  function suppressCompetingLocks() {
    resolveServices()
    standDownOmarchyLock()

    if (suppressionSettled) return
    var idle = root.idleService
    if (!idle || typeof idle.applyStayAwake !== "function") return

    suppressionSettled = true
    if (idle.stayAwake === true) return  // already held awake by the user
    idle.applyStayAwake(true, false, "blackwall")
    idleSuppressed = true
  }

  function restoreCompetingLocks() {
    suppressionSettled = false
    if (!idleSuppressed) return
    idleSuppressed = false
    var idle = root.idleService
    if (idle && typeof idle.applyStayAwake === "function")
      idle.applyStayAwake(false, false, "blackwall")
  }

  function standDownOmarchyLock() {
    var lock = root.lockService
    if (!lock || !root.holding) return
    if (lock.lockRequested === true && typeof lock.finishUnlock === "function") {
      logEvent("stood down omarchy.lock")
      lock.finishUnlock()
    }
  }

  Connections {
    target: root.lockService
    enabled: !!root.lockService && root.holding
    function onLockRequestedChanged() { root.standDownOmarchyLock() }
  }

  // ---------------------------------------------------------- persistence

  // The state file carries the boot id alongside the deadline so a resume can
  // tell a shell restart from a reboot. Older files held a bare number; those
  // are read as "boot unknown", which resumes only when persistence is on.
  function persistDeadline() {
    stateFile.write(JSON.stringify({
      version: 1,
      deadline: Math.round(root.deadline),
      bootId: root.bootId
    }) + "\n")
  }

  function clearDeadline() {
    stateFile.write(JSON.stringify({ version: 1, deadline: 0, bootId: "" }) + "\n")
  }

  // Resume needs three inputs — the state file, the config, and this boot's
  // id — and they land in whatever order the processes finish. Each one calls
  // in here; the last to arrive does the work.
  property bool stateRead: false
  property string stateRaw: ""

  function noteState(raw) {
    stateRaw = String(raw || "")
    stateRead = true
    maybeResume()
  }

  function maybeResume() {
    if (stateLoaded) return
    if (!stateRead || !configLoaded || !bootIdLoaded) return
    stateLoaded = true
    resumeFromState(stateRaw)
  }

  // What makes the wall hold across a shell restart or crash. A deadline that
  // has already passed is cleared instead.
  function resumeFromState(raw) {
    var saved = Model.parseState(raw)
    if (saved.deadline <= 0) return

    root.now = Date.now()
    if (saved.deadline <= root.now) {
      logEvent("stale deadline discarded")
      clearDeadline()
      return
    }

    var remaining = Math.round((saved.deadline - root.now) / 1000)
    var sameBoot = saved.bootId !== "" && saved.bootId === root.bootId

    // A reboot only clears the lock when persistence is off. Inside one boot
    // the lock always comes back, however the shell went down.
    if (!sameBoot && !root.persistAcrossReboot) {
      logEvent("reboot cleared a session-only lock, discarding " + remaining + "s")
      clearDeadline()
      return
    }

    root.deadline = saved.deadline
    root.engagedSpanMs = saved.deadline - root.now
    // The file still names the previous boot; restamp it as ours.
    persistDeadline()
    suppressCompetingLocks()
    logEvent("resumed with " + remaining + "s left (" + (sameBoot ? "same boot" : "across reboot") + ")")
    takeSessionLock()
  }

  // ---- the count, written down ---------------------------------------------
  //
  // The stretch used to live only in this object, which meant the shell going
  // down took it with it -- and the shell goes down on a theme change, on any
  // edit to any plugin, and on a crash. Each one handed out a fresh three
  // hours. That made the one thing deliberately not a choice into a choice,
  // and a trivially easy one, so it is on disk now.
  //
  // Kept apart from the deadline file rather than folded into it. They answer
  // different questions, are written on completely different rhythms, and a
  // corrupt one of them should not cost the other: a lock still owed is the
  // more serious of the two and must not be lost because a counter would not
  // parse.
  property int persistedActiveMinute: -1

  // The one thing that genuinely pays off the stretch: a break that was taken.
  // Not a restart, not the toggle -- those are both judged as time away and go
  // through applySavedCount. This is the only caller, and it is the break.
  //
  // It also stands down any restore still in flight. Without that, a stretch
  // read back off disk a moment later could resurrect the one this break has
  // just paid off -- the two land in whichever order the processes finish, and
  // only one of those orders is right.
  function resetActivityCount() {
    root.activityState = ({ activeMs: 0, idleMs: 0 })
    root.activityLastTick = 0
    root.activityRestored = true
    root.persistActivity()
  }

  // The record, as last written. Held in memory as well as on disk because
  // switching the reminders back on asks it the same question the startup
  // restore does, and it must not have to go back to the file to do it.
  property var activitySaved: ({ activeMs: 0, idleMs: 0, at: 0 })

  function persistActivity() {
    var stamp = Date.now()
    root.persistedActiveMinute = root.activeMinutes
    root.activitySaved = ({
      activeMs: Math.round(Number(root.activityState.activeMs) || 0),
      idleMs: Math.round(Number(root.activityState.idleMs) || 0),
      at: stamp
    })
    activityFile.write(JSON.stringify({
      version: 1,
      activeMs: root.activitySaved.activeMs,
      idleMs: root.activitySaved.idleMs,
      at: stamp
    }) + "\n")
  }

  // Pick the count back up from the record, judging the time since it was
  // written as time away.
  //
  // Shared by the startup restore and by switching the reminders back on,
  // because they are the same question asked of the same record: this count
  // was true at that moment, how much of it is still owed now. `what` only
  // names the gap in the log.
  function applySavedCount(what) {
    // An explicit resume outranks a restore still in flight. They land in
    // whichever order the processes finish, and only one of those orders is
    // right.
    root.activityRestored = true

    var back = Model.restoreActivity(root.activityConfig, root.activitySaved,
                                     Date.now())
    root.activityLastTick = 0

    if (!back.kept) {
      // Either nothing was recorded, or the gap was long enough that it was
      // the break. Only worth a line when there was something to lose; a
      // first run is not an event.
      if (Number(root.activitySaved.activeMs) > 0)
        logEvent("activity: " + Math.round(back.gapMs / 60000)
                 + " min away across the " + what + " -- the stretch reset")
      root.activityState = ({ activeMs: 0, idleMs: 0 })
      root.persistActivity()
      return
    }

    root.activityState = ({ activeMs: back.activeMs, idleMs: back.idleMs })
    // The count did not move; the record of it is still current. Restamping
    // the minute here stops the next tick writing the same figure back out.
    root.persistedActiveMinute = root.activeMinutes
    logEvent("activity: resumed at " + root.activeMinutes + " min at the machine")
  }

  // Two inputs, landing in whichever order they finish: the file and the
  // config the gap is judged against. Whichever is last does the work. Same
  // shape as the deadline resume, and for the same reason.
  property bool activityRead: false
  property bool activityRestored: false
  property string activityRaw: ""

  function noteActivityState(raw) {
    root.activityRaw = String(raw || "")
    root.activityRead = true
    root.maybeRestoreActivity()
  }

  function maybeRestoreActivity() {
    if (root.activityRestored) return
    if (!root.activityRead || !root.configLoaded) return

    // Read whether or not the reminders are on. Switching them on later asks
    // this same record the same question, and a stretch must not be lost
    // because the shell happened to restart while they were off -- off, then
    // restart, then on would otherwise be a two-step way to a fresh three
    // hours, which is the hole again with an extra step in it.
    root.activitySaved = Model.parseActivityState(root.activityRaw)

    if (root.activityConfig.enabled !== true) {
      root.activityRestored = true
      return
    }
    root.applySavedCount("restart")
  }

  // Blackwall's own, in the same 0700 directory as the deadline, under the
  // same guard. Symlinks refused; a write may take the name back, because a
  // counter that quietly stopped persisting would be the whole hole again.
  GuardedFile {
    id: activityFile
    path: root.stateDirReady ? root.activityPath : ""
    guardScript: root.guardScript
    allowSymlink: false
    reclaim: true

    onReadyChanged: if (ready) read()
    onTextReady: function(text) { root.noteActivityState(text) }
    onAbsent: root.noteActivityState("")
    // A refusal resolves the gate as "nothing saved" rather than stalling it.
    // The cost of that is one lost stretch; the cost of stalling is a count
    // that never starts.
    onRefused: function(reason) {
      root.logEvent("activity state unreadable, ignoring it: " + reason)
      root.noteActivityState("")
    }
    onWriteRefused: function(reason) {
      root.logEvent("activity state not written: " + reason)
    }
  }

  property bool stateDirReady: false

  Process {
    id: stateDirProc
    // 0700 on the leaf. The guard refuses any file whose parent directory
    // other users can write to, and this is the directory that decides
    // whether anything can be planted at the deadline path in the first place.
    command: ["bash", "-c", 'mkdir -p -- "$1" && chmod 700 -- "$1"',
              "blackwall-state-dir", root.stateDir]
    onExited: root.stateDirReady = true
  }

  // Path stays empty until mkdir has returned, so the first read is not spent
  // on a directory that does not exist yet — that would burn the one-shot
  // resume before the real read.
  //
  // Blackwall's own private file, in a directory nothing else uses. Symlinks
  // are refused outright. A write may take the name back from a planted entry,
  // because refusing forever would quietly stop the deadline persisting, and
  // that would turn restarting the shell into a way out of a lock.
  GuardedFile {
    id: stateFile
    path: root.stateDirReady ? root.statePath : ""
    guardScript: root.guardScript
    allowSymlink: false
    reclaim: true

    onReadyChanged: if (ready) read()
    onTextReady: function(text) { root.noteState(text) }
    onAbsent: root.noteState("")
    // Never stalls the resume: a refusal resolves the gate as "no saved lock",
    // exactly as an empty file would.
    onRefused: function(reason) {
      root.logEvent("state unreadable, ignoring it: " + reason)
      root.noteState("")
    }
    onWriteRefused: function(reason) { root.logEvent("state not written: " + reason) }
  }

  Process {
    id: bootIdProc
    command: ["cat", "/proc/sys/kernel/random/boot_id"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        root.bootId = String(text || "").trim()
        root.bootIdLoaded = true
        root.maybeResume()
      }
    }
    // No boot id (an odd kernel, a container) degrades to "boot unknown",
    // which is the conservative branch — it never traps a lock on.
    onExited: if (!root.bootIdLoaded) { root.bootIdLoaded = true; root.maybeResume() }
  }

  // Three places, in order: what the operator configured, whatever they
  // dropped in sounds/, and the ambience shipped with the plugin.
  //
  // The last of those is new. The lock used to come up silent unless you found
  // your own audio, because the track it was built against was not ours to
  // distribute. audio/ambience.mp3 is synthesised by tools/make-ambience.py
  // and is, so there is now a voice out of the box -- still overridden by
  // anything of your own, which is the order that matters.
  readonly property string shippedAmbience: pluginDir + "/audio/ambience.mp3"

  readonly property string soundProbeScript:
    'configured="$1"; dir="$2"; shipped="$3"; ' +
    'if [[ -n $configured ]]; then ' +
      'case $configured in "~/"*) configured="$HOME/${configured:2}";; esac; ' +
      'if [[ -f $configured && -r $configured ]]; then printf %s "$configured"; exit 0; fi; ' +
    'fi; ' +
    'shopt -s nullglob nocaseglob; ' +
    'for f in "$dir"/*.mp3 "$dir"/*.ogg "$dir"/*.opus "$dir"/*.flac "$dir"/*.wav "$dir"/*.m4a; do ' +
      'if [[ -f $f && -r $f ]]; then printf %s "$f"; exit 0; fi; ' +
    'done; ' +
    'if [[ -f $shipped && -r $shipped ]]; then printf %s "$shipped"; fi'

  function refreshSound() {
    if (soundProbe.running) return
    soundProbe.command = ["bash", "-c", root.soundProbeScript,
                          "blackwall-sound-probe", root.configuredSoundPath,
                          root.soundDir, root.shippedAmbience]
    soundProbe.running = true
  }

  onConfiguredSoundPathChanged: refreshSound()

  Process {
    id: soundProbe
    stdout: StdioCollector {
      id: soundProbeOut
      waitForEnd: true
    }
    onExited: {
      var next = String(soundProbeOut.text || "").trim()
      if (next === root.resolvedSoundPath) return
      root.resolvedSoundPath = next
      root.logEvent(next === "" ? "no ambience found" : "ambience: " + next)
    }
  }

  // ------------------------------------------------------------ user config

  function applyConfig(raw) {
    var parsed = Model.parseConfig(raw)
    root.persistAcrossReboot = parsed.persistAcrossReboot
    root.configuredSoundPath = parsed.soundPath
    root.soundEnabled = parsed.soundEnabled
    root.challengePhrase = parsed.challengePhrase
    root.agents = parsed.agents
    root.scheduleConfig = parsed.schedule
    root.activityConfig = parsed.activity
    root.configLoaded = true
    root.maybeRestoreActivity()
    root.maybeResume()
    root.refreshSound()
  }

  // Write the defaults out on first run so the file is there to be read and
  // hand-edited, rather than only appearing once the toggle is touched.
  function seedConfig() {
    applyConfig("")
    writeConfig()
  }

  // Every setting, every time. Writing only the field that changed would drop
  // the others — flipping the toggle used to erase soundPath.
  function writeConfig() {
    if (!root.configWritable) return
    configFile.write(JSON.stringify({
      version: 1,
      persistAcrossReboot: root.persistAcrossReboot,
      soundPath: root.configuredSoundPath,
      soundEnabled: root.soundEnabled,
      challengePhrase: root.challengePhrase,
      // Not read by this file, and written by it regardless. `agents` was
      // added to the parser and not to here, which meant the next save of any
      // other setting silently deleted whoever was on file -- the exact
      // failure the note above describes, made again.
      agents: root.agents,
      // Same reasoning as agents: a key this file does not carry is a key it
      // deletes. Only the operator's own windows are written -- what a
      // provider pushed is theirs to push again.
      schedule: {
        enabled: root.scheduleConfig.enabled,
        warnSeconds: root.scheduleConfig.warnSeconds,
        maxLockMinutes: root.scheduleConfig.maxLockMinutes,
        gapSeconds: root.scheduleConfig.gapSeconds,
        windows: root.scheduleConfig.windows
      },
      activity: root.activityConfig
    }, null, 2) + "\n")
  }

  // A setting still takes effect in memory when the config path is one we
  // refuse to touch, but saying "true" and silently not saving it would be a
  // lie the user only finds out about after a reboot.
  function notPersistedSuffix() {
    return root.configWritable ? "" : " (in memory only — config path refused)"
  }

  function setPersistAcrossReboot(value) {
    var next = !!value
    if (next === root.persistAcrossReboot && root.configLoaded) return next
    root.persistAcrossReboot = next
    writeConfig()
    logEvent("persistAcrossReboot=" + next)
    return next
  }

  function setSoundEnabled(value) {
    var next = !!value
    if (next === root.soundEnabled && root.configLoaded) return next
    root.soundEnabled = next
    writeConfig()
    logEvent("soundEnabled=" + next)
    return next
  }

  function setSoundPath(value) {
    root.configuredSoundPath = String(value || "").trim()
    writeConfig()
    logEvent("soundPath=" + (root.configuredSoundPath || "(auto)"))
    return root.configuredSoundPath
  }

  // The user's own file, so the rules are the opposite way round: symlinks are
  // allowed, because keeping a config in a dotfiles repo and linking it into
  // place is a normal thing to do — the link still has to land inside $HOME and
  // the target still faces every other check. Nothing is ever reclaimed here;
  // this file belongs to the user, not to Blackwall.
  //
  // notifyChanges keeps hand-edits taking effect without a restart.
  GuardedFile {
    id: configFile
    path: root.configPath
    guardScript: root.guardScript
    allowSymlink: true
    reclaim: false
    notifyChanges: true

    Component.onCompleted: read()
    onChangedExternally: read()
    onTextReady: function(text) { root.applyConfig(text) }
    onAbsent: root.seedConfig()
    onRefused: function(reason) {
      // A path we will not read is a path we will not write. Run on defaults
      // in memory and leave whatever is sitting there completely alone.
      root.configWritable = false
      root.logEvent("config unreadable, using defaults: " + reason)
      root.applyConfig("")
    }
    onWriteRefused: function(reason) { root.logEvent("config not written: " + reason) }
  }

  // ------------------------------------------------------------- countdown

  // Driven off the wall clock rather than accumulated ticks, so a missed or
  // late timer callback cannot stretch the lock.
  Timer {
    id: tick
    // 5Hz is plenty for a countdown that only ever renders whole seconds, but
    // the release sequence derives every one of its curves from this same
    // clock — at 200ms the shatter steps visibly. One clock, sped up while the
    // ceremony runs, keeps the visuals smooth without letting a second timer
    // drift away from the authoritative one.
    interval: root.releasing ? 16 : 200
    repeat: true
    running: true
    onTriggered: {
      root.now = Date.now()
      if (root.deadline > 0 && root.now >= root.deadline) root.expire("expired")
      else if (root.releasing && root.releaseProgress >= 1) root.finishRelease("sequence complete")
    }
  }

  // ------------------------------------------------------------ lock surface

  WlSessionLock {
    id: sessionLock

    locked: false

    onLockStateChanged: {
      root.logEvent("session-locked=" + locked)
      if (locked) {
        root.reassertAttempts = 0
        return
      }
      // Surfaces are gone, so the next set has to claim the audio afresh —
      // otherwise a re-assert would rebuild them with no owner and play
      // nothing at all.
      root.audioClaims = 0

      // Lost the lock with the wall still up — take it back.
      if (root.holding) reassertTimer.restart()
    }

    WlSessionLockSurface {
      color: "#000000"

      BlackwallLockView {
        anchors.fill: parent
        takeoverSource: root.takeoverSource
        takeoverArmed: root.takeoverArmed
        // Every surface runs its own tear -- one per monitor, all from the
        // same still -- and the first to finish is the one that clears it.
        onTakeoverFinished: root.discardTakeover()
        remainingMs: root.remainingMs
        totalMs: root.engagedSpanMs
        active: root.holding
        releasing: root.releasing
        releaseProgress: root.releaseProgress
        soundEnabled: root.soundEnabled
        soundSource: root.soundEnabled ? root.soundUrl : ""

        // Assigned, not bound. claimAudio() reads audioClaims while it
        // increments it, so as a binding QML captures audioClaims as a
        // dependency and the mutation re-triggers the binding forever.
        // One imperative claim at construction is what we actually want.
        Component.onCompleted: audioLead = root.claimAudio()
      }
    }
  }

  // ------------------------------------------------------------------- IPC
  //
  // `engage` only. There is no release method by design; adding one would be
  // the emergency unlock this plugin exists to not have.
  IpcHandler {
    target: "blackwall"

    function engage(seconds: string): string {
      var value = Number(String(seconds || "").trim())
      if (!isFinite(value) || value <= 0) return "usage: blackwall engage <seconds>"
      return root.engage(value) ? "engaged" : "already engaged"
    }

    function status(): string {
      return JSON.stringify({
        engaged: root.engaged,
        releasing: root.releasing,
        releaseProgress: Math.round(root.releaseProgress * 100) / 100,
        remainingSeconds: Math.ceil(root.remainingMs / 1000),
        deadline: root.deadline,
        persistAcrossReboot: root.persistAcrossReboot,
        soundAvailable: root.soundAvailable,
        soundPath: root.resolvedSoundPath,
        soundConfigured: root.configuredSoundPath,
        configWritable: root.configWritable,
        idleSuppressed: root.idleSuppressed,
        lastEvent: root.lastEvent,
        lastEventAt: root.lastEventAt
      })
    }

    function remaining(): string {
      return Model.formatRemaining(root.remainingMs)
    }

    // Reading and writing the toggle is fine while locked — it decides what
    // happens at the *next* boot, so it is not an unlock path.
    // Report and set where the ambience comes from. Handy for checking a
    // dropped-in file was actually picked up.
    function sound(): string {
      if (root.resolvedSoundPath !== "") return root.resolvedSoundPath
      return "(none — drop an audio file in " + root.soundDir + ")"
    }

    function setSound(path: string): string {
      var next = root.setSoundPath(path)
      return (next === "" ? "(auto)" : next) + root.notPersistedSuffix()
    }

    function persist(): string {
      return root.persistAcrossReboot ? "true" : "false"
    }

    function schedule(): string {
      if (!root.scheduleEnabled) return "off"
      var parts = []
      parts.push(root.effectiveWindows.length + " window(s)")
      if (root.activeWindow)
        parts.push("NOW: " + root.activeWindow.label + ", "
                   + root.activeWindow.endsInMinutes + " min left"
                   + " (stretches of " + root.scheduleConfig.maxLockMinutes + ")")
      else if (root.nextWindow)
        parts.push("next: " + root.nextWindow.label + " in "
                   + root.nextWindow.inMinutes + " min")
      return parts.join("  |  ")
    }

    // How another plugin hands windows in: one window per call, under the
    // provider's own name, held in memory only.
    //
    // It is not JSON, and that is not a style choice. Quickshell's IPC parses
    // its arguments -- `[a,b]` is read as an argument LIST and split on the
    // commas, and a lone `[{...}]` arrives with the brackets eaten. Passing a
    // JSON array through this channel is not possible, so the shape that
    // survives it is plain scalars: no brackets, no commas. `days` is
    // plus-separated for the same reason.
    //
    // A provider recomputes on its own schedule, calls clearWindows, then adds
    // what it has. It can only ADD windows -- it cannot touch the operator's
    // own, and it cannot shorten or cancel a lock that is already up.
    function provideWindow(source: string, label: string, start: string,
                           end: string, days: string): string {
      var name = String(source || "").trim()
      if (name === "")
        return "usage: blackwall provideWindow <source> <label> <HH:MM> <HH:MM> <all|mon+tue+...>"

      // Every argument is required -- Quickshell's IPC has no optional
      // parameters -- so "all" is the word for every day rather than an
      // omitted argument or an empty string a shell would swallow.
      var spec = String(days || "").trim().toLowerCase()
      var dayList = (spec === "" || spec === "all" || spec === "*")
        ? []
        : spec.split("+").filter(function (d) { return String(d).trim() !== "" })
      var cleaned = Model.parseSchedule({
        enabled: true,
        windows: [{ label: String(label || name), start: start, end: end,
                    days: dayList }]
      }).windows
      if (cleaned.length === 0) return "not a window: check the times are HH:MM"

      var next = ({})
      for (var key in root.providedWindows)
        if (root.providedWindows.hasOwnProperty(key)) next[key] = root.providedWindows[key]
      next[name] = (next[name] || []).concat(cleaned)
      root.providedWindows = next
      root.scheduleTick()
      logEvent("schedule: " + name + " added " + cleaned[0].label)
      return String(next[name].length)
    }

    function clearWindows(source: string): string {
      var name = String(source || "").trim()
      if (name === "") return "usage: blackwall clearWindows <source>"
      var next = ({})
      for (var key in root.providedWindows)
        if (root.providedWindows.hasOwnProperty(key) && key !== name)
          next[key] = root.providedWindows[key]
      root.providedWindows = next
      root.scheduleTick()
      logEvent("schedule: " + name + " cleared")
      return "cleared"
    }

    // Fire the demand now, for seeing what it does without working three
    // hours first. Safe to expose on a 0666 socket: the only thing it can do
    // is cause a break. There is no argument that shortens one, and no way to
    // call it that avoids one.
    // The same window, with nothing behind it. Shows what a demand looks like
    // without closing anything or taking the screen.
    function previewBreak(): string {
      if (root.holding) return "already behind the wall"
      breakDemand.preview = true
      breakDemand.activeMinutes = root.activityConfig.breakAfterMinutes
      breakDemand.graceSeconds = root.activityConfig.demandGraceSeconds
      breakDemand.demanding = true
      return "preview"
    }

    function demandBreak(): string {
      if (root.holding) return "already behind the wall"
      root.activityState = ({ activeMs: root.activityConfig.breakAfterMinutes * 60000,
                              idleMs: 0 })
      root.activityLastTick = 0
      root.activityTick()
      return "demanded"
    }

    function breaks(): string {
      if (root.activityConfig.enabled !== true) return "off"
      return "on  |  " + root.activeMinutes + " min at the machine"
             + (root.awayFromPost
                ? "  |  away"
                : (idleWatch.isIdle ? "  |  counting (something is playing)" : ""))
    }

    function setBreaks(value: string): string {
      var text = String(value || "").trim().toLowerCase()
      if (text !== "on" && text !== "off")
        return "usage: blackwall setBreaks <on|off>"
      // Safe while locked, like the others: it changes whether a reminder is
      // offered, not whether the wall is there.
      return root.setActivityEnabled(text === "on") ? "on" : "off"
    }

    function soundOn(): string {
      return root.soundEnabled ? "on" : "off"
    }

    function setSoundOn(value: string): string {
      var text = String(value || "").trim().toLowerCase()
      if (text !== "on" && text !== "off")
        return "usage: blackwall setSoundOn <on|off>"
      // Safe while locked, like setPersist: it changes what the wall sounds
      // like, not whether it is there.
      return root.setSoundEnabled(text === "on") ? "on" : "off"
    }

    function setPersist(value: string): string {
      var text = String(value || "").trim().toLowerCase()
      if (text !== "true" && text !== "false")
        return "usage: blackwall setPersist <true|false>"
      return (root.setPersistAcrossReboot(text === "true") ? "true" : "false")
             + root.notPersistedSuffix()
    }

    // Rung one. The daemon has recorded a breach and is asking for it to be
    // answered. The token proves the call came from the daemon rather than from
    // anything else that can reach its socket, and it is handed straight back
    // with the answer.
    function challenge(reason: string, token: string): string {
      var text = String(token || "").trim()
      if (text === "") return "usage: blackwall challenge <reason> <token>"
      root.showChallenge(String(reason || "the wall was weakened"), text)
      return "challenge shown"
    }

    // Rung two. Engage the wall for a breach that has already had its question
    // asked, or that arrived past the point of asking.
    function lock(seconds: string, token: string): string {
      var value = Number(String(seconds || "").trim())
      if (!isFinite(value) || value <= 0)
        return "usage: blackwall lock <seconds> <token>"
      challengeView.open = false
      return root.engage(value) ? "locked" : "already engaged"
    }
  }

  // --------------------------------------------------------------- the ladder

  function showChallenge(reason, token) {
    challengeView.reason = String(reason || "")
    challengeView.phrase = root.challengePhrase
    challengeView.token = String(token || "")
    challengeView.open = true
    logEvent("challenge: " + reason)
  }

  // Answering is the only thing that clears the count. Dismissing is not, and
  // that is deliberate: the breach stays standing, so the next weakening is the
  // second inside the window and lands on the lock instead of another question.
  function acknowledge(token) {
    var text = String(token || "").trim()
    if (text === "") return
    ackProc.command = ["netwatchctl", "ack", text]
    ackProc.running = true
  }

  ChallengeView {
    id: challengeView

    // The same ambience the lock plays, from the same resolution: an explicit
    // soundPath, else whatever is in sounds/, else silence.
    soundSource: root.soundEnabled ? root.soundUrl : ""

    onAnswered: function (token) {
      challengeView.open = false
      root.acknowledge(token)
      logEvent("challenge answered")
    }

    onDismissed: {
      challengeView.open = false
      logEvent("challenge dismissed, breach still standing")
    }
  }

  Process {
    id: ackProc
    stderr: StdioCollector { id: ackErr; waitForEnd: true }
    onExited: function (code, status) {
      if (code !== 0)
        root.logEvent("ack refused: " + (String(ackErr.text || "").trim() || code))
    }
  }

  Component.onCompleted: {
    logEvent("service-ready")
    resolveServices()
    stateDirProc.running = true
    bootIdProc.running = true
    refreshSound()
  }
}
