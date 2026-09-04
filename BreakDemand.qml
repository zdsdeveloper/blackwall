pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import "Model.js" as Model

// The break, being taken rather than offered.
//
// The first version of this was a notification suggesting a break, and that
// was the wrong shape: a thing you can wave away is a thing you wave away at
// hour four, which is exactly when it mattered. The only choice here is how
// long, and every way out of the window is a way of choosing.
//
// Closing it picks the shortest. Ignoring it picks the shortest when the grace
// runs out. There is no cancel, because a cancel is the whole feature undone.
//
// NetWatch's colours rather than the wall's: this is the post telling you to
// stand down, not the Blackwall coming up. The wall arrives immediately after,
// and it looks like itself.
Item {
  id: root

  property bool demanding: false
  property int activeMinutes: 0
  property int graceSeconds: 90
  property string monoFamily: "monospace"

  // Emitted exactly once per demand, with the minutes chosen.
  signal chosen(int minutes)

  readonly property color netwatchInk: "#8fd8f2"
  readonly property color netwatchGlow: "#eaf7ff"
  readonly property color warnColor: "#ffb84a"

  property int remaining: 0
  property bool answered: false

  onDemandingChanged: {
    if (!root.demanding) return
    root.answered = false
    root.remaining = root.graceSeconds
    grace.restart()
  }

  function choose(minutes) {
    if (root.answered) return
    root.answered = true
    grace.stop()
    root.demanding = false
    root.chosen(Math.round(minutes))
  }

  Timer {
    id: grace
    interval: 1000
    repeat: true
    running: root.demanding && !root.answered
    onTriggered: {
      root.remaining -= 1
      // Out of time. The shortest break is the default, not no break.
      if (root.remaining <= 0) root.choose(Model.BREAK_CHOICES[0])
    }
  }

  FloatingWindow {
    id: win
    visible: root.demanding
    implicitWidth: 560
    implicitHeight: 300
    title: "NetWatch — Stand Down"
    color: "#04070a"

    // Closing the window is choosing the shortest, not escaping.
    onVisibleChanged: if (!visible && root.demanding) root.choose(Model.BREAK_CHOICES[0])

    Item {
      anchors.fill: parent
      anchors.margins: 22

      Rectangle {
        anchors.fill: parent
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                              root.netwatchInk.b, 0.30)
      }

      Column {
        anchors.centerIn: parent
        width: parent.width - 40
        spacing: 10

        Text {
          text: "NETWATCH  ──  STAND DOWN"
          font.family: root.monoFamily
          font.pixelSize: 12
          font.bold: true
          font.letterSpacing: 4
          color: root.netwatchInk
        }

        Rectangle {
          width: parent.width
          height: 1
          color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                         root.netwatchInk.b, 0.25)
        }

        Item { width: 1; height: 6 }

        Text {
          text: "TIME TO TAKE A BREAK"
          font.family: root.monoFamily
          font.pixelSize: 22
          font.bold: true
          font.letterSpacing: 3
          color: root.netwatchGlow
        }

        Text {
          width: parent.width
          wrapMode: Text.WordWrap
          text: {
            var h = Math.floor(root.activeMinutes / 60)
            var m = root.activeMinutes % 60
            var span = h > 0
              ? (h + (h === 1 ? " hour " : " hours ") + m + " min")
              : (m + " min")
            return "You have been at this machine for " + span
                 + " without a break. The wall goes up either way — "
                 + "the only thing left to choose is for how long."
          }
          font.family: root.monoFamily
          font.pixelSize: 11
          lineHeight: 1.35
          color: Qt.rgba(1, 1, 1, 0.62)
        }

        Item { width: 1; height: 8 }

        Row {
          spacing: 10

          Repeater {
            model: Model.BREAK_CHOICES

            delegate: Rectangle {
              id: choice
              required property var modelData

              width: 96
              height: 42
              color: hover.hovered
                ? Qt.rgba(root.netwatchInk.r, root.netwatchInk.g, root.netwatchInk.b, 0.16)
                : "transparent"
              border.width: 1
              border.color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                                    root.netwatchInk.b, hover.hovered ? 0.85 : 0.40)

              HoverHandler { id: hover }

              Text {
                anchors.centerIn: parent
                text: choice.modelData + " MIN"
                font.family: root.monoFamily
                font.pixelSize: 12
                font.bold: true
                font.letterSpacing: 1.5
                color: root.netwatchGlow
              }

              MouseArea {
                anchors.fill: parent
                cursorShape: Qt.PointingHandCursor
                onClicked: root.choose(choice.modelData)
              }
            }
          }

          // Longer, if they want it. There is no shorter.
          Rectangle {
            width: 120
            height: 42
            color: "#070c11"
            border.width: 1
            border.color: custom.activeFocus
              ? root.netwatchInk
              : Qt.rgba(root.netwatchInk.r, root.netwatchInk.g, root.netwatchInk.b, 0.30)

            TextInput {
              id: custom
              anchors.fill: parent
              anchors.margins: 10
              font.family: root.monoFamily
              font.pixelSize: 12
              color: root.netwatchGlow
              selectByMouse: true
              validator: IntValidator { bottom: 1; top: 720 }
              onAccepted: {
                var n = parseInt(custom.text, 10)
                if (isFinite(n) && n > 0) root.choose(n)
              }
            }

            Text {
              anchors.centerIn: parent
              visible: custom.text === "" && !custom.activeFocus
              text: "CUSTOM ⏎"
              font.family: root.monoFamily
              font.pixelSize: 10
              font.letterSpacing: 1.5
              color: Qt.rgba(1, 1, 1, 0.30)
            }
          }
        }

        Item { width: 1; height: 4 }

        Text {
          text: "no answer in " + root.remaining + "s → "
                + Model.BREAK_CHOICES[0] + " minutes"
          font.family: root.monoFamily
          font.pixelSize: 10
          font.letterSpacing: 1
          color: root.remaining <= 15 ? root.warnColor : Qt.rgba(1, 1, 1, 0.34)
        }
      }
    }
  }
}
