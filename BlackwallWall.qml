pragma ComponentBehavior: Bound

import QtQuick
import "Logo.js" as Logo
import "Model.js" as Model

// The wall itself: the ASCII logo, its bloom, and the ripple running through
// it.
//
// Lifted out of BlackwallLockView so the lock surface and the breach challenge
// are the same wall rather than two copies of it. A change to how the wall
// moves should not have to be made twice and land in one place.
//
// The release sequence is passed in as plain numbers rather than understood
// here: a surface that never opens the wall does not have to know the sequence
// exists, and gets the defaults.
Item {
  id: root

  property bool active: true
  property string monoFamily: "monospace"

  // The space the wall may size itself against — the surface it sits on, not
  // its own bounds, which are derived from the font it settles on.
  property real availableWidth: 0
  property real availableHeight: 0

  // How much of that space it may take. The lock gives it the screen; the
  // challenge has a question and an input to fit underneath.
  property real heightFraction: 0.46
  property real widthFraction: 0.84

  property real rippleStrength: 0.14

  // Release-sequence inputs, all neutral by default.
  property real rippleBoost: 1
  property real bleach: 0
  property real shatterSpan: 0
  property bool releasing: false
  property real releaseProgress: 0

  // Outputs. The surfaces around the wall breathe with it — the static behind
  // it, the countdown under it — so the value has to be readable from outside.
  property real phase: 0
  property real breath: 0

  readonly property int rows: Logo.rowCount()
  readonly property int sliceCount: rows

  // Measured at a known size and scaled, so the wall fills its share at a real
  // font size instead of being drawn small and scaled up into mush.
  TextMetrics {
    id: probe
    font.family: root.monoFamily
    font.pixelSize: 64
    text: Logo.longestLine()
  }

  // Line advance as a fraction of the font size, taken from the font rather
  // than assumed. Getting this wrong is what collapses the wall: too tight and
  // the half-block rows overlap into a solid slab.
  readonly property real lineRatio: probe.height > 0 ? probe.height / 64 : 1.3

  readonly property int logoFontSize: {
    if (probe.width <= 0 || root.availableWidth <= 0 || root.availableHeight <= 0)
      return 12
    var byWidth = 64 * (root.availableWidth * root.widthFraction) / probe.width
    var byHeight = (root.availableHeight * root.heightFraction) / (root.rows * lineRatio)
    return Math.max(4, Math.floor(Math.min(byWidth, byHeight)))
  }

  // The wall's true painted size at the chosen font size. Slice geometry comes
  // from this so the bands line up with the character rows.
  Text {
    id: metrics
    visible: false
    text: Logo.TEXT
    font.family: root.monoFamily
    font.pixelSize: root.logoFontSize
  }

  readonly property real wallWidth: metrics.contentWidth
  readonly property real wallHeight: metrics.contentHeight
  readonly property real cellHeight: root.rows > 0 ? wallHeight / root.rows : 0
  readonly property real rippleAmplitude:
    Math.max(1, logoFontSize * rippleStrength) * rippleBoost

  implicitWidth: wallWidth
  implicitHeight: wallHeight
  width: wallWidth
  height: wallHeight

  scale: 1 + 0.016 * root.breath
  transformOrigin: Item.Center

  function sliceColor(index) {
    var t = Model.intensityAt(index, root.sliceCount, root.phase, root.breath)
    var r = 0.07 + 0.93 * t
    var g = 0.008 + 0.17 * t
    var b = 0.02 + 0.20 * t
    // Bleaching pulls green and blue up toward the red, so the wall goes from
    // red to white-hot as it thins rather than simply getting brighter.
    var w = root.bleach
    if (w > 0) {
      // Ripple structure survives as luminance; the hue goes incandescent
      // rather than desaturating into grey.
      var hot = 0.45 + 0.55 * t
      r = r + (Math.min(1, hot * 1.08) - r) * w
      g = g + (hot * 0.88 - g) * w
      b = b + (hot * 0.86 - b) * w
    }
    return Qt.rgba(r, g, b, 1)
  }

  NumberAnimation on phase {
    running: root.active
    from: 0
    to: Model.TAU
    duration: 2600
    loops: Animation.Infinite
  }

  SequentialAnimation on breath {
    running: root.active
    loops: Animation.Infinite
    NumberAnimation { from: 0; to: 1; duration: 1900; easing.type: Easing.InOutSine }
    NumberAnimation { from: 1; to: 0; duration: 2500; easing.type: Easing.InOutSine }
  }

  // Bloom. No blur filter is available here, so two oversized, very dim copies
  // stand in for the halo — the breath drives both.
  Repeater {
    model: [
      { scale: 1.010, alpha: 0.22 },
      { scale: 1.038, alpha: 0.11 }
    ]

    delegate: Text {
      required property var modelData
      anchors.centerIn: parent
      horizontalAlignment: Text.AlignLeft
      text: Logo.TEXT
      font.family: root.monoFamily
      font.pixelSize: root.logoFontSize
      color: "#ff2b34"
      scale: modelData.scale
      opacity: modelData.alpha * (0.35 + 0.65 * root.breath) * (1 - root.shatterSpan)
    }
  }

  // The rippling wall itself.
  Repeater {
    model: root.sliceCount

    delegate: Item {
      id: slice
      required property int index

      readonly property int sliceTop: Math.round(index * root.height / root.sliceCount)
      readonly property int sliceBottom: Math.round((index + 1) * root.height / root.sliceCount)

      x: 0
      y: sliceTop
      width: root.width
      height: sliceBottom - sliceTop
      // Clipping has to stop once the rows start flying, or each row would be
      // sliced off at its own band and the break would read as a wipe instead
      // of the wall coming apart.
      clip: root.shatterSpan <= 0
      opacity: root.releasing
        ? Model.shatterFade(slice.index, root.releaseProgress)
        : 1

      Text {
        x: Model.offsetAt(slice.index, root.sliceCount, root.phase,
                          root.rippleAmplitude, root.breath)
          + (root.releasing
             ? Model.shatterOffset(slice.index, root.releaseProgress, root.width)
             : 0)
        y: -slice.sliceTop
          + (root.releasing
             ? Model.shatterDrift(slice.index, root.sliceCount,
                                  root.releaseProgress, root.height)
             : 0)
        width: root.width
        text: Logo.TEXT
        font.family: root.monoFamily
        font.pixelSize: root.logoFontSize
        color: root.sliceColor(slice.index)
      }
    }
  }
}
