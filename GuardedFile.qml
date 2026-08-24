import QtQuick
import Quickshell
import Quickshell.Io

// One file, reached only through bin/blackwall-file-guard.
//
// Qt's FileView is not usable for either of Blackwall's files. It has no size
// ceiling, so a read lands entirely in the shell's heap; it has no type check,
// so a FIFO left at the path blocks the open; and its atomic write resolves a
// symlink and writes through to whatever is on the other end. All three are
// reachable at paths that are entirely predictable.
//
// FileView still appears below, but with blockAllReads set it never opens the
// file at all. It is here purely as a change notifier, so that hand-edits to
// the config keep taking effect without a restart.
Item {
  id: guard

  property string path: ""
  property string guardScript: ""
  property int maxBytes: 64 * 1024

  // Only the user's own config opts into symlinks — people keep configs in a
  // dotfiles repo and link them into place. Only Blackwall's private deadline
  // file opts into reclaim. See the guard script for what each one relaxes.
  property bool allowSymlink: false
  property bool reclaim: false
  property bool notifyChanges: false

  // A guard run is a local exec against a file of at most a few hundred bytes.
  // If one has not come back by now it is wedged on something unanticipated,
  // and nothing in the service may wait on it forever — least of all the
  // startup resume, which decides whether a lock is still owed.
  property int timeoutMs: 5000

  // Exactly one of these three fires for every read(), always.
  signal textReady(string text)
  signal absent()
  signal refused(string reason)

  // Kept separate from refused(): a rejected write says nothing about the
  // settings already in memory, and must not be mistaken for a failed read.
  signal writeRefused(string reason)

  signal changedExternally()

  readonly property bool ready: guard.path !== "" && guard.guardScript !== ""

  function argv(mode) {
    return ["python3", guard.guardScript, mode, guard.path,
            String(guard.maxBytes),
            guard.allowSymlink ? "1" : "0",
            guard.reclaim ? "1" : "0"]
  }

  // -------------------------------------------------------------------- read

  property bool readQueued: false
  property bool readTimedOut: false

  function read() {
    if (!guard.ready) return
    if (readProc.running) { guard.readQueued = true; return }
    guard.readQueued = false
    guard.readTimedOut = false
    readProc.command = guard.argv("read")
    readProc.running = true
    readWatchdog.restart()
  }

  Process {
    id: readProc
    stdout: StdioCollector { id: readOut; waitForEnd: true }
    stderr: StdioCollector { id: readErr; waitForEnd: true }
    onExited: function(code, status) {
      readWatchdog.stop()
      if (guard.readQueued) { guard.read(); return }

      if (guard.readTimedOut) guard.refused("timed out after " + guard.timeoutMs + "ms")
      else if (code === 0) guard.textReady(String(readOut.text || ""))
      else if (code === 10) guard.absent()
      else guard.refused(String(readErr.text || "").trim() || ("guard exited " + code))
    }
  }

  Timer {
    id: readWatchdog
    interval: guard.timeoutMs
    repeat: false
    onTriggered: {
      if (!readProc.running) return
      guard.readTimedOut = true
      readProc.signal(9)
    }
  }

  // ------------------------------------------------------------------- write
  //
  // Writes are whole-document and last-write-wins, so a write arriving while
  // one is in flight replaces any other queued one rather than stacking up.
  // engage() persisting a deadline and expire() clearing it can land in the
  // same frame, and the later of the two is the one that must survive.

  property string queuedWrite: ""
  property bool hasQueuedWrite: false
  property bool writeTimedOut: false

  function write(text) {
    if (!guard.ready) return
    if (writeProc.running) {
      guard.queuedWrite = String(text)
      guard.hasQueuedWrite = true
      return
    }
    guard.startWrite(String(text))
  }

  function startWrite(text) {
    guard.writeTimedOut = false
    writeProc.payload = text
    writeProc.stdinEnabled = true
    writeProc.command = guard.argv("write")
    writeProc.running = true
    writeWatchdog.restart()
  }

  Process {
    id: writeProc
    stdinEnabled: true
    stderr: StdioCollector { id: writeErr; waitForEnd: true }

    property string payload: ""

    // The payload cannot be handed over until the child is actually up — a
    // write issued in the same pass as `running = true` is dropped on the
    // floor. processId turning positive is that moment.
    onProcessIdChanged: {
      if (processId <= 0 || payload === "") return
      write(payload)
      payload = ""
      // Closing stdin is what gives the guard its EOF; it cannot happen until
      // the write above has been flushed.
      Qt.callLater(function() { writeProc.stdinEnabled = false })
    }

    onExited: function(code, status) {
      writeWatchdog.stop()
      if (guard.writeTimedOut)
        guard.writeRefused("timed out after " + guard.timeoutMs + "ms")
      else if (code !== 0)
        guard.writeRefused(String(writeErr.text || "").trim() || ("guard exited " + code))

      if (guard.hasQueuedWrite) {
        guard.hasQueuedWrite = false
        var next = guard.queuedWrite
        guard.queuedWrite = ""
        guard.startWrite(next)
      }
    }
  }

  Timer {
    id: writeWatchdog
    interval: guard.timeoutMs
    repeat: false
    onTriggered: {
      if (!writeProc.running) return
      guard.writeTimedOut = true
      writeProc.signal(9)
    }
  }

  // ---------------------------------------------------------------- notifier

  // blockAllReads means this never opens the file; it only watches the name.
  FileView {
    path: guard.notifyChanges && guard.ready ? guard.path : ""
    blockAllReads: true
    watchChanges: true
    printErrors: false
    onFileChanged: guard.changedExternally()
  }
}
