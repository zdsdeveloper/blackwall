import QtQuick

// A status lamp on the station panel.
//
// Four states, because three is not enough: a protection can be in place, gone,
// or unreadable, and the third must not look like the second. A filesystem that
// cannot report the ledger's append-only flag is not the same as a ledger that
// lost it, and a lamp that showed them alike would have the operator chasing a
// breach that never happened.
Item {
  id: root

  // "lit" — the protection is in place
  // "dark" — it is not, and that is a finding
  // "unknown" — could not be determined; not a finding
  // "idle" — nothing to report yet, e.g. before the first poll
  property string lamp: "idle"
  property string label: ""
  property string monoFamily: "monospace"
  property real scaleUnit: 12

  // Rises while the station boots so lamps come up in sequence rather than all
  // at once. 0 keeps the lamp dark whatever its state says.
  property real power: 1

  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0


  readonly property color litColor: "#ff2b34"
  readonly property color darkColor: Qt.rgba(1, 1, 1, 0.16)
  readonly property color unknownColor: Qt.rgba(1, 0.72, 0.28, 0.75)

  readonly property color bodyColor: {
    if (root.lamp === "lit") return root.litColor
    if (root.lamp === "unknown") return root.unknownColor
    if (root.lamp === "dark") return Qt.rgba(1, 0.24, 0.28, 0.30)
    return root.darkColor
  }

  // The lamp breathes when lit and stutters when unknown. A dark lamp is
  // perfectly still, which is what makes it read as a dead circuit rather than
  // an idle one.
  // The breath and the stutter, as functions of the clock rather than as two
  // competing animations. The shapes are the ones they replace: a slow
  // sinusoidal swell for a lit lamp, and a quick rise with a long fall and a
  // longer wait for one that cannot be read.
  readonly property real pulse: {
    if (root.power <= 0) return 0
    if (root.lamp === "lit")
      return 0.5 - 0.5 * Math.cos(2 * Math.PI * (root.clock / 4.7))
    if (root.lamp === "unknown") {
      var u = root.clock % 2.62
      if (u < 0.32) return 0.2 + 0.7 * (u / 0.32)
      if (u < 1.22) return 0.9 - 0.7 * ((u - 0.32) / 0.90)
      return 0.2
    }
    return 0
  }

  implicitHeight: Math.max(scaleUnit, labelText.implicitHeight)
  implicitWidth: dot.width + labelText.implicitWidth + scaleUnit * 0.6

  // The halo. No blur is available, so a larger, dimmer copy stands in — the
  // same trick the wall uses for its bloom.
  Rectangle {
    anchors.centerIn: dot
    width: dot.width * (2.4 + 0.8 * root.pulse)
    height: width
    radius: width / 2
    color: root.bodyColor
    opacity: root.lamp === "lit" || root.lamp === "unknown"
      ? (0.10 + 0.16 * root.pulse) * root.power
      : 0
  }

  Rectangle {
    id: dot
    anchors.verticalCenter: parent.verticalCenter
    width: Math.round(root.scaleUnit * 0.52)
    height: width
    radius: width / 2
    color: root.bodyColor
    opacity: (root.lamp === "lit" ? 0.72 + 0.28 * root.pulse : 1) * root.power

    // The unlit ring stays visible on a dark lamp, so the socket is there even
    // when nothing is in it.
    border.width: 1
    border.color: Qt.rgba(1, 0.24, 0.28, 0.22 * root.power)
  }

  Text {
    id: labelText
    anchors.verticalCenter: parent.verticalCenter
    anchors.left: dot.right
    anchors.leftMargin: Math.round(root.scaleUnit * 0.6)
    text: root.label
    font.family: root.monoFamily
    font.pixelSize: Math.round(root.scaleUnit * 0.86)
    font.letterSpacing: 1
    color: root.lamp === "lit"
      ? Qt.rgba(1, 0.42, 0.45, 1)
      : Qt.rgba(1, 1, 1, root.lamp === "dark" ? 0.42 : 0.30)
    opacity: root.power
  }
}
