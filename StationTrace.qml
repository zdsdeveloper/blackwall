pragma ComponentBehavior: Bound

import QtQuick

// A pulse travelling the perimeter of whatever it fills.
//
// Purely decorative. It exists because a static border makes a window look like
// a picture of a console, and a moving one makes it look like a circuit with
// something running through it. The cost is one animated real and a handful of
// rectangles.
//
// Position is computed from a single 0..1 progress value rather than a Path,
// because the parametrisation has to survive the window being resized at any
// moment and a Path would need rebuilding each time.
Item {
  id: root

  property real power: 1
  property int period: 5200
  property color inkColor: "#ff2b34"
  // The lit segment, as a fraction of the whole perimeter.
  property real tailFraction: 0.06

  property real progress: 0

  NumberAnimation on progress {
    running: root.power > 0 && root.width > 0 && root.height > 0
    from: 0
    to: 1
    duration: root.period
    loops: Animation.Infinite
  }

  readonly property real perimeter: 2 * (width + height)

  // Where a point sits on the border, given how far round it is. Walked as
  // four runs rather than solved as one curve: the corners have to be exact or
  // the pulse visibly cuts across them.
  function pointAt(t) {
    var d = ((t % 1) + 1) % 1 * root.perimeter
    if (d < root.width) return Qt.point(d, 0)
    d -= root.width
    if (d < root.height) return Qt.point(root.width, d)
    d -= root.height
    if (d < root.width) return Qt.point(root.width - d, root.height)
    d -= root.width
    return Qt.point(0, root.height - d)
  }

  // The tail is drawn as a run of dots rather than a gradient, which reads as
  // charge moving through a trace instead of a light sliding along a tube.
  Repeater {
    model: 14

    delegate: Rectangle {
      id: spark
      required property int index

      readonly property real back: spark.index / 14 * root.tailFraction
      readonly property point at: root.pointAt(root.progress - spark.back)

      width: 2
      height: 2
      radius: 1
      color: root.inkColor
      x: at.x - width / 2
      y: at.y - height / 2
      // Brightest at the head, fading behind it.
      opacity: root.power * (1 - spark.index / 14) * 0.85
    }
  }
}
