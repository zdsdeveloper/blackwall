pragma ComponentBehavior: Bound

import QtQuick

// The power-on sequence: a field terminal coming up, checking itself, and
// naming whoever is standing at it.
//
// Every line is a real reading. The subject count, the sink lines, the sweep,
// the seal — all of it comes off the same status the panel behind is about to
// draw, so the sequence is the station reporting itself rather than a loading
// bar with numbers painted on. A check that fails says so and the terminal
// comes up anyway; this gates nothing.
//
// The greeting recognises. It does not authenticate. A USB id is four bytes
// anyone can claim, the file listing them is world-readable, and anyone
// holding that mouse is greeted by that name. It is a nameplate on a door, and
// in a plugin whose whole subject is enforcement it is worth being exact about
// which of the two a thing is.
Item {
  id: root

  property real clock: 0
  property string monoFamily: "monospace"
  property color inkColor: "#ff2b34"
  property color netwatchInk: "#8fd8f2"
  property color netwatchGlow: "#eaf7ff"

  // [{ label, value, alert }] — supplied by the panel, which is where the
  // status lives. Values are live bindings, so a line already on screen fills
  // itself in when the first poll lands.
  property var lines: []
  // The name to greet, or "" for a pointing device nobody has claimed.
  property string agent: ""
  property string token: ""

  signal finished()

  // ---- the run -------------------------------------------------------------

  property real startedAt: 0
  property bool running: false

  readonly property real lineInterval: 0.16
  readonly property real charInterval: 0.006
  readonly property real greetHold: 1.15

  readonly property real elapsed: root.running
    ? Math.max(0, root.clock - root.startedAt) : 0

  readonly property real linesDoneAt: root.lines.length * root.lineInterval
  readonly property bool greeting: root.elapsed >= root.linesDoneAt
  readonly property real total: root.linesDoneAt + root.greetHold

  function begin() {
    root.startedAt = root.clock
    root.running = true
  }

  function skip() {
    if (!root.running) return
    root.running = false
    root.finished()
  }

  onElapsedChanged: {
    if (root.running && root.elapsed >= root.total) root.skip()
  }

  visible: root.running
  // A sequence you cannot get past is a sequence you come to resent. Anywhere
  // on it, any button.
  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.AllButtons
    onClicked: root.skip()
  }

  Rectangle {
    anchors.fill: parent
    color: "#040003"
    opacity: 0.97
  }

  Column {
    anchors.centerIn: parent
    width: Math.min(560, parent.width * 0.78)
    spacing: 2

    Text {
      text: "NETWATCH FIELD TERMINAL"
      font.family: root.monoFamily
      font.pixelSize: 12
      font.bold: true
      font.letterSpacing: 4
      color: root.netwatchInk
    }

    Text {
      text: "──────────────────────────────────────────"
      font.family: root.monoFamily
      font.pixelSize: 11
      color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                     root.netwatchInk.b, 0.30)
    }

    Item { width: 1; height: 8 }

    Repeater {
      // Only while the sequence is up. The lines are live bindings on status,
      // so leaving the model connected would rebuild nine delegates on every
      // poll for a surface nobody is looking at.
      model: root.running ? root.lines : []

      delegate: Item {
        id: entry
        required property var modelData
        required property int index

        width: parent.width
        height: visible ? Math.round(13 * 1.5) : 0
        visible: root.elapsed >= entry.index * root.lineInterval

        readonly property real since:
          root.elapsed - entry.index * root.lineInterval
        // The label types itself in; the reading lands whole once it has.
        readonly property string label: "> " + String(entry.modelData.label)
        readonly property int shown:
          Math.min(entry.label.length,
                   Math.ceil(entry.since / root.charInterval))
        readonly property bool settled: entry.shown >= entry.label.length

        Text {
          id: typed
          anchors.verticalCenter: parent.verticalCenter
          text: entry.label.substring(0, entry.shown)
          font.family: root.monoFamily
          font.pixelSize: 11
          color: Qt.rgba(1, 0.62, 0.64, 0.90)
        }

        // Leader dots, so the readings line up on the right the way an
        // instrument panel's do.
        Item {
          anchors.verticalCenter: parent.verticalCenter
          x: typed.x + typed.width + 6
          width: Math.max(0, reading.x - x - 6)
          height: 12
          clip: true
          visible: entry.settled

          Text {
            anchors.verticalCenter: parent.verticalCenter
            text: "······························································"
            font.family: root.monoFamily
            font.pixelSize: 11
            color: Qt.rgba(1, 0.30, 0.33, 0.30)
          }
        }

        Text {
          id: reading
          anchors.verticalCenter: parent.verticalCenter
          x: parent.width - width
          visible: entry.settled
          text: String(entry.modelData.value)
          font.family: root.monoFamily
          font.pixelSize: 11
          font.bold: true
          color: entry.modelData.alert
            ? Qt.rgba(1, 0.72, 0.28, 1)
            : Qt.rgba(1, 0.62, 0.64, 0.95)
        }
      }
    }

    Item { width: 1; height: 14; visible: root.greeting }

    // The nameplate.
    Text {
      visible: root.greeting
      width: parent.width
      text: root.agent !== ""
        ? "WELCOME, AGENT " + root.agent
        : "OPERATOR UNRECOGNISED"
      font.family: root.monoFamily
      font.pixelSize: 17
      font.bold: true
      font.letterSpacing: 3
      color: root.agent !== "" ? root.netwatchGlow : Qt.rgba(1, 0.72, 0.28, 1)
    }

    Text {
      visible: root.greeting
      text: root.agent !== ""
        ? "hardware token " + root.token + " · post is yours"
        : (root.token !== ""
           ? "hardware token " + root.token + " not on file"
           : "no pointing device seen")
      font.family: root.monoFamily
      font.pixelSize: 10
      font.letterSpacing: 1
      color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                     root.netwatchInk.b, 0.55)
    }

    Item { width: 1; height: 10 }

    Text {
      visible: root.greeting
      text: "click to continue"
      font.family: root.monoFamily
      font.pixelSize: 9
      font.letterSpacing: 2
      color: Qt.rgba(1, 1, 1, 0.26)
    }
  }
}
