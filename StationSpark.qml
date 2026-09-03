pragma ComponentBehavior: Bound

import QtQuick

// A sparkline of the enforcement cycle: one bar per completed pass, newest on
// the right, scrolling left as the daemon works.
//
// Decorative in the sense that nobody acts on it, and honest in the sense that
// it only moves when the daemon actually completes a cycle. A station where the
// heartbeat kept beating after the heart stopped would be worse than one with
// no heartbeat at all.
Item {
  id: root

  property real power: 1
  property int bars: 24
  property color inkColor: "#ff2b34"
  property real scaleUnit: 12

  // Newest last. Callers push a value in 0..1 per cycle.
  property var samples: []

  // A cycle that found nothing to do is a low bar, one that repaired something
  // is a tall one, and a failed cycle is drawn in the warning colour. The
  // shape of the last two minutes is readable at a glance without a legend.
  function push(level, failed) {
    var next = root.samples.slice(-(root.bars - 1))
    next.push({ level: Math.max(0.08, Math.min(1, Number(level) || 0.08)),
                failed: !!failed })
    root.samples = next
  }

  implicitHeight: Math.round(scaleUnit * 1.6)
  implicitWidth: bars * Math.round(scaleUnit * 0.28)

  Row {
    anchors.bottom: parent.bottom
    anchors.left: parent.left
    spacing: Math.max(1, Math.round(root.scaleUnit * 0.10))

    Repeater {
      model: root.samples

      delegate: Rectangle {
        id: bar
        required property var modelData
        required property int index

        width: Math.max(1, Math.round(root.scaleUnit * 0.18))
        height: Math.max(1, Math.round(root.height * bar.modelData.level))
        color: bar.modelData.failed ? Qt.rgba(1, 0.72, 0.28, 1) : root.inkColor
        // The newest bar is full strength and the trail dims behind it, so the
        // eye finds "now" without having to count from the end.
        opacity: root.power
          * (0.22 + 0.78 * (bar.index + 1) / Math.max(1, root.samples.length))

        Behavior on height {
          NumberAnimation { duration: 260; easing.type: Easing.OutCubic }
        }
      }
    }
  }
}
