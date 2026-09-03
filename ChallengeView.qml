import QtQuick
import QtMultimedia
import Quickshell
import Quickshell.Wayland
import qs.Commons
import "Model.js" as Model

// Rung one of the ladder. The wall was made weaker, and the operator is asked
// to say so in their own words before anything else happens.
//
// Deliberately not a session lock. A challenge is a question; the lock is what
// comes next if the question goes unanswered. Dismissing this window costs
// nothing right now and is not an acknowledgement -- the breach stays standing,
// so the next weakening is the second in the window and lands on the lock.
//
// The token arrives as an argument to the IPC call the daemon makes into this
// session and is handed straight back with the answer. It is never read from
// anywhere on disk: anything this plugin could read there, a process spamming
// the daemon's socket could read too.
PanelWindow {
  id: root

  property bool open: false
  property string reason: ""
  property string phrase: ""
  property string token: ""
  property int armSeconds: 15

  // Empty when no audio file is on disk, which is the whole of the missing-file
  // handling: no source, no player, no error. Same file the lock uses.
  property string soundSource: ""
  readonly property real audioVolume: 0.3

  signal answered(string token)
  signal dismissed()

  property int remaining: armSeconds

  readonly property bool armed: remaining <= 0
  // The rule lives in Model.js so it can be tested without a compositor.
  readonly property bool matches: Model.phraseMatches(field.text, root.phrase)
  readonly property bool ready: armed && matches

  readonly property string monoFamily: Style.font.family

  visible: open

  // Instantiated hidden, so focus has to be taken after the surface maps.
  onOpenChanged: {
    if (root.open) {
      root.remaining = root.armSeconds
      field.text = ""
      Qt.callLater(function () {
        if (!root.open) return
        field.forceActiveFocus()
      })
    }
  }

  anchors { top: true; bottom: true; left: true; right: true }
  color: "transparent"
  exclusionMode: ExclusionMode.Ignore
  WlrLayershell.namespace: "blackwall-challenge"
  WlrLayershell.layer: WlrLayer.Overlay
  WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive

  Timer {
    interval: 1000
    repeat: true
    running: root.open && root.remaining > 0
    onTriggered: root.remaining = Math.max(0, root.remaining - 1)
  }

  // Ambience, built only while the challenge is up and only when the file is
  // there. Tying the loader to `open` starts it with the question and stops it
  // with the answer, the same way the lock ties its player to the surface.
  //
  // Unlike the lock there is no lead to claim: the service is a singleton, so
  // there is exactly one of these no matter how many monitors are attached.
  Loader {
    active: root.open && root.soundSource !== ""
    sourceComponent: Component {
      MediaPlayer {
        id: ambience
        source: root.soundSource
        loops: MediaPlayer.Infinite
        audioOutput: AudioOutput { volume: root.audioVolume }

        Component.onCompleted: ambience.play()
        Component.onDestruction: ambience.stop()

        onErrorOccurred: function (error, errorString) {
          console.warn("blackwall challenge ambience failed:", errorString)
        }
      }
    }
  }

  // Opaque, and the same static the lock wears. A challenge is the wall
  // speaking, not a dialog floating over the desktop -- if the machine behind
  // it stays visible, the moment reads as dismissible, which is the opposite of
  // what this is for. The flat fill underneath is the fallback for a shader
  // that fails to load: a broken background must never be why the wall is not
  // there.
  Rectangle {
    anchors.fill: parent
    color: "#000000"
  }

  GlitchBackground {
    anchors.fill: parent
    running: root.open
    // Breathing with the wall, as it does on the lock, so the static swells
    // with the logo instead of flickering against it. Scaled below the lock's
    // full strength: that surface has only a countdown on it, this one has a
    // question and a field to type into.
    intensity: (0.42 + 0.30 * wall.breath)
  }

  Item {
    anchors.fill: parent
    focus: true

    Keys.onEscapePressed: root.dismissed()

    Column {
      id: content
      anchors.centerIn: parent
      width: Math.min(root.width * 0.72, 900)
      spacing: Math.round(root.height * 0.024)

      // The same wall the lock puts up, from the same component — smaller,
      // because a question and an input have to fit under it.
      BlackwallWall {
        id: wall
        anchors.horizontalCenter: parent.horizontalCenter
        active: root.open
        monoFamily: root.monoFamily
        availableWidth: root.width
        availableHeight: root.height
        heightFraction: 0.20
        widthFraction: 0.52
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "BREACH DETECTED"
        font.family: root.monoFamily
        font.pixelSize: Math.max(22, Math.round(root.height * 0.05))
        font.bold: true
        font.letterSpacing: Math.round(root.height * 0.006)
        color: "#ff2b34"
      }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: root.reason
        font.family: root.monoFamily
        font.pixelSize: Math.max(13, Math.round(root.height * 0.021))
        color: Qt.rgba(1, 0.42, 0.45, 1)
      }

      Item { width: 1; height: Math.round(root.height * 0.02) }

      Text {
        width: parent.width
        horizontalAlignment: Text.AlignHCenter
        text: "TYPE THE PHRASE"
        font.family: root.monoFamily
        font.pixelSize: Math.max(11, Math.round(root.height * 0.015))
        font.letterSpacing: Math.round(root.height * 0.004)
        color: Qt.rgba(1, 1, 1, 0.38)
      }

      Rectangle {
        width: parent.width * 0.8
        x: (parent.width - width) / 2
        height: Math.max(38, Math.round(root.height * 0.06))
        color: "#0d0203"
        border.width: 1
        border.color: root.matches ? "#ff2b34" : Qt.rgba(1, 0.24, 0.28, 0.32)

        TextInput {
          id: field
          anchors.fill: parent
          anchors.margins: Math.round(parent.height * 0.27)
          font.family: root.monoFamily
          font.pixelSize: Math.max(14, Math.round(root.height * 0.023))
          color: "#ff6b70"
          selectionColor: "#ff2b34"
          selectedTextColor: "#000000"
          selectByMouse: true
          clip: true
          onAccepted: if (root.ready) root.answered(root.token)
        }
      }

      Item { width: 1; height: Math.round(root.height * 0.012) }

      Rectangle {
        width: parent.width * 0.42
        x: (parent.width - width) / 2
        height: Math.max(34, Math.round(root.height * 0.054))
        color: root.ready ? "#2a0508" : "transparent"
        border.width: 1
        border.color: root.ready ? "#ff2b34" : Qt.rgba(1, 1, 1, 0.14)

        Text {
          anchors.centerIn: parent
          // The countdown is the friction, and it is shown rather than hidden:
          // a button that is simply dead reads as broken, one that is visibly
          // counting reads as waiting.
          text: root.armed ? "CONFIRM" : ("CONFIRM  " + root.remaining + "s")
          font.family: root.monoFamily
          font.pixelSize: Math.max(12, Math.round(root.height * 0.018))
          font.bold: true
          font.letterSpacing: Math.round(root.height * 0.004)
          color: root.ready ? "#ff2b34" : Qt.rgba(1, 1, 1, 0.26)
        }

        MouseArea {
          anchors.fill: parent
          enabled: root.ready
          cursorShape: root.ready ? Qt.PointingHandCursor : Qt.ArrowCursor
          onClicked: root.answered(root.token)
        }
      }
    }
  }
}
