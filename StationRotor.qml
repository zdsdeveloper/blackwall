pragma ComponentBehavior: Bound

import QtQuick

// A rotor: concentric rings of tick marks turning at different rates.
//
// Decorative, and deliberately so. A station carries readouts nobody acts on,
// and the rotor is the clearest of them — it says the post is live at a glance,
// from across the room, without asking to be read.
//
// It does carry one honest signal: `steady`. Turning smoothly means the
// enforcement loop is running; stuttering means it is not. Nobody has to be
// told that to feel it.
Item {
  id: root

  property real scaleUnit: 64
  property bool steady: true
  property real power: 1
  readonly property color inkColor: "#ff2b34"

  implicitWidth: scaleUnit
  implicitHeight: scaleUnit

  // Three rings, alternating direction. Opposed rotation is what stops it
  // reading as one spinning picture and starts it reading as a mechanism.
  Repeater {
    model: [
      { radius: 0.50, ticks: 24, period: 14000, reverse: false, weight: 0.10, alpha: 0.55 },
      { radius: 0.36, ticks: 12, period:  9000, reverse: true,  weight: 0.14, alpha: 0.40 },
      { radius: 0.22, ticks:  6, period:  6000, reverse: false, weight: 0.18, alpha: 0.75 }
    ]

    delegate: Item {
      id: ring
      required property var modelData
      anchors.centerIn: parent
      width: root.scaleUnit
      height: root.scaleUnit
      opacity: root.power * modelData.alpha

      property real spin: 0

      RotationAnimation on spin {
        running: root.power > 0
        from: 0
        to: ring.modelData.reverse ? -360 : 360
        duration: ring.modelData.period
        loops: Animation.Infinite
      }

      // A stalled loop drags the rotor rather than freezing it outright: a
      // dead rotor reads as a broken window, a labouring one reads as a
      // machine in trouble, which is the true thing.
      rotation: root.steady ? spin : spin * 0.12

      Repeater {
        model: ring.modelData.ticks

        delegate: Rectangle {
          id: tick
          required property int index
          readonly property real angle: index * 2 * Math.PI / ring.modelData.ticks
          readonly property real r: root.scaleUnit * ring.modelData.radius

          width: Math.max(1, Math.round(root.scaleUnit * ring.modelData.weight * 0.34))
          height: Math.max(1, Math.round(root.scaleUnit * 0.045))
          radius: height / 2
          color: root.inkColor
          // Every fourth tick is brighter, so the ring has a readable index
          // mark and the eye can see it turn rather than merely shimmer.
          opacity: (index % 4 === 0) ? 1 : 0.45

          x: root.scaleUnit / 2 + Math.cos(angle) * r - width / 2
          y: root.scaleUnit / 2 + Math.sin(angle) * r - height / 2
          // Qualified through the tick's own id: inside a transform the
          // implicit scope is the Rotation, not the item it turns.
          transform: Rotation {
            origin.x: tick.width / 2
            origin.y: tick.height / 2
            angle: tick.index * 360 / ring.modelData.ticks
          }
        }
      }
    }
  }

  // The still centre. Everything turns around it, which is what makes the
  // turning legible.
  Rectangle {
    anchors.centerIn: parent
    width: Math.round(root.scaleUnit * 0.07)
    height: width
    radius: width / 2
    color: root.inkColor
    opacity: 0.9 * root.power
  }
}
