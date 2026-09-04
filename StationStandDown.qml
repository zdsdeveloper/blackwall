pragma ComponentBehavior: Bound

import QtQuick
import "Model.js" as Model

// How long is left before NetWatch takes the break for them.
//
// The vigil panel above says how long it has been. This says what happens
// next, which is the half that actually changes behaviour: a stretch is a
// fact, a countdown is a warning. When it reaches zero the window that closes
// what you were doing is already on its way, so the number is drawn as
// something running out rather than as a reading.
Item {
  id: root

  property real power: 1
  property font font
  property var readout: ({})
  property color inkColor: "#8fd8f2"
  property color glowColor: "#eaf7ff"
  property color warnColor: "#ffb84a"

  // Seconds, from the station's one clock.
  property real clock: 0
  // The station's shared caret blink, so the colon here keeps time with every
  // other caret on the surface rather than running its own.
  property real caret: 1

  readonly property bool counting: root.readout && root.readout.enabled === true
  readonly property bool away: root.counting && root.readout.away === true
  readonly property bool due: root.counting && root.readout.due === true
  readonly property real leftMs: root.counting ? Number(root.readout.untilBreakMs) || 0 : 0

  // The last five minutes, where it stops being a number on a panel.
  readonly property bool closing: root.counting && !root.due && root.leftMs <= 5 * 60000

  readonly property color faceColor: root.due || root.closing
    ? root.warnColor
    : (root.counting ? root.glowColor : Qt.rgba(1, 1, 1, 0.22))

  // What is left of the stretch, which is what this bar draws. Named rather
  // than written inline so a test can assert on the thing the bar is actually
  // bound to instead of recomputing the same arithmetic beside it and proving
  // nothing.
  readonly property real barLevel: root.counting
    ? Model.clamp(1 - (Number(root.readout.fraction) || 0), 0, 1)
    : 0

  readonly property real bigSize:
    Math.max(17, Math.min(34, Math.round(root.height * 0.30)))

  // A colon that blinks reads as time running; a solid one reads as a label.
  // Monospace, so swapping it for a space cannot shift the digits.
  readonly property string face: {
    if (!root.counting) return "--:--"
    if (root.due) return "00:00"
    var t = Model.formatRemaining(root.leftMs)
    // Held while they are away: the countdown is not running, so its colon
    // should not be either.
    if (root.away || root.caret > 0.5) return t
    return t.replace(/:/g, " ")
  }

  Column {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    spacing: Math.max(3, Math.round(root.height * 0.05))

    Text {
      // The frame above it already says STAND DOWN. This says what about it.
      text: {
        if (!root.counting) return "NOT COUNTING"
        if (root.due) return "DUE NOW"
        if (root.away) return "HELD — AWAY FROM THE POST"
        return "BREAK DUE IN"
      }
      font.family: root.font.family
      font.pixelSize: 9
      font.letterSpacing: 2
      color: root.due
        ? root.warnColor
        : Qt.rgba(1, 1, 1, 0.40)
      opacity: root.power
      // Only once it is owed. A panel that breathes for the whole three hours
      // is a panel nobody looks at by the end of them.
      Behavior on color { ColorAnimation { duration: 300 } }
    }

    Text {
      text: root.face
      font.family: root.font.family
      font.pixelSize: root.bigSize
      font.letterSpacing: 1
      color: root.faceColor
      opacity: root.power * (root.away ? 0.55 : 1)
        * (root.due ? 0.72 + 0.28 * (0.5 - 0.5 * Math.cos(root.clock * 3.2)) : 1)
    }

    // Emptying, where the vigil's bar fills. Same fact, told as what is left.
    StationBar {
      width: parent.width
      segments: 24
      scaleUnit: Math.max(10, Math.min(15, Math.round(root.height * 0.13)))
      level: root.barLevel
      critical: root.closing || root.due
      inkColor: root.inkColor
      warnColor: root.warnColor
      power: root.power
    }

    Text {
      width: parent.width
      wrapMode: Text.WordWrap
      maximumLineCount: 2
      elide: Text.ElideRight
      text: {
        if (!root.counting) return "nothing is counting"
        if (root.due) return "by order of NetWatch — the wall goes up either way"
        if (root.away) return "resumes when they are back at the desk"
        return "then " + Model.BREAK_CHOICES.join(" / ") + " min, your choice of which"
      }
      font.family: root.font.family
      font.pixelSize: 9
      color: root.due
        ? Qt.rgba(root.warnColor.r, root.warnColor.g, root.warnColor.b, 0.85)
        : Qt.rgba(1, 1, 1, 0.34)
      opacity: root.power
    }
  }
}
