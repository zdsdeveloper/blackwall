pragma ComponentBehavior: Bound

import QtQuick

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
    root.progress = 0
    root.running = true
    // Nothing to tear. Hand over at once rather than holding a black screen
    // for two and a half seconds.
    if (root.failed) {
      root.done()
      return
    }
    if (root.ready) sweep.restart()
    // otherwise onStatusChanged starts it the moment the still lands
  }

  function done() {
    if (!root.running) return
    root.running = false
    root.progress = 1
    root.finished()
  }

  visible: root.running && !root.failed && root.ready

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
