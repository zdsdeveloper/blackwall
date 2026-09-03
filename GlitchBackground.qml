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

  // Seconds since the surface appeared, before quantising. Driven by an
  // animation rather than a Timer so it advances with the frame clock.
  property real clock: 0

  // What the shader is actually given, and the reason this window does not
  // cost a third of a core to sit still.
  //
  // Every visible thing in glitch.frag that moves is a floor of the clock:
  // `frame` is floor(time * stepRate) and `slow` is floor(time * stepRate/6).
  // Nothing else reads `time` at all -- the scanlines and the vignette are
  // functions of uv. So feeding the shader a `time` already rounded down to a
  // whole 1/stepRate step gives bit-identical output while changing the
  // uniform stepRate times a second instead of sixty, and a uniform that does
  // not change is a frame the ShaderEffect does not repaint.
  //
  // The two floors survive it exactly: floor(t'*stepRate) == floor(t*stepRate)
  // by construction, and floor(floor(x)/6) == floor(x/6) for x >= 0.
  //
  // At the lock's 18 that is a third of the repaints for the same picture. At
  // the station's 2.5 it is a fortieth.
  readonly property real time: root.stepRate > 0
    ? Math.floor(root.clock * root.stepRate) / root.stepRate
    : root.clock

  // Overall strength, 0..1. The lock view breathes this in sync with the
  // wall so the background swells with it instead of fighting it.
  property real intensity: 1.0

  property bool running: true

  // Seconds, if someone else is keeping time. Negative means drive yourself.
  // Same reasoning as the wall's: an animation running is a render loop
  // pinned at the refresh rate.
  property real externalClock: -1

  onExternalClockChanged: {
    if (root.externalClock >= 0) root.clock = root.externalClock % 3600
  }

  // The field's texture, exposed so one shader can serve two surfaces. The
  // defaults reproduce the lock exactly; the station asks for something much
  // finer and slower, and turns the loud half off.
  //
  //   grainScale  higher is finer -- sand rather than snow
  //   stepRate    how often the noise resamples; lower drifts, higher snaps
  //   artifacts   the tears and red blocks, 0 removes them entirely
  property real grainScale: 1.0
  property real stepRate: 18.0
  property real artifacts: 1.0

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
  NumberAnimation on clock {
    running: root.running && !root.failed && root.externalClock < 0
    from: 0
    to: 3600
    duration: 3600000
    loops: Animation.Infinite
  }
}
