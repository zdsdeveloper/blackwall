pragma ComponentBehavior: Bound

import QtQuick

// A bordered instrument panel, in the shape a terminal draws things: a hairline
// box, heavier brackets at the corners, and the label cut into the top edge
// rather than floating above it.
//
// Everything on the station lives in one of these. Loose text on a black field
// reads as a web page; a field of framed boxes reads as a console, and the
// frame is most of what does that work.
//
// The charge running the top edge is the panel's own pulse. It is decorative,
// but it is gated on `power`, so a panel that is not powered is visibly dead
// rather than merely empty.
Item {
  id: root

  property string title: ""
  // Shown at the right of the top edge, where an instrument prints its unit.
  property string annotation: ""
  property real power: 1
  property color inkColor: "#ff2b34"
  property color paperColor: "#050102"
  // Draws the whole frame in the warning colour. For a panel whose contents
  // are the problem.
  property bool alert: false
  // Runs the top-edge charge. Off for panels that are merely holding still.
  property bool live: true
  property real padding: 12
  // A frame is used in enough places that it carries its own type knobs
  // rather than reaching for the station's.
  property font font
  property real labelSize: 9

  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0


  readonly property color edgeColor: root.alert
    ? Qt.rgba(1, 0.72, 0.28, 1)
    : root.inkColor

  // Where children go. Declared as the default property so callers can write
  // StationFrame { Text { ... } } and have it land inside the border.
  default property alias content: body.data

  // ---- the box -------------------------------------------------------------

  Rectangle {
    anchors.fill: parent
    color: "transparent"
    border.width: 1
    border.color: Qt.rgba(root.edgeColor.r, root.edgeColor.g, root.edgeColor.b,
                          (root.alert ? 0.55 : 0.26) * root.power)
  }

  // Corner brackets. Two rectangles per corner, drawn over the hairline, which
  // is what gives the box weight without thickening the whole border.
  Repeater {
    model: [
      { hx: 0, hy: 0 }, { hx: 1, hy: 0 }, { hx: 0, hy: 1 }, { hx: 1, hy: 1 }
    ]

    delegate: Item {
      id: corner
      required property var modelData
      anchors.fill: parent

      readonly property real arm: Math.max(8, Math.min(18, root.width * 0.05))
      readonly property color c: Qt.rgba(root.edgeColor.r, root.edgeColor.g,
                                         root.edgeColor.b, 0.85 * root.power)

      Rectangle {
        width: corner.arm
        height: 1
        color: corner.c
        x: corner.modelData.hx === 0 ? 0 : parent.width - width
        y: corner.modelData.hy === 0 ? 0 : parent.height - 1
      }

      Rectangle {
        width: 1
        height: corner.arm
        color: corner.c
        x: corner.modelData.hx === 0 ? 0 : parent.width - 1
        y: corner.modelData.hy === 0 ? 0 : parent.height - height
      }
    }
  }

  // ---- the label, cut into the top edge ------------------------------------

  Row {
    x: root.padding
    y: -Math.round(label.height / 2)
    spacing: 0
    visible: root.title !== ""

    // The gap in the border. Painted in the panel colour rather than made
    // transparent, because the border runs underneath it.
    Rectangle {
      width: label.width + 12
      height: label.height
      color: root.paperColor

      Text {
        id: label
        anchors.centerIn: parent
        text: root.title
        font.family: root.font.family
        font.pixelSize: Math.round(root.labelSize)
        font.letterSpacing: 2.5
        font.bold: true
        color: Qt.rgba(root.edgeColor.r, root.edgeColor.g, root.edgeColor.b,
                       0.92 * root.power)
      }
    }
  }

  Rectangle {
    visible: root.annotation !== ""
    x: root.width - width - root.padding
    y: -Math.round(height / 2)
    width: note.width + 12
    height: note.height
    color: root.paperColor

    Text {
      id: note
      anchors.centerIn: parent
      text: root.annotation
      font.family: root.font.family
      font.pixelSize: Math.round(root.labelSize)
      font.letterSpacing: 1.5
      color: Qt.rgba(1, 1, 1, 0.34 * root.power)
    }
  }

  // ---- the charge on the top edge ------------------------------------------

  readonly property real sweep: root.live ? (root.clock / 4.2) % 1 : -1

  Rectangle {
    width: Math.max(24, root.width * 0.14)
    height: 1
    y: 0
    // Travels the full width and then off the end, so there is a gap between
    // passes instead of a permanently circulating bead.
    x: root.sweep * (root.width + width) - width
    visible: root.live && root.power > 0
    gradient: Gradient {
      orientation: Gradient.Horizontal
      GradientStop { position: 0.0; color: "transparent" }
      GradientStop {
        position: 0.7
        color: Qt.rgba(root.edgeColor.r, root.edgeColor.g, root.edgeColor.b,
                       0.75 * root.power)
      }
      GradientStop { position: 1.0; color: "transparent" }
    }
  }

  // ---- the contents --------------------------------------------------------

  Item {
    id: body
    anchors.fill: parent
    anchors.margins: root.padding
    anchors.topMargin: root.padding + (root.title === "" ? 0 : 4)
    clip: true
    opacity: root.power
  }
}
