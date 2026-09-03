pragma ComponentBehavior: Bound

import QtQuick

// A board of traces with charge running through them.
//
// Each trace is a staircase walked from one edge to the other, cut into
// segments, and the segments light in the order they were laid down — so what
// you see is a charge finding its way across the board rather than a row of
// things blinking. The pads at the corners flash as it arrives.
//
// The layout is generated once from a fixed seed. It has to be stable, because
// a board that redraws itself differently every time the window opens reads as
// noise, and a real board is the same board every time you look at it.
Item {
  id: root

  property real power: 1
  property color inkColor: "#ff2b34"
  // How many charges are crossing at once, spaced evenly along the run.
  property int traces: 5
  property real speed: 1.0
  // "down" for a tall strip, "across" for a wide one.
  property string flow: "down"
  property int seed: 1337
  // Seconds, handed down from the station's one clock. Everything on this
  // surface derives its motion from it instead of running an animation of its
  // own -- see the note on the clock in BlackwallPanel.qml.
  property real clock: 0


  // Generated geometry. Each entry is one rectangle plus its position in the
  // order the trace is walked.
  property var segments: []
  property var pads: []
  property int steps: 1

  onWidthChanged: root.rebuild()
  onHeightChanged: root.rebuild()
  onTracesChanged: root.rebuild()
  onFlowChanged: root.rebuild()
  Component.onCompleted: root.rebuild()

  // A tiny deterministic generator. Math.random would give a different board
  // on every open, which is the one thing this must not do.
  function rand(state) {
    // Numerical Recipes LCG, taken mod 2^32 by the multiply-and-floor.
    return (state * 1664525 + 1013904223) % 4294967296
  }

  function rebuild() {
    if (root.width <= 0 || root.height <= 0) return

    var down = root.flow === "down"
    var along = down ? root.height : root.width   // the direction of travel
    var across = down ? root.width : root.height  // the direction it jogs in

    var segs = []
    var padList = []
    var state = root.seed
    var order = 0

    var lanes = Math.max(1, root.traces)
    var laneGap = across / (lanes + 1)

    for (var i = 0; i < lanes; i++) {
      var pos = laneGap * (i + 1)      // position across
      var travelled = 0                 // position along
      // Each trace takes a different number of hops so they do not all turn
      // at the same heights, which is what would make it read as a grid.
      state = root.rand(state)
      var hops = 3 + (state % 3)
      var hopLength = along / hops

      for (var h = 0; h < hops; h++) {
        var runTo = Math.min(along, travelled + hopLength)

        // The straight run.
        segs.push(down
          ? { x: pos, y: travelled, w: 1, h: runTo - travelled, order: order }
          : { x: travelled, y: pos, w: runTo - travelled, h: 1, order: order })
        order++
        travelled = runTo
        if (travelled >= along) break

        // The jog sideways, alternating direction and shrinking so traces
        // stay inside the board.
        state = root.rand(state)
        var reach = laneGap * 0.55 * (((state >> 8) % 100) / 100 + 0.35)
        var dir = ((state >> 16) % 2) === 0 ? 1 : -1
        var target = pos + dir * reach
        if (target < 4 || target > across - 4) target = pos - dir * reach
        if (target < 4 || target > across - 4) continue

        var lo = Math.min(pos, target)
        var span = Math.abs(target - pos)
        segs.push(down
          ? { x: lo, y: travelled, w: span, h: 1, order: order }
          : { x: travelled, y: lo, w: 1, h: span, order: order })
        order++

        padList.push(down ? { x: target, y: travelled, order: order }
                          : { x: travelled, y: target, order: order })
        pos = target
      }
    }

    root.steps = Math.max(1, order)
    root.segments = segs
    root.pads = padList
  }

  // ---- the charge ----------------------------------------------------------

  readonly property real cycleSeconds: Math.max(1.2, 9.0 / Math.max(0.05, root.speed))
  readonly property real phase: (root.clock / root.cycleSeconds) % 1

  // The clock the board is actually read off, quantised.
  //
  // Every segment and pad binds to this, so a board is a hundred-odd bindings
  // that re-run whenever it changes. Letting that happen every frame costs
  // real CPU for motion nobody can see: the charge crosses in nine seconds,
  // so four steps per segment is already smoother than the eye needs. A
  // binding that produces the same value emits no change, which is what makes
  // this cheap rather than merely coarse.
  //
  // It also happens to look more like a board this way. Charge on a real one
  // arrives at a pad or it does not.
  readonly property int ticks: Math.max(8, root.steps * 4)
  readonly property real litPhase: Math.round(root.phase * root.ticks) / root.ticks

  // How lit a thing at `order` is right now: a bright head with a tail behind
  // it, wrapping around the end of the run.
  function litAt(order) {
    var d = root.litPhase - (order / root.steps)
    if (d < 0) d += 1
    var tail = 0.22
    return d < tail ? (1 - d / tail) : 0
  }

  // ---- the board -----------------------------------------------------------

  Repeater {
    model: root.segments

    delegate: Rectangle {
      id: seg
      required property var modelData

      x: seg.modelData.x
      y: seg.modelData.y
      width: Math.max(1, seg.modelData.w)
      height: Math.max(1, seg.modelData.h)
      color: root.inkColor
      // A dim trace that is always there, plus the charge on top of it. The
      // board should look like a board when nothing is flowing.
      opacity: root.power * (0.10 + 0.80 * root.litAt(seg.modelData.order))
    }
  }

  Repeater {
    model: root.pads

    delegate: Rectangle {
      id: pad
      required property var modelData

      readonly property real lit: root.litAt(pad.modelData.order)

      width: 3 + 3 * pad.lit
      height: width
      radius: width / 2
      x: pad.modelData.x - width / 2
      y: pad.modelData.y - height / 2
      color: root.inkColor
      opacity: root.power * (0.18 + 0.82 * pad.lit)
    }
  }
}
