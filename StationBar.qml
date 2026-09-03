pragma ComponentBehavior: Bound

import QtQuick

// A segmented bar. Two jobs, one shape.
//
// As a gauge it shows a level that means something — the rung, say, where two
// of two is a locked screen. As a progress bar it tracks work actually in
// flight: the segments fill left to right while a domain is committed, and
// stop where the work stopped.
//
// Segments rather than a smooth fill because a smooth fill reads as a
// percentage and segments read as capacity — and capacity is the true shape of
// "one more of these and the wall locks you out".
Item {
  id: root

  property real power: 1
  property int segments: 10
  // 0..1. Segments light in proportion.
  property real level: 0
  property color inkColor: "#ff2b34"
  property color warnColor: Qt.rgba(1, 0.72, 0.28, 1)
  // Draws in the warning colour without changing the level — used when the
  // thing being measured is at its last notch.
  property bool critical: false
  property real scaleUnit: 12

  // Set while real work is in flight. The lit head shimmers so a stalled
  // commit looks stalled rather than finished.
  property bool working: false
  property real shimmer: 0

  SequentialAnimation on shimmer {
    running: root.working && root.power > 0
    loops: Animation.Infinite
    NumberAnimation { from: 0.35; to: 1; duration: 420; easing.type: Easing.InOutSine }
    NumberAnimation { from: 1; to: 0.35; duration: 520; easing.type: Easing.InOutSine }
  }

  readonly property int litCount: Math.round(Math.max(0, Math.min(1, level)) * segments)

  implicitHeight: Math.round(scaleUnit * 0.72)
  implicitWidth: segments * Math.round(scaleUnit * 0.46)

  Row {
    id: strip
    anchors.fill: parent
    spacing: Math.max(1, Math.round(root.scaleUnit * 0.12))

    Repeater {
      model: root.segments

      delegate: Rectangle {
        id: seg
        required property int index

        readonly property bool lit: seg.index < root.litCount
        readonly property bool head: seg.index === root.litCount - 1

        // Through the Row's own id. A delegate's `parent` is the Row only
        // after it is reparented at runtime, so reaching spacing that way
        // happens to work and does not survive being reasoned about.
        width: Math.max(2, (root.width - (root.segments - 1) * strip.spacing) / root.segments)
        height: root.height
        color: seg.lit ? (root.critical ? root.warnColor : root.inkColor) : "transparent"
        border.width: seg.lit ? 0 : 1
        border.color: Qt.rgba(1, 0.24, 0.28, 0.20)

        opacity: root.power * (seg.lit
          ? (seg.head && root.working ? root.shimmer : 1)
          : 1)

        Behavior on opacity {
          NumberAnimation { duration: 180 }
        }
      }
    }
  }
}
