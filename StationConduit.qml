pragma ComponentBehavior: Bound

import QtQuick

// Conduit: parallel pipes with material moving through them.
//
// This replaces a board of traces that wandered. The trouble with the traces
// was that they were generated — every jog was a decision nothing justified,
// so the eye read them as noise dressed up as engineering. Pipes have no such
// problem. They are straight, evenly spaced, coupled at a fixed pitch, and
// everything in them moves the same way at the same speed. The regularity is
// the point: a thing that is obviously built reads as built.
//
// Each lane is a channel drawn as two walls with couplings across it, and the
// charge inside is a run of evenly spaced packets. The only variation is a
// small phase stagger between lanes, so the run reads as a system with
// something flowing rather than a single object sliding sideways.
Item {
  id: root

  property real power: 1
  property color inkColor: "#ff2b34"

  // Seconds, handed down from the station's one clock.
  property real clock: 0

  // "across" for a wide panel, "down" for a tall strip.
  property string flow: "across"
  property int lanes: 4
  property real speed: 1.0

  // Pipe geometry. Fixed distances rather than fractions of the panel, so a
  // narrow strip and a wide one are visibly the same plumbing at the same
  // scale instead of one being a stretched copy of the other.
  property real bore: 7          // inside width of a pipe
  property real couplingPitch: 26
  property real packetSpacing: 74
  property real packetLength: 18
  property real travelRate: 42   // pixels a second at speed 1

  readonly property bool across: root.flow === "across"
  readonly property real runLength: root.across ? root.width : root.height
  readonly property real span: root.across ? root.height : root.width
  readonly property real laneGap: root.span / (root.lanes + 1)

  Repeater {
    model: root.lanes

    delegate: Item {
      id: lane
      required property int index

      // The lane's centre line, across the panel.
      readonly property real centre: root.laneGap * (lane.index + 1)

      x: root.across ? 0 : lane.centre - root.bore / 2
      y: root.across ? lane.centre - root.bore / 2 : 0
      width: root.across ? root.width : root.bore
      height: root.across ? root.bore : root.height
      opacity: root.power

      // ---- the walls -------------------------------------------------------
      //
      // Two hairlines with the bore between them. One line would be a wire;
      // two make it a channel with an inside, which is what lets the packets
      // read as being carried rather than drawn on top.

      Repeater {
        model: 2

        delegate: Rectangle {
          id: wall
          required property int index

          x: root.across ? 0 : (wall.index === 0 ? 0 : root.bore - 1)
          y: root.across ? (wall.index === 0 ? 0 : root.bore - 1) : 0
          width: root.across ? lane.width : 1
          height: root.across ? 1 : lane.height
          color: root.inkColor
          opacity: 0.55
        }
      }

      // A trace of fill between the walls, so the channel has an inside even
      // where nothing is passing through it.
      Rectangle {
        anchors.fill: parent
        color: root.inkColor
        opacity: 0.055
      }

      // ---- the couplings ---------------------------------------------------
      //
      // Every pipe is coupled at the same pitch, and the pitch is the same in
      // every lane. This is most of what makes the run look manufactured.

      Repeater {
        model: Math.max(0, Math.floor(root.runLength / root.couplingPitch))

        delegate: Rectangle {
          id: coupling
          required property int index

          readonly property real at: (coupling.index + 1) * root.couplingPitch

          x: root.across ? coupling.at : -2
          y: root.across ? -2 : coupling.at
          width: root.across ? 1 : root.bore + 4
          height: root.across ? root.bore + 4 : 1
          color: root.inkColor
          opacity: 0.42
        }
      }

      // ---- what is in the pipe --------------------------------------------

      readonly property int packetCount:
        Math.max(1, Math.ceil(root.runLength / root.packetSpacing) + 1)

      // Lanes are staggered by an even fraction of the spacing, so the run has
      // a rhythm without any lane being different from the others.
      readonly property real stagger:
        root.packetSpacing * (lane.index / Math.max(1, root.lanes))

      Repeater {
        model: lane.packetCount

        delegate: Rectangle {
          id: packet
          required property int index

          // Constant speed, evenly spaced, wrapping one packet-spacing beyond
          // each end so nothing appears or vanishes inside the panel.
          readonly property real cycle: root.runLength + root.packetSpacing
          readonly property real at: {
            var p = (root.clock * root.travelRate * root.speed
                     + packet.index * root.packetSpacing
                     + lane.stagger) % packet.cycle
            return p - root.packetLength
          }

          x: root.across ? packet.at : 1
          y: root.across ? 1 : packet.at
          width: root.across ? root.packetLength : root.bore - 2
          height: root.across ? root.bore - 2 : root.packetLength
          color: root.inkColor
          // Dimmed as it enters and leaves, so the ends of the run do not
          // flicker as packets cross the boundary.
          opacity: 0.75 * Math.min(1,
            Math.min(packet.at + root.packetLength, root.runLength - packet.at) / 24)
        }
      }
    }
  }
}
