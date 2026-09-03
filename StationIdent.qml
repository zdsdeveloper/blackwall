pragma ComponentBehavior: Bound

import QtQuick

// The station's ident strip: a fixed pattern of bars with a head reading
// across it, over and over.
//
// It is the one piece of chrome that belongs to NetWatch rather than to the
// wall, so it behaves like something an agency stamps on its own equipment: a
// mark that is always the same mark, being checked rather than being watched.
// The pattern never changes -- that is the point of an ident -- and the only
// thing that moves is the head reading it and the bars answering as it passes.
//
// Deliberately not a gauge, a scope, or a length of pipe. Those all say
// "something is flowing". This says "this is the post, and it is being read".
Item {
  id: root

  property real power: 1
  property real clock: 0
  property color inkColor: "#8fd8f2"
  // Seconds for the head to cross once, plus the pause at the end of a pass.
  property real sweepSeconds: 3.4
  property real restSeconds: 1.1
  property int seed: 0x4E57   // "NW"

  // Bars are laid out once from a fixed seed: an ident that came out
  // differently every time the window opened would not be an ident.
  property var bars: []

  onWidthChanged: root.rebuild()
  Component.onCompleted: root.rebuild()

  function rand(state) {
    return (state * 1103515245 + 12345) % 2147483648
  }

  function rebuild() {
    if (root.width <= 0) return
    var out = []
    var state = root.seed
    var x = 2
    // Widths and gaps come from a small fixed vocabulary rather than a
    // continuous range, which is what makes it read as a code rather than as
    // a row of random sticks.
    var widths = [1, 1, 2, 1, 3, 2]
    var gaps = [2, 3, 2, 4, 2, 3]
    var heights = [1.0, 0.55, 0.8, 0.4, 1.0, 0.65, 0.9]
    var i = 0
    while (x < root.width - 2) {
      state = root.rand(state)
      var w = widths[(state >> 4) % widths.length]
      var h = heights[(state >> 9) % heights.length]
      if (x + w > root.width - 2) break
      out.push({ x: x, w: w, h: h, i: i })
      x += w + gaps[(state >> 14) % gaps.length]
      i++
    }
    root.bars = out
  }

  // 0..1 across the strip, then off the end and a pause before the next pass.
  readonly property real cycle: root.sweepSeconds + root.restSeconds
  readonly property real head: {
    var t = (root.clock % root.cycle) / root.sweepSeconds
    return t > 1 ? -1 : t     // -1 parks the head off the strip while resting
  }
  readonly property bool reading: root.head >= 0

  // ---- the bars ------------------------------------------------------------

  Repeater {
    model: root.bars

    delegate: Rectangle {
      id: bar
      required property var modelData

      // How close the head is, in pixels, wrapped to nothing while resting.
      readonly property real lit: {
        if (!root.reading) return 0
        var headX = root.head * root.width
        var d = Math.abs(headX - (bar.modelData.x + bar.modelData.w / 2))
        return d < 26 ? 1 - d / 26 : 0
      }

      x: bar.modelData.x
      width: bar.modelData.w
      // Bars stand up from the baseline and lift a little as the head passes.
      height: Math.max(2, root.height * bar.modelData.h * (0.62 + 0.38 * bar.lit))
      y: root.height - height
      color: root.inkColor
      opacity: root.power * (0.26 + 0.74 * bar.lit)
    }
  }

  // ---- the head ------------------------------------------------------------

  Rectangle {
    visible: root.reading && root.power > 0
    x: root.head * root.width
    width: 1
    height: root.height
    color: root.inkColor
    opacity: root.power * 0.9
  }

  // Registration marks at each end, so the strip has a beginning and an end
  // rather than simply running out of room.
  Repeater {
    model: 2

    delegate: Item {
      id: bracket
      required property int index
      readonly property bool atStart: bracket.index === 0

      x: bracket.atStart ? 0 : root.width - 3
      y: 0
      width: 3
      height: root.height

      Rectangle {
        x: bracket.atStart ? 0 : 2
        width: 1
        height: parent.height
        color: root.inkColor
        opacity: root.power * 0.55
      }

      Repeater {
        model: 2

        delegate: Rectangle {
          id: tick
          required property int index
          x: 0
          y: tick.index === 0 ? 0 : bracket.height - 1
          width: 3
          height: 1
          color: root.inkColor
          opacity: root.power * 0.55
        }
      }
    }
  }
}
