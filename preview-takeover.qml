import QtQuick
import Quickshell
import QtMultimedia

// The lock's opening sequence, on a loop, in an ordinary window.
//
// This sits in the plugin root rather than in tools/ because Quickshell takes
// the entry file's directory as the config root and refuses to load types from
// outside it -- run from tools/, the plugin's own components are "outside the
// config folder" and nothing resolves. In the root they resolve implicitly,
// with no import at all.
//
// Tuning a two-and-a-half second sequence by engaging a real Blackwall means
// locking yourself out for thirty seconds to watch it once. This runs the same
// TakeoverView, the same shader and the same sting over a real capture of the
// desktop, as many times as you like, and closes when you close it.
ShellRoot {
  FloatingWindow {
    id: win
    title: "Blackwall — takeover preview"
    implicitWidth: 1100
    implicitHeight: 620
    color: "#050102"
    visible: true

    // Closing the window has to end the process, not just hide the surface.
    // Without this the preview kept running headless with the sting still
    // looping, and the only way to stop it was to find the pid.
    onVisibleChanged: if (!visible) Qt.quit()

    // Stands in for the lock surface underneath: the tear writes alpha zero
    // inside itself, so this is what shows through the hole.
    Rectangle {
      anchors.fill: parent
      color: "#050102"

      GlitchBackground {
        anchors.fill: parent
        running: true
        intensity: 0.7
      }

      BlackwallWall {
        anchors.centerIn: parent
        active: true
        monoFamily: "monospace"
        availableWidth: parent.width
        availableHeight: parent.height
        heightFraction: 0.42
        widthFraction: 0.72
      }
    }

    // The ambience under it, as the lock plays it: started first and left
    // running, so what you hear is the sting landing on top of it and the
    // handoff between the two -- which is the part a preview of the tear alone
    // could not show.
    MediaPlayer {
      id: ambience
      source: Qt.resolvedUrl("audio/ambience.mp3")
      loops: MediaPlayer.Infinite
      audioOutput: AudioOutput { volume: 0.3 }
      Component.onCompleted: play()
    }

    TakeoverView {
      id: tk
      anchors.fill: parent
      source: Qt.resolvedUrl("file://" + Quickshell.env("BW_PREVIEW_SHOT"))
      audioLead: true
      onFinished: again.restart()
      Component.onCompleted: tk.begin()
    }

    Timer {
      id: again
      interval: 1400        // a beat to see the wall before it goes again
      repeat: false
      onTriggered: tk.begin()
    }

    Text {
      anchors.bottom: parent.bottom
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottomMargin: 10
      text: "takeover looping over the ambience · close the window to stop"
      font.family: "monospace"
      font.pixelSize: 10
      color: Qt.rgba(1, 1, 1, 0.30)
    }
  }
}
