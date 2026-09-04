pragma ComponentBehavior: Bound

import QtQuick
import "NetWatchLogo.js" as Wordmark

// The NetWatch mark, in NetWatch's colours.
//
// The station is a NetWatch post watching the Blackwall, and the two are not
// the same thing. The wall is red because it is the thing being contained; the
// agency watching it is cold — steel and ice, corporate rather than hostile —
// so the mark runs near-white at the top into a pale blue at the foot.
//
// Drawn one row per Text, each row its own colour. A Text takes a single
// colour, and this is the cheapest way to get a vertical two-tone across a
// glyph run without a shader or a mask: the same trick the wall uses to
// colour its slices. Six rows, laid out once, then never re-laid-out.
Item {
  id: root

  property string monoFamily: "monospace"
  property real power: 1
  property real clock: 0
  property color topColor: "#eaf7ff"
  property color footColor: "#6fc8e8"
  // Set when the post is not hearing from the daemon. The mark goes to a dead
  // steel grey: the agency is still there, it is just not being told anything.
  property bool live: true

  // Left in the station's header, where it sits beside other things; centred
  // on a surface where it is the thing. Without this the block is drawn at
  // whatever size fits and then pinned to the left edge of a wider item, which
  // reads as off-centre however carefully the item itself is centred.
  property bool centred: false

  readonly property int rows: Wordmark.rowCount()

  // Measured at a known size and scaled, the same approach the wall takes, so
  // the block is drawn at a real font size rather than drawn small and blown
  // up into mush.
  TextMetrics {
    id: probe
    font.family: root.monoFamily
    font.pixelSize: 40
    text: Wordmark.longestLine()
  }

  readonly property real rowAdvance: probe.height > 0 ? probe.height : 44
  readonly property real fitByWidth:
    probe.width > 0 ? 40 * (root.width / probe.width) : 8
  readonly property real fitByHeight:
    root.rowAdvance > 0 ? 40 * (root.height / (root.rowAdvance * root.rows)) : 8
  readonly property real markSize:
    Math.max(4, Math.min(root.fitByWidth, root.fitByHeight))

  // The height one row occupies at the size actually being drawn.
  readonly property real lineHeight: root.rowAdvance * (root.markSize / 40)

  implicitWidth: probe.width * (root.markSize / 40)
  implicitHeight: root.lineHeight * root.rows

  // A pale charge running down the mark, about every nine seconds. Enough to
  // say the post is powered; not enough to draw the eye off the wall.
  readonly property real scan: (root.clock / 9.0) % 1

  Column {
    anchors.left: root.centred ? undefined : parent.left
    anchors.horizontalCenter: root.centred ? parent.horizontalCenter : undefined
    anchors.verticalCenter: parent.verticalCenter
    spacing: 0

    Repeater {
      model: root.rows

      delegate: Text {
        id: line
        required property int index

        // 0 at the top row, 1 at the foot.
        readonly property real depth:
          root.rows > 1 ? line.index / (root.rows - 1) : 0

        // How close the travelling charge is to this row.
        readonly property real touched: {
          var d = Math.abs(line.depth - (root.scan * 1.6 - 0.3))
          return Math.max(0, 1 - d * 4)
        }

        text: Wordmark.ROWS[line.index]
        font.family: root.monoFamily
        font.pixelSize: root.markSize
        height: root.lineHeight
        verticalAlignment: Text.AlignVCenter
        color: {
          var cold = root.live ? root.footColor : Qt.rgba(0.36, 0.42, 0.45, 1)
          var warm = root.live ? root.topColor : Qt.rgba(0.55, 0.62, 0.66, 1)
          var base = Qt.rgba(
            warm.r + (cold.r - warm.r) * line.depth,
            warm.g + (cold.g - warm.g) * line.depth,
            warm.b + (cold.b - warm.b) * line.depth, 1)
          if (line.touched <= 0) return base
          // The charge lifts a row toward white rather than tinting it.
          var t = line.touched * 0.45
          return Qt.rgba(base.r + (1 - base.r) * t,
                         base.g + (1 - base.g) * t,
                         base.b + (1 - base.b) * t, 1)
        }
        opacity: root.power
      }
    }
  }
}
