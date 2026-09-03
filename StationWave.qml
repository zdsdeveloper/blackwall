pragma ComponentBehavior: Bound

import QtQuick

// A scope trace. Bars stood up either side of a centre line, following a
// travelling wave, with a bright head where the beam is writing.
//
// The wave is three sines of unrelated periods summed together, which is what
// keeps it from reading as a single sine sliding sideways — the shape has to
// change as it goes or the eye stops seeing it after a second.
//
// It measures nothing. It says the post is live, which on a monitor that is
// mostly waiting is worth its space.
Item {
  id: root

  property real power: 1
  property color inkColor: "#ff2b34"
  property int bars: 56
  property real amplitude: 0.42
  property real speed: 1.0
  // Rises and goes ragged when something is wrong, so the panel reads
  // differently across the room without anybody reading the words.
  property bool agitated: false

  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0


  readonly property real cycleSeconds: Math.max(0.9, 3.4 / Math.max(0.05, root.speed))
  readonly property real phase: (root.clock / root.cycleSeconds) % 1 * Math.PI * 2

  // Quantised for the same reason the boards are: every bar rebinds on every
  // change, and a scope that redraws 22 times a second looks like a scope.
  // Sixty would look identical and cost three times as much.
  readonly property real steppedPhase:
    Math.round(root.phase * 12) / 12

  function sampleAt(i) {
    var u = i / Math.max(1, root.bars - 1)
    var t = root.steppedPhase
    var v = Math.sin(u * 7.1 + t)
          + 0.55 * Math.sin(u * 17.3 - t * 1.7)
          + 0.30 * Math.sin(u * 31.7 + t * 2.6)
    if (root.agitated)
      v += 0.9 * Math.sin(u * 71.0 + t * 6.1) * Math.sin(t * 3.3)
    return v / (root.agitated ? 2.7 : 1.85)
  }

  // Where the beam is writing, 0..1 across the panel.
  readonly property real head: (root.steppedPhase / (Math.PI * 2)) % 1

  // The centre line the trace is written on.
  Rectangle {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    height: 1
    color: root.inkColor
    opacity: 0.14 * root.power
  }

  Row {
    anchors.fill: parent
    spacing: 0

    Repeater {
      model: root.bars

      delegate: Item {
        id: cell
        required property int index

        width: root.width / root.bars
        height: root.height

        readonly property real v: root.sampleAt(cell.index)
        // Distance from the writing head, wrapped, so the glow follows it
        // round rather than stopping at the right edge.
        readonly property real fromHead: {
          var d = Math.abs((cell.index / Math.max(1, root.bars - 1)) - root.head)
          return Math.min(d, 1 - d)
        }

        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          anchors.verticalCenter: parent.verticalCenter
          width: Math.max(1, cell.width * 0.55)
          height: Math.max(1, Math.abs(cell.v) * root.height * root.amplitude)
          color: root.agitated ? Qt.rgba(1, 0.72, 0.28, 1) : root.inkColor
          opacity: root.power * (0.30 + 0.70 * Math.max(0, 1 - cell.fromHead * 7))
        }
      }
    }
  }
}
