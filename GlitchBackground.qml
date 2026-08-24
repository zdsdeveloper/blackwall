import QtQuick

// Fullscreen digital-static field for the lock surface. Draws underneath the
// wall, never in front of it.
//
// The work happens in glitch.frag (compiled to glitch.frag.qsb — Qt 6 will
// not accept inline GLSL strings the way Qt 5 did, so the .qsb has to be
// rebuilt with `qsb --qt6 -o glitch.frag.qsb glitch.frag` after any edit).
//
// If the shader fails to load for any reason the effect hides itself and the
// lock surface simply falls back to flat black — a broken background must
// never be a reason the Blackwall does not come up.
ShaderEffect {
  id: root

  // Seconds since the surface appeared. Driven by an animation rather than a
  // Timer so the GPU gets a fresh value every frame it paints.
  property real time: 0

  // Overall strength, 0..1. The lock view breathes this in sync with the
  // wall so the background swells with it instead of fighting it.
  property real intensity: 1.0

  property bool running: true

  readonly property real aspect: height > 0 ? width / height : 1.0
  readonly property real scanScale: Math.max(1.0, height)

  readonly property bool failed: status === ShaderEffect.Error

  fragmentShader: Qt.resolvedUrl("glitch.frag.qsb")

  visible: !failed
  blending: false

  onStatusChanged: {
    if (status === ShaderEffect.Error)
      console.warn("blackwall glitch shader failed to load:", log)
  }

  // One unit per second, rolling over after an hour. Restarted whenever the
  // surface reappears so every lock opens on the same part of the sequence.
  NumberAnimation on time {
    running: root.running && !root.failed
    from: 0
    to: 3600
    duration: 3600000
    loops: Animation.Infinite
  }
}
