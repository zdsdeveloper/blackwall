import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
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
  readonly property string configPath: home + "/.config/omarchy/zds.blackwall.json"
  readonly property string soundDir: home + "/.config/omarchy/plugins/zds.blackwall/sounds"

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
  property bool configLoaded: false

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
    takeSessionLock()
    return true
  }

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

  readonly property string soundProbeScript:
    'configured="$1"; dir="$2"; ' +
    'if [[ -n $configured ]]; then ' +
      'case $configured in "~/"*) configured="$HOME/${configured:2}";; esac; ' +
      'if [[ -f $configured && -r $configured ]]; then printf %s "$configured"; exit 0; fi; ' +
    'fi; ' +
    'shopt -s nullglob nocaseglob; ' +
    'for f in "$dir"/*.mp3 "$dir"/*.ogg "$dir"/*.opus "$dir"/*.flac "$dir"/*.wav "$dir"/*.m4a; do ' +
      'if [[ -f $f && -r $f ]]; then printf %s "$f"; exit 0; fi; ' +
    'done'

  function refreshSound() {
    if (soundProbe.running) return
    soundProbe.command = ["bash", "-c", root.soundProbeScript,
                          "blackwall-sound-probe", root.configuredSoundPath, root.soundDir]
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
    root.configLoaded = true
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
      soundPath: root.configuredSoundPath
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
        remainingMs: root.remainingMs
        totalMs: root.engagedSpanMs
        active: root.holding
        releasing: root.releasing
        releaseProgress: root.releaseProgress
        soundSource: root.soundUrl

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

    function setPersist(value: string): string {
      var text = String(value || "").trim().toLowerCase()
      if (text !== "true" && text !== "false")
        return "usage: blackwall setPersist <true|false>"
      return (root.setPersistAcrossReboot(text === "true") ? "true" : "false")
             + root.notPersistedSuffix()
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
