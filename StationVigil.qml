pragma ComponentBehavior: Bound

import QtQuick
import "Model.js" as Model

// How long the operator has been at the post, without a break.
//
// The one instrument on the station that is not about the wall. Everything
// else here reads out something the daemon did; this reads out something the
// person did, which is why it is drawn in NetWatch's cold colours rather than
// the wall's red even though it sits below the header rule. It is the post
// watching its own operator.
//
// It shows a stretch, not a clock time. Nobody needs telling what time it is;
// what is worth knowing at hour three is that it has been three hours.
Item {
  id: root

  property real power: 1
  property font font
  // The reading, from Model.activityReadout. Projected forward to now by the
  // caller, so this simply draws what it is handed.
  property var readout: ({})
  property color inkColor: "#8fd8f2"
  property color glowColor: "#eaf7ff"
  property color warnColor: "#ffb84a"

  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0

  readonly property bool counting: root.readout && root.readout.enabled === true
  readonly property bool away: root.counting && root.readout.away === true
  readonly property real fraction: root.counting ? Number(root.readout.fraction) || 0 : 0
  readonly property bool due: root.counting && root.readout.due === true

  // The elapsed stretch, as a stretch. Not rounded to minutes: the seconds
  // moving are the whole reason this reads as something running rather than a
  // number somebody typed in.
  readonly property string elapsed: root.counting
    ? Model.formatRemaining(Number(root.readout.activeMs) || 0)
    : "--:--"

  // What the eye should be drawn to, at the size the frame can afford.
  readonly property real bigSize:
    Math.max(17, Math.min(34, Math.round(root.height * 0.30)))

  Column {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    spacing: Math.max(3, Math.round(root.height * 0.05))

    Text {
      text: root.counting
        ? (root.away ? "AWAY FROM THE POST" : "CONTINUOUS AT THE POST")
        : "NOT COUNTING"
      font.family: root.font.family
      font.pixelSize: 9
      font.letterSpacing: 2
      color: root.away
        ? Qt.rgba(root.warnColor.r, root.warnColor.g, root.warnColor.b, 0.85)
        : Qt.rgba(1, 1, 1, 0.40)
      opacity: root.power
    }

    Text {
      text: root.elapsed
      font.family: root.font.family
      font.pixelSize: root.bigSize
      font.letterSpacing: 1
      color: root.counting ? root.glowColor : Qt.rgba(1, 1, 1, 0.22)
      // A held count is dimmed rather than stopped. It is still true; it is
      // just not moving, and dimming says that without another line of text.
      opacity: root.power * (root.away ? 0.55 : 1)
    }

    // The stretch spent, filling. Its opposite number on the stand-down panel
    // empties, which is the same fact told the other way round.
    StationBar {
      width: parent.width
      segments: 24
      scaleUnit: Math.max(10, Math.min(15, Math.round(root.height * 0.13)))
      level: root.fraction
      critical: root.due
      inkColor: root.inkColor
      warnColor: root.warnColor
      power: root.power
    }

    Text {
      width: parent.width
      elide: Text.ElideRight
      text: {
        if (!root.counting) return "break reminders are off"
        if (root.away) {
          var back = Math.ceil((Number(root.readout.resetInMs) || 0) / 60000)
          return back > 0
            ? "count held · " + back + " min away and it resets"
            : "away long enough · the stretch has reset"
        }
        var span = Math.round((Number(root.readout.breakAfterMs) || 0) / 60000)
        return "of " + Model.formatDuration(span) + " before a break is owed"
      }
      font.family: root.font.family
      font.pixelSize: 9
      color: Qt.rgba(1, 1, 1, 0.34)
      opacity: root.power
    }
  }
}
