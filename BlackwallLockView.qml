pragma ComponentBehavior: Bound

import QtQuick
import QtMultimedia
import qs.Commons
import "Model.js" as Model

// The face of the Blackwall. Painted onto the ext-session-lock surface, one
// instance per monitor.
//
// The ripple is built from horizontal slices of the same logo: each slice
// clips its own band out of a full copy of the wall, and is displaced
// sideways and re-tinted by a single travelling sine wave. Because every
// slice samples one shared wave, the block art flexes as one surface. Only
// `phase` and `breath` are animated — the per-slice x and color are plain
// bindings off those two, so nothing re-lays-out text per frame.
Item {
  id: root

  property real remainingMs: 0
  property real totalMs: 0
  property bool active: true

  // The reconnection sequence. `releaseProgress` runs 0..1 over
  // Model.RELEASE_MS; every curve below is a pure function of it, so the
  // whole ceremony is driven off one clock and cannot come apart.
  property bool releasing: false
  property real releaseProgress: 0

  readonly property string releasePhaseName: Model.releasePhase(releaseProgress)
  readonly property real glitchBoost: releasing ? Model.glitchBoost(releaseProgress) : 1
  readonly property real rippleBoost: releasing ? Model.rippleBoost(releaseProgress) : 1
  readonly property real bleach: releasing ? Model.bleach(releaseProgress) : 0
  readonly property real facePressure: releasing ? Model.facePressure(releaseProgress) : 0
  readonly property real shatterSpan: releasing ? Model.phaseSpan(releaseProgress, 0.88, 1) : 0

  // Escalating readout. The wall reports what is happening to it, then stops
  // reporting once it is coming apart.
  readonly property string statusWord: {
    if (!releasing) return ""
    if (releasePhaseName === "breach") return "BREACH DETECTED"
    if (releasePhaseName === "press") return "RELEASING"
    if (releasePhaseName === "surge") return "WALL FAILING"
    return ""
  }

  // Hard on/off flicker for the breach line — a smooth fade would read as a
  // notification, and this is an alarm. ~7Hz over the breach phase.
  readonly property real statusFlicker: releasePhaseName === "breach"
    ? (Math.sin(releaseProgress * 220) > 0 ? 1 : 0.12)
    : 1

  // Empty when the sound file is not on disk, which is the whole of the
  // missing-file handling: no source, no player, no error.
  property string soundSource: ""

  // True on exactly one surface. See Service.claimAudio().
  property bool audioLead: false

  readonly property real audioVolume: 0.3

  readonly property string monoFamily: Style.font.family

  // The wall's own breath, read back from the component that owns it. The
  // surfaces around it — the static behind, the countdown under — swell with
  // the logo rather than against it.
  readonly property real breath: wall.breath

  readonly property real elapsedFraction: totalMs > 0
    ? Model.clamp(1 - remainingMs / totalMs, 0, 1)
    : 0

  // Sizing, slice colouring and the ripple drivers all belong to BlackwallWall
  // now — the breach challenge puts up the same wall, and a change to how it
  // moves should not have to be made twice and land in one place.

  // --- surface -------------------------------------------------------------

  Rectangle {
    anchors.fill: parent
    color: "#000000"
  }

  // Digital static, underneath the wall. Declared before the content Column
  // so it paints behind it, and breathing in sync so the background swells
  // with the logo rather than flickering against it.
  GlitchBackground {
    anchors.fill: parent
    running: root.active
    intensity: (0.72 + 0.38 * root.breath) * root.glitchBoost
  }

  // The things on the other side, between the static and the wall — behind
  // the logo, in front of the noise.
  GhostFaces {
    anchors.fill: parent
    active: root.releasing
    pressure: root.facePressure
    fontFamily: root.monoFamily
  }

  // Ambience. Only the lead surface builds a player, and only when the file
  // exists — `source` stays empty otherwise, so a missing mp3 is silence
  // rather than an error on the lock screen.
  Loader {
    active: root.audioLead && root.soundSource !== ""
    sourceComponent: Component {
      MediaPlayer {
        id: ambience
        source: root.soundSource
        loops: MediaPlayer.Infinite
        // Fades with the picture on the shatter so the ambience does not get
        // cut off mid-note when the session hands back.
        audioOutput: AudioOutput { volume: root.audioVolume * (1 - root.shatterSpan) }

        // The surface only exists while the session is locked, so starting
        // here and stopping on destruction ties the sound to the lock exactly.
        Component.onCompleted: ambience.play()
        Component.onDestruction: ambience.stop()

        onErrorOccurred: function(error, errorString) {
          console.warn("blackwall ambience failed:", errorString)
        }
      }
    }
  }

  // Swallows every pointer event and takes the cursor with it. The session
  // lock already denies input to everything else; this stops the cursor from
  // sitting on top of the wall as a visible arrow.
  MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.AllButtons
    hoverEnabled: true
    cursorShape: Qt.BlankCursor
    onWheel: function(wheel) { wheel.accepted = true }
  }

  // Swallows every key. Nothing here maps to an unlock; this only stops
  // keystrokes from reaching anything else on the surface.
  Item {
    anchors.fill: parent
    focus: true
    Keys.onPressed: function(event) { event.accepted = true }
    Keys.onReleased: function(event) { event.accepted = true }
  }

  Column {
    anchors.centerIn: parent
    spacing: Math.round(root.height * 0.045)

    // ---------------------------------------------------------- the wall
    //
    // The same component the breach challenge puts up. The release sequence is
    // handed over as plain numbers rather than understood in there, so a
    // surface that never opens the wall gets the neutral defaults.
    BlackwallWall {
      id: wall
      anchors.horizontalCenter: parent.horizontalCenter
      active: root.active
      monoFamily: root.monoFamily
      availableWidth: root.width
      availableHeight: root.height
      releasing: root.releasing
      releaseProgress: root.releaseProgress
      rippleBoost: root.rippleBoost
      bleach: root.bleach
      shatterSpan: root.shatterSpan
    }

    // ----------------------------------------- the countdown / the readout
    //
    // One slot, two jobs: the clock while the wall holds, the sequence
    // readout while it opens. Sharing the slot keeps the composition from
    // jumping when the timer runs out.
    Item {
      anchors.horizontalCenter: parent.horizontalCenter
      width: Math.max(countdown.implicitWidth, statusLine.implicitWidth)
      height: Math.max(countdown.implicitHeight, statusLine.implicitHeight)
      opacity: 1 - root.shatterSpan

      Text {
        visible: !root.releasing
        anchors.centerIn: parent
        text: countdown.text
        font: countdown.font
        color: "#ff2b34"
        opacity: 0.18 + 0.22 * root.breath
        scale: 1.03
      }

      Text {
        id: countdown
        visible: !root.releasing
        anchors.centerIn: parent
        text: Model.formatRemaining(root.remainingMs)
        font.family: root.monoFamily
        font.pixelSize: Math.max(18, Math.round(root.height * 0.115))
        font.bold: true
        font.letterSpacing: Math.round(root.height * 0.006)
        color: Qt.rgba(1, 0.24 + 0.10 * root.breath, 0.28 + 0.10 * root.breath, 1)
      }

      Text {
        id: statusLine
        visible: root.releasing && text !== ""
        anchors.centerIn: parent
        text: root.statusWord
        font.family: root.monoFamily
        font.pixelSize: Math.max(14, Math.round(root.height * 0.072))
        font.bold: true
        font.letterSpacing: Math.round(root.height * 0.010)
        // Bleaches with the wall, so the words go white-hot alongside it.
        color: Qt.rgba(1, 0.16 + 0.72 * root.bleach, 0.20 + 0.70 * root.bleach, 1)
        opacity: root.statusFlicker
      }
    }

    // ------------------------------------------------------ progress + copy
    Column {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Math.round(root.height * 0.022)
      opacity: 1 - root.shatterSpan

      // Elapsed-time bar while locked.
      Rectangle {
        visible: !root.releasing
        anchors.horizontalCenter: parent.horizontalCenter
        width: Math.round(root.width * 0.34)
        height: Math.max(2, Math.round(root.height * 0.0022))
        color: "#2a0508"

        Rectangle {
          anchors.left: parent.left
          anchors.top: parent.top
          anchors.bottom: parent.bottom
          width: parent.width * root.elapsedFraction
          color: "#ff2b34"
          opacity: 0.55 + 0.35 * root.breath
        }
      }

      // Block meter while opening — same character vocabulary as the wall,
      // so the sequence is built out of the same material as the logo.
      Text {
        visible: root.releasing
        anchors.horizontalCenter: parent.horizontalCenter
        text: Model.progressBlocks(Model.releaseMeter(root.releaseProgress), 34)
        font.family: root.monoFamily
        font.pixelSize: Math.max(8, Math.round(root.height * 0.020))
        color: Qt.rgba(1, 0.17 + 0.70 * root.bleach, 0.21 + 0.68 * root.bleach, 1)
        opacity: 0.9
      }

      Text {
        anchors.horizontalCenter: parent.horizontalCenter
        text: root.releasing ? "RECONNECTION SEQUENCE" : "BLACKWALL ENGAGED  ·  NO OVERRIDE"
        font.family: root.monoFamily
        font.pixelSize: Math.max(10, Math.round(root.height * 0.017))
        font.bold: true
        font.letterSpacing: Math.round(root.height * 0.004)
        color: root.releasing ? Qt.rgba(0.85, 0.25 + 0.5 * root.bleach, 0.28 + 0.5 * root.bleach, 1) : "#8c1219"
        opacity: root.releasing ? 0.85 : 0.55 + 0.45 * root.breath
      }
    }
  }

  // ------------------------------------------------------- the seal
  //
  // The last beat. Everything else has flown apart and faded by now; this is
  // a single white line that opens across the middle of the screen and then
  // shuts to a point — the wall closing behind whatever just came through.
  //
  // It has to be the last child so it paints over the wreckage.
  Item {
    anchors.fill: parent
    visible: root.shatterSpan > 0

    readonly property real opening: Model.phaseSpan(root.releaseProgress, 0.90, 0.965)
    readonly property real shutting: Model.phaseSpan(root.releaseProgress, 0.965, 1.0)

    Rectangle {
      anchors.centerIn: parent
      height: Math.max(2, Math.round(root.height * 0.0035))
      width: parent.width * parent.opening * (1 - parent.shutting)
      color: "#ffffff"
      opacity: 0.55 + 0.45 * parent.opening
    }

    // A dim wash of the same line, wider and softer, so the seal has some
    // bloom instead of looking like a drawn rectangle.
    Rectangle {
      anchors.centerIn: parent
      height: Math.max(6, Math.round(root.height * 0.02))
      width: parent.width * parent.opening * (1 - parent.shutting)
      color: "#ff4d55"
      opacity: 0.18 * (1 - parent.shutting)
    }
  }
}
