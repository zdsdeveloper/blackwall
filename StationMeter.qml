pragma ComponentBehavior: Bound

import QtQuick

// One labelled reading: NAME ·············· VALUE.
//
// The leader dots are the point. A column of these lines up its values on the
// right and fills the space between with something regular, which is what makes
// a stack of readings look like an instrument panel instead of a list. The dots
// drift slowly so the panel is never completely still.
//
// Every value shown through this is a real one the daemon reported. The flash
// on change is there so a number that moves is noticed.
Item {
  id: root

  property real power: 1
  property color inkColor: "#ff2b34"
  property font font
  property string label: ""
  property string value: ""
  // Draws the value in the warning colour. For a reading that is itself bad
  // news, not merely large.
  property bool alert: false
  property real textSize: 10

  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0


  implicitHeight: Math.round(textSize * 1.7)

  property real flash: 0

  onValueChanged: {
    if (root.power > 0) flashAnim.restart()
  }

  NumberAnimation {
    id: flashAnim
    target: root
    property: "flash"
    from: 1
    to: 0
    duration: 900
    easing.type: Easing.OutCubic
  }

  Text {
    id: name
    anchors.verticalCenter: parent.verticalCenter
    x: 0
    text: root.label
    font.family: root.font.family
    font.pixelSize: root.textSize
    font.letterSpacing: 1.5
    color: Qt.rgba(1, 1, 1, 0.40)
    opacity: root.power
  }

  // The leader. One Text of repeated dots, clipped to the gap, shifted by a
  // slow drift -- cheaper than a Repeater of dots and it reads the same.
  Item {
    anchors.verticalCenter: parent.verticalCenter
    x: name.width + 6
    width: Math.max(0, reading.x - x - 6)
    height: root.textSize
    clip: true

    Text {
      id: dots
      x: -root.drift
      anchors.verticalCenter: parent.verticalCenter
      text: "····························································"
      font.family: root.font.family
      font.pixelSize: root.textSize
      color: Qt.rgba(root.inkColor.r, root.inkColor.g, root.inkColor.b, 0.22)
      opacity: root.power
    }
  }

  // One dot pitch per cycle, so the loop is invisible.
  readonly property real drift:
    ((root.clock / 2.6) % 1) * Math.round(root.textSize * 0.6)

  Text {
    id: reading
    anchors.verticalCenter: parent.verticalCenter
    x: root.width - width
    text: root.value
    font.family: root.font.family
    font.pixelSize: root.textSize
    font.bold: true
    font.letterSpacing: 1
    color: root.alert
      ? Qt.rgba(1, 0.72, 0.28, 1)
      : Qt.rgba(1, 0.62 + 0.30 * root.flash, 0.64 + 0.28 * root.flash, 0.92)
    opacity: root.power
  }
}
