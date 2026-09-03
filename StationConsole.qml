pragma ComponentBehavior: Bound

import QtQuick
import "Model.js" as Model

// The ledger, as a console rather than a footnote.
//
// This is the one part of the station that is a record instead of an
// instrument: every line is something the daemon actually did, in the order it
// did it. It was previously drawn at 30% white on black at 10px, which is to
// say it was there and unreadable. A log nobody can read is not a log.
//
// New lines type themselves in. That is not decoration for its own sake — it
// is how you notice, out of the corner of your eye, that something arrived.
Item {
  id: root

  property real power: 1
  property color inkColor: "#ff2b34"
  property var entries: []
  property font font
  property real lineSize: 11
  // Redacts the detail column, which is the only one carrying a domain name.
  property bool censored: false

  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0


  // Set while the last line is being written out.
  property real reveal: 1
  property int lastCount: 0

  onEntriesChanged: {
    var n = root.entries.length
    if (n > root.lastCount && root.lastCount > 0) {
      root.reveal = 0
      typer.restart()
    } else if (n !== root.lastCount) {
      root.reveal = 1
    }
    root.lastCount = n
    list.positionViewAtEnd()
  }

  NumberAnimation {
    id: typer
    target: root
    property: "reveal"
    from: 0
    to: 1
    duration: 380
    easing.type: Easing.OutQuad
  }

  // The console's own ground, a shade off the panel so the text sits on
  // something rather than floating on the window.
  Rectangle {
    anchors.fill: parent
    color: "#090103"
  }

  // Scanlines across the console only. Cheap, and it is the single clearest
  // signal that this box is a screen and not a table.
  Repeater {
    model: Math.max(0, Math.floor(root.height / 3))

    delegate: Rectangle {
      required property int index
      x: 0
      y: index * 3
      width: root.width
      height: 1
      color: "#000000"
      opacity: 0.30 * root.power
    }
  }

  ListView {
    id: list
    anchors.fill: parent
    anchors.margins: 6
    clip: true
    model: root.entries
    spacing: 1
    boundsBehavior: Flickable.StopAtBounds

    delegate: Item {
      id: row
      required property var modelData
      required property int index

      width: list.width
      height: Math.round(root.lineSize * 1.45)

      readonly property bool newest: row.index === root.entries.length - 1
      readonly property bool breach: row.modelData
        && (row.modelData.kind === "breach" || row.modelData.kind === "lock")
      readonly property var parts: Model.stationLogParts(row.modelData)
      readonly property string line: Model.stationLogLine(row.modelData, root.censored)

      // The newest line writes itself in; every other line is simply there.
      readonly property string shown: row.newest
        ? row.line.substring(0, Math.ceil(root.reveal * row.line.length))
        : row.line

      Text {
        anchors.verticalCenter: parent.verticalCenter
        x: 0
        width: 34
        horizontalAlignment: Text.AlignRight
        text: String(row.index + 1).padStart(3, "0")
        font.family: root.font.family
        font.pixelSize: Math.round(root.lineSize * 0.85)
        color: Qt.rgba(root.inkColor.r, root.inkColor.g, root.inkColor.b, 0.40)
        opacity: root.power
      }

      Text {
        anchors.verticalCenter: parent.verticalCenter
        x: 44
        width: parent.width - 52
        elide: Text.ElideRight
        text: row.shown
        font.family: root.font.family
        font.pixelSize: root.lineSize
        font.bold: row.breach
        // A bar has to read as something struck out rather than picked out.
        // At the colour the text is set in, a run of solid blocks is the
        // brightest thing on the console -- which is the opposite of hiding.
        color: root.censored && row.parts.detail !== ""
          ? Qt.rgba(1, 0.30, 0.33, 0.40)
          : (row.breach ? Qt.rgba(1, 0.44, 0.46, 1)
                        : Qt.rgba(1, 0.62, 0.64, 0.88))
        opacity: root.power
      }

      // The cursor, on the line currently being written.
      Rectangle {
        visible: row.newest && root.power > 0
        anchors.verticalCenter: parent.verticalCenter
        x: 44 + measure.width + 2
        width: Math.round(root.lineSize * 0.55)
        height: Math.round(root.lineSize * 0.95)
        color: root.inkColor
        opacity: root.reveal < 1 ? 0.95 : root.blinkOn

        TextMetrics {
          id: measure
          font.family: root.font.family
          font.pixelSize: root.lineSize
          text: row.shown
        }
      }
    }
  }

  // One blink for the whole console rather than one per line. On for the
  // longer half, which is how a terminal caret sits.
  readonly property real blinkOn: (root.clock % 1.16) < 0.68 ? 1 : 0

  // Nothing to show yet reads as a dead console otherwise.
  Text {
    anchors.centerIn: parent
    visible: root.entries.length === 0
    text: "· no entries ·"
    font.family: root.font.family
    font.pixelSize: root.lineSize
    color: Qt.rgba(1, 1, 1, 0.22)
    opacity: root.power
  }
}
