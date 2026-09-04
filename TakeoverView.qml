pragma ComponentBehavior: Bound

import QtQuick
import QtMultimedia

// The desktop, being taken.
//
// Sits over the lock surface holding a still of the session captured the
// instant before it locked, and tears a hole in it that widens until there is
// nothing left. What shows through the hole is the lock surface itself — the
// shader writes alpha zero inside the tear rather than painting a void — so it
// reads as the wall coming through the screen instead of a picture of a wall
// fading in over one.
//
// It has to be a still. Once a session lock surface is up the compositor
// presents nothing else, so there is no live desktop behind this to reveal.
//
// Every failure here ends the same way: `finished` fires and the lock view is
// simply there, with no takeover. A decoration must never be able to hold up
// the thing it decorates.
Item {
  id: root

  // file:// URL of the capture, or "" for none.
  property url source: ""
  property bool running: false
  property int durationMs: 2400

  // Exactly one lock surface may play it. Every monitor instantiates this, and
  // two of them firing the same sting a frame apart sounds like a fault rather
  // than an effect -- the same reason the lock's ambience is claimed rather
  // than simply played.
  property bool audioLead: false
  property real audioVolume: 0.55

  property real progress: 0

  // Its own clock, for the noise the tear's edge drifts on. A running
  // animation pins the render loop to the refresh rate, which everywhere else
  // in this plugin is a thing to avoid -- here it runs for two and a half
  // seconds while the screen is being eaten, and stops.
  property real clock: 0

  NumberAnimation on clock {
    running: root.running && !root.failed
    from: 0
    to: 60
    duration: 60000
    loops: Animation.Infinite
  }

  signal finished()

  readonly property bool failed:
    shot.status === Image.Error || String(root.source) === ""
  readonly property bool ready: shot.status === Image.Ready

  function begin() {
    // Idempotent. Beginning a sequence that is already under way restarted it
    // and signalled `finished` a second time, and the handler on the other end
    // deletes the still -- harmless as it happens, but a component that
    // signals completion twice for one run is one that cannot be reasoned
    // about from the outside.
    if (root.running) return
    root.progress = 0
    root.running = true
    // Belt and braces, for the same reason the lock itself has one.
    //
    // Every path in here is meant to end at done(): the sweep finishing, the
    // still failing to load, the shader failing to compile. If any of them
    // ever does not, this layer stays over the lock view holding a frozen
    // photograph of the desktop -- no wall, no countdown, and no way out for
    // the length of the lock. That would look exactly like the Blackwall being
    // broken, at the moment it is least possible to check.
    //
    // So the sequence is bounded from outside as well as from within.
    hardStop.restart()
    // Nothing to tear. Hand over at once rather than holding a black screen
    // for two and a half seconds.
    if (root.failed) {
      root.done()
      return
    }
    if (root.audioLead) sting.play()
    if (root.ready) sweep.restart()
    // otherwise onStatusChanged starts it the moment the still lands
  }

  function done() {
    if (!root.running) return
    root.running = false
    hardStop.stop()
    sweep.stop()
    // Skipped past, so the sting should not keep playing over a wall that is
    // already up.
    if (sting.playbackState === MediaPlayer.PlayingState) sting.stop()
    root.progress = 1
    root.finished()
  }

  Timer {
    id: hardStop
    // The sequence plus enough slack that it never pre-empts a healthy run.
    interval: root.durationMs + 1500
    repeat: false
    onTriggered: {
      console.warn("blackwall takeover did not finish on its own; handing over")
      root.done()
    }
  }

  visible: root.running && !root.failed && root.ready

  // One shot, synthesised by tools/make-takeover-sound.py and shaped to the
  // tear: the crack at the top, the fall through the middle, the impact as it
  // takes the screen, then a low settle for the wall's own ambience to come in
  // under. Not looped -- it ends where the tear does.
  MediaPlayer {
    id: sting
    source: Qt.resolvedUrl("audio/takeover.mp3")
    audioOutput: AudioOutput { volume: root.audioVolume }
    onErrorOccurred: function (err, str) {
      // A missing or unplayable sting is not a reason for the wall to stall.
      console.warn("blackwall takeover sound:", str)
    }
  }

  Image {
    id: shot
    source: root.source
    // Held for its texture only; the shader is what draws it.
    visible: false
    cache: false
    asynchronous: false
    fillMode: Image.PreserveAspectCrop
    sourceSize.width: root.width > 0 ? root.width : undefined
    sourceSize.height: root.height > 0 ? root.height : undefined

    onStatusChanged: {
      if (!root.running) return
      if (shot.status === Image.Ready) sweep.restart()
      else if (shot.status === Image.Error) root.done()
    }
  }

  NumberAnimation {
    id: sweep
    target: root
    property: "progress"
    from: 0
    to: 1
    duration: root.durationMs
    // The shader puts its own curve on this; a second one here would fight it.
    easing.type: Easing.Linear
    onFinished: root.done()
  }

  ShaderEffect {
    id: tear
    anchors.fill: parent
    visible: !effectFailed

    property variant src: shot
    property real progress: root.progress
    property real aspect: root.height > 0 ? root.width / root.height : 1.0
    property real time: root.clock

    readonly property bool effectFailed: tear.status === ShaderEffect.Error

    blending: true
    fragmentShader: Qt.resolvedUrl("takeover.frag.qsb")

    onStatusChanged: {
      if (tear.status === ShaderEffect.Error) {
        console.warn("blackwall takeover shader failed to load:", tear.log)
        // The wall still has to come up.
        root.done()
      }
    }
  }
}
