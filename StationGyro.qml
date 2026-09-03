pragma ComponentBehavior: Bound

import QtQuick

// A containment gyro: rings turning around the wall on different axes, with a
// charge running each one.
//
// The 3D is honest perspective rather than a picture of it. A circle seen
// edge-on is a line, and a ring turning about an axis is a circle whose width
// collapses to nothing and opens again — so each ring is drawn as a real
// circle and squashed by the cosine of its own angle. The charge is a child of
// that same squash, which is what makes it slow at the rim and quick across
// the face without any of it being animated by hand.
//
// It is decorative, with one honest tell: `steady`. Rings turning evenly mean
// the enforcement loop is running. Nobody needs to be told that to feel it.
Item {
  id: root

  property real scaleUnit: 200
  property bool steady: true
  property real power: 1
  property color inkColor: "#ff2b34"

  implicitWidth: scaleUnit
  implicitHeight: scaleUnit

  // Three rings, tilted apart so they read as a cage rather than as one ring
  // drawn three times. The periods are deliberately not multiples of each
  // other: common factors make the whole thing pulse in step, which reads as
  // an animation looping instead of a mechanism running.
  Repeater {
    model: [
      { tilt:   0, period: 11000, radius: 0.50, weight: 1.4, alpha: 0.85, lead: 0.00 },
      { tilt:  62, period:  8300, radius: 0.42, weight: 1.1, alpha: 0.55, lead: 0.33 },
      { tilt: 118, period: 14500, radius: 0.47, weight: 1.1, alpha: 0.40, lead: 0.66 }
    ]

    delegate: Item {
      id: ring
      required property var modelData

      anchors.centerIn: parent
      width: root.scaleUnit * ring.modelData.radius * 2
      height: width
      opacity: root.power * ring.modelData.alpha

      // 0..1 around the ring's own axis.
      property real turn: ring.modelData.lead

      NumberAnimation on turn {
        running: root.power > 0
        from: ring.modelData.lead
        to: ring.modelData.lead + 1
        duration: ring.modelData.period
        loops: Animation.Infinite
      }

      // A stalled loop drags the gyro rather than stopping it. A frozen one
      // reads as a broken window; a labouring one reads as a machine in
      // trouble, which is the true thing.
      readonly property real angle: (root.steady ? ring.turn : ring.turn * 0.10) * 2 * Math.PI
      readonly property real squash: Math.cos(ring.angle)

      // Squash first, then tilt. The order is the whole illusion: squashing a
      // circle and then turning it gives a ring on its own axis, while
      // turning it and then squashing gives an ellipse on the screen's axis
      // -- and a circle's own rotation is invisible, so getting this backwards
      // collapses all three rings onto one shared axis and there is no cage.
      //
      // It has to be one transform list rather than the item's `rotation`
      // property, because `transform` composes OUTSIDE `rotation`: an item
      // with `rotation: 90` and a Scale in `transform` maps its right-edge
      // midpoint to (50,100), where squash-then-tilt puts it at (50,55).
      // Measured under Quickshell rather than assumed.
      transform: [
        Scale {
          origin.x: ring.width / 2
          origin.y: ring.height / 2
          // Never quite zero: a ring exactly edge-on disappears for a frame
          // and the cage blinks.
          xScale: Math.max(0.04, Math.abs(ring.squash))
        },
        Rotation {
          origin.x: ring.width / 2
          origin.y: ring.height / 2
          angle: ring.modelData.tilt
        }
      ]

      // The ring itself.
      Rectangle {
        anchors.fill: parent
        radius: width / 2
        color: "transparent"
        border.width: ring.modelData.weight
        border.color: root.inkColor
        // Dimmer when edge-on, so the far side of the cage sits behind the
        // near side instead of competing with it.
        opacity: 0.35 + 0.65 * Math.abs(ring.squash)
      }

      // The charge. Sits on the ring and inherits its squash, so it slows at
      // the rim and crosses the face quickly — the whole illusion, for free.
      Rectangle {
        id: charge
        readonly property real t: ring.turn * 2 * Math.PI * 1.7
        width: Math.max(3, root.scaleUnit * 0.022)
        height: width
        radius: width / 2
        color: root.inkColor
        x: ring.width / 2 + Math.cos(charge.t) * ring.width / 2 - width / 2
        y: ring.height / 2 + Math.sin(charge.t) * ring.height / 2 - height / 2
        // x is the squashed axis, so x is the axis that carries depth: the
        // charge is brightest on the near side and faint going round the
        // back. Keying this to sin would have brightened it at the top of the
        // ellipse, which is a height, not a distance.
        opacity: 0.25 + 0.75 * (0.5 + 0.5 * Math.cos(charge.t))
      }

      // Its wake, three dots back along the ring.
      Repeater {
        model: 3

        delegate: Rectangle {
          id: wake
          required property int index
          readonly property real t: ring.turn * 2 * Math.PI * 1.7 - (wake.index + 1) * 0.16
          width: Math.max(2, root.scaleUnit * 0.014)
          height: width
          radius: width / 2
          color: root.inkColor
          x: ring.width / 2 + Math.cos(wake.t) * ring.width / 2 - width / 2
          y: ring.height / 2 + Math.sin(wake.t) * ring.height / 2 - height / 2
          opacity: (0.40 - wake.index * 0.10) * (0.5 + 0.5 * Math.cos(wake.t))
        }
      }
    }
  }
}
