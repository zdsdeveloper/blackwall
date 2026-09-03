pragma ComponentBehavior: Bound

import QtQuick

// The probe matrix: one cell per contained subject, showing what the resolver
// actually said about it.
//
// This is the one panel on the station that is not a readout of a file. Every
// other check asks whether /etc/hosts still carries the right lines; this asks
// where the name actually points when something on this machine looks it up,
// which is a different question and the one that matters. A hosts entry is a
// claim. A sink address coming back is the claim being kept.
//
// Drawn as a matrix rather than a list so it holds fifty subjects as readily
// as five, and drawn as cells rather than pipes because it is not carrying
// anything — it is a bank of answers, and a bank of answers is a grid.
Item {
  id: root

  property real power: 1
  property real clock: 0
  property color inkColor: "#ff2b34"
  property color warnColor: "#ffb84a"
  property font font

  // domains in display order, and the daemon's last sweep keyed by domain.
  property var domains: []
  property var results: ({})
  // Epoch seconds of the last sweep, 0 if none has run yet, and how often the
  // daemon sweeps. Both come straight from status.
  property real sweptAt: 0
  property real interval: 300
  // Epoch seconds now, so the countdown does not need its own clock.
  property real epoch: 0

  readonly property bool swept: root.sweptAt > 0

  function stateOf(domain) {
    var s = root.results ? root.results[domain] : undefined
    return s === undefined ? "unknown" : s
  }

  function colorFor(state) {
    // Sunk is the wall doing its job, so it is the wall's colour. Leaking is
    // the one state that wants the operator, so it is the one that is warm.
    if (state === "sunk") return root.inkColor
    if (state === "leaking") return root.warnColor
    if (state === "unresolved") return Qt.rgba(1, 0.42, 0.45, 0.75)
    return Qt.rgba(1, 1, 1, 0.20)
  }

  readonly property var leaks: {
    var out = []
    for (var i = 0; i < root.domains.length; i++)
      if (root.stateOf(root.domains[i]) === "leaking") out.push(root.domains[i])
    return out
  }

  readonly property int sunkCount: {
    var n = 0
    for (var i = 0; i < root.domains.length; i++)
      if (root.stateOf(root.domains[i]) === "sunk") n++
    return n
  }

  // Seconds until the next sweep, floored at zero. The daemon sweeps at the
  // end of an enforcement cycle, so this is "no sooner than", not "at".
  readonly property int nextIn: {
    if (!root.swept || root.epoch <= 0) return -1
    var left = Math.ceil(root.sweptAt + root.interval - root.epoch)
    return left > 0 ? left : 0
  }

  // ---- the matrix ----------------------------------------------------------

  readonly property real cellSize: 9
  readonly property real cellGap: 4
  readonly property int perRow: Math.max(1,
    Math.floor((root.width + root.cellGap) / (root.cellSize + root.cellGap)))

  Grid {
    id: matrix
    anchors.top: parent.top
    anchors.left: parent.left
    anchors.right: parent.right
    columns: root.perRow
    spacing: root.cellGap

    Repeater {
      model: root.domains

      delegate: Rectangle {
        id: cell
        required property var modelData
        required property int index

        readonly property string probeState: root.stateOf(cell.modelData)
        readonly property color tint: root.colorFor(cell.probeState)

        // The sweep runs over the cells in order, so the matrix shows the
        // probe working through the list rather than all of it changing at
        // once. Decorative in its timing, honest in its content: a cell only
        // ever shows the state the daemon reported for that name.
        readonly property real visited: {
          if (!root.swept) return 0
          var head = (root.clock / 3.0) % 1 * root.domains.length
          var d = head - cell.index
          return d >= 0 && d < 2.5 ? 1 - d / 2.5 : 0
        }

        width: root.cellSize
        height: root.cellSize
        color: cell.probeState === "unknown" ? "transparent" : cell.tint
        border.width: 1
        border.color: cell.probeState === "unknown"
          ? Qt.rgba(1, 1, 1, 0.22)
          : cell.tint
        opacity: root.power * (0.45 + 0.55 * Math.max(
          cell.probeState === "unknown" ? 0.35 : 0.75, cell.visited))
      }
    }
  }

  // ---- what it adds up to --------------------------------------------------

  Column {
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    spacing: 3

    Text {
      width: parent.width
      elide: Text.ElideRight
      text: {
        if (root.domains.length === 0) return "no subjects contained"
        if (!root.swept) return "awaiting first sweep"
        if (root.leaks.length === 0)
          return "all " + root.domains.length + " sunk at the resolver"
        return "LEAKING  " + root.leaks.join("  ")
      }
      font.family: root.font.family
      font.pixelSize: 10
      font.bold: root.leaks.length > 0
      color: root.leaks.length > 0
        ? root.warnColor
        : (root.swept ? Qt.rgba(1, 0.58, 0.60, 0.88) : Qt.rgba(1, 1, 1, 0.34))
      opacity: root.power
    }

    Text {
      visible: root.nextIn >= 0
      text: "next sweep in " + Math.floor(root.nextIn / 60) + "m "
        + (root.nextIn % 60) + "s"
      font.family: root.font.family
      font.pixelSize: 9
      color: Qt.rgba(1, 1, 1, 0.30)
      opacity: root.power
    }
  }
}
