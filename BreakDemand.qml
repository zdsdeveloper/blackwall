pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
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

  // A dry run: the window looks and behaves exactly as it will in earnest --
  // same grace, same countdown, same fact that every exit is a choice -- but
  // the caller discards what is chosen and nothing is closed or locked.
  //
  // Marked on its face, because a preview you cannot tell apart from the real
  // thing teaches you the wrong thing about the real thing.
  property bool preview: false
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

  // One clock for the whole surface, thirty steps a second, the same way the
  // station does it. Everything that moves here is a function of it; nothing
  // runs an animation of its own.
  //
  // It only ticks while the demand is up, which is at most a minute and a
  // half, so this never costs anything when the window is not there.
  property real clock: 0
  property double clockOrigin: 0

  Timer {
    interval: 33
    repeat: true
    running: root.demanding
    onTriggered: root.clock = (Date.now() - root.clockOrigin) / 1000
  }

  onDemandingChanged: {
    if (!root.demanding) return
    root.answered = false
    root.remaining = root.graceSeconds
    root.clockOrigin = Date.now()
    root.clock = 0
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

  // A layer surface, not a window.
  //
  // The first version was a FloatingWindow, and Hyprland tiled it like any
  // other toplevel: a 560x300 demand arrived as a full-height pane wedged
  // beside the browser. Worse than untidy -- a demand that can be tiled can be
  // moved behind something, resized to nothing, or simply worked around.
  //
  // On the overlay layer it is above everything, cannot be tiled, and takes
  // the keyboard. The same choice ChallengeView makes, for the same reason.
  PanelWindow {
    id: win
    visible: root.demanding
    color: "transparent"

    anchors { top: true; bottom: true; left: true; right: true }

    WlrLayershell.namespace: "blackwall-break"
    WlrLayershell.layer: WlrLayer.Overlay
    // Exclusive in earnest, so it cannot be typed past. A preview only takes
    // focus when clicked -- being unable to reach anything else for ninety
    // seconds is a fair thing to demand of someone at hour three and a poor
    // thing to spring on someone who asked to see what it looks like.
    WlrLayershell.keyboardFocus: root.preview
      ? WlrKeyboardFocus.OnDemand
      : WlrKeyboardFocus.Exclusive

    // The ground behind the card. Dim rather than opaque: what you were doing
    // is still visible behind it, which is the point being made.
    Rectangle {
      anchors.fill: parent
      color: "#04070a"
      opacity: 0.86
    }

    // The field, at a fraction of the station's. This is a demand, not a
    // spectacle: it should read as a surface that is alive rather than as
    // something happening. Coarse and slow, and barely there at all.
    GlitchBackground {
      anchors.fill: parent
      running: root.demanding
      externalClock: root.clock
      intensity: 0.30
      grainScale: 0.55
      stepRate: 12
      artifacts: 0
      opacity: 0.5
    }

    StationFrame {
      anchors.centerIn: parent
      width: Math.min(660, parent.width - 80)
      height: card.implicitHeight + 78
      title: "NETWATCH"
      annotation: root.preview ? "PREVIEW" : "STAND DOWN"
      inkColor: root.netwatchInk
      paperColor: "#04070a"
      font.family: root.monoFamily
      clock: root.clock
      padding: 26

      Column {
        id: card
        anchors.centerIn: parent
        width: parent.width
        spacing: 10

        // The mark itself, not the word set in a bold font. Front and
        // centre, because this is the post speaking and it should look like
        // it -- and it carries its own slow charge down the rows, which is
        // most of the movement on this surface.
        StationWordmark {
          anchors.horizontalCenter: parent.horizontalCenter
          // Wide, and given enough height that the width is what limits it --
          // otherwise the block is sized by height, comes out narrower than
          // its box, and sits off to one side of it.
          width: parent.width
          height: 96
          centred: true
          monoFamily: root.monoFamily
          clock: root.clock
          topColor: root.netwatchGlow
          footColor: root.netwatchInk
        }

        Item { width: 1; height: 4 }

        // A rule that fills in rather than being drawn. Once, on arrival.
        Rectangle {
          anchors.horizontalCenter: parent.horizontalCenter
          width: parent.width * Math.min(1, root.clock / 0.7)
          height: 1
          color: Qt.rgba(root.netwatchInk.r, root.netwatchInk.g,
                         root.netwatchInk.b, 0.25)
        }

        Item { width: 1; height: 6 }

        Rectangle {
          visible: root.preview
          width: parent.width
          height: 22
          color: Qt.rgba(root.warnColor.r, root.warnColor.g, root.warnColor.b, 0.14)
          border.width: 1
          border.color: Qt.rgba(root.warnColor.r, root.warnColor.g, root.warnColor.b, 0.45)

          Text {
            anchors.centerIn: parent
            text: "PREVIEW  ·  nothing will be closed or locked"
            font.family: root.monoFamily
            font.pixelSize: 10
            font.letterSpacing: 2
            color: root.warnColor
          }
        }

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
            var body = "You have been at this machine for " + span
                     + " without a break. The wall goes up either way — "
                     + "the only thing left to choose is for how long."
            return root.preview
              ? body + "\n\nIn a preview, it does not."
              : body
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
          // Steady until the last quarter minute, then a slow breath. Not a
          // flash: the point is that time is passing, not that you are being
          // shouted at.
          color: root.remaining <= 15 ? root.warnColor : Qt.rgba(1, 1, 1, 0.34)
          opacity: root.remaining <= 15
            ? 0.65 + 0.35 * (0.5 - 0.5 * Math.cos(root.clock * 3.4))
            : 1
        }
      }
    }
  }
}
