pragma ComponentBehavior: Bound

import QtQuick
import "Faces.js" as Faces

// Rogue intelligences coming down the outside of the wall. Click one and it
// goes.
//
// The faces are v1's, straight out of Faces.js — the same apparitions that
// press against the lock while it opens. They belong here for the same reason
// they belong there: they are drawn in the logo's own character vocabulary, a
// halo of ░ falling off to a solid ██ core with the eyes and mouth carved out
// to nothing, so they read as things looking in rather than as clip art.
// GhostFaces.qml uses them as an ambient layer that swells and sinks in place;
// this uses the same pool as something falling that can be hit.
//
// This is a toy and makes no claim to be anything else. Nothing here reads or
// changes any state the daemon owns, and a ghost reaching the bottom costs
// nothing — it simply passes out of the sector. It sits where the conduits
// used to on the grounds that a length of pipe was decoration too, and this is
// better company while you wait for a sweep.
Item {
  id: root

  // A face enters at minus its own height so it comes down into view rather
  // than appearing whole at the top edge. Without clipping that draws it up
  // over the header, across the wordmark.
  clip: true

  property real power: 1
  property real clock: 0
  property color inkColor: "#ff2b34"
  property string monoFamily: "monospace"

  // Two lanes, not three: a face is twenty-six columns wide and three of them
  // abreast in a side column would each be too small to aim at.
  property int lanes: 2
  // Pixels a second. Slow on purpose — the drop is the whole play.
  property real fallRate: 30
  property real spawnEvery: 3.0
  // Kills, for whoever is counting.
  property int purged: 0

  // v1's colour for these, which is a pale bone rather than the wall's red:
  // they are the things on the other side, not the wall itself. v1 draws them
  // at 0.26 as something half-seen; here they have to be aimed at, so they are
  // brighter than that -- but not so bright that the brightest thing on the
  // hero is a toy rather than the wall.
  readonly property color faceColor: "#d9aeb2"
  property real faceOpacity: 0.72
  readonly property real burstSeconds: 0.46

  readonly property real laneWidth: root.width / Math.max(1, root.lanes)

  // Measured at a known size and scaled, the same approach the wall and the
  // wordmark take, so the block is drawn at a real font size instead of being
  // drawn small and blown up.
  TextMetrics {
    id: probe
    font.family: root.monoFamily
    font.pixelSize: 40
    text: Faces.textAt(0).split("\n")[0]
  }

  readonly property real glyphSize: probe.width > 0
    ? Math.max(3, 40 * (root.laneWidth * 0.94 / probe.width))
    : 6
  readonly property real faceHeight: probe.height > 0
    ? probe.height * (root.glyphSize / 40) * Faces.rows()
    : 60

  ListModel { id: swarm }

  // How many are on the column right now. Exposed so the spawn cap and the
  // reaping can be asserted from outside; nothing on the surface reads it.
  readonly property alias count: swarm.count

  // A ListModel rather than an array of records, so hitting one ghost changes
  // that ghost instead of rebuilding every delegate on the column.
  function spawn() {
    if (root.power <= 0 || root.width <= 0 || swarm.count > 8) return
    swarm.append({
      born: root.clock,
      lane: Math.floor(Math.random() * root.lanes),
      face: Math.floor(Math.random() * Faces.count()),
      dying: false,
      diedAt: 0
    })
  }

  function reap() {
    for (var i = swarm.count - 1; i >= 0; i--) {
      var g = swarm.get(i)
      if (g.dying) {
        if (root.clock - g.diedAt > root.burstSeconds) swarm.remove(i)
      } else if ((root.clock - g.born) * root.fallRate
                 > root.height + root.faceHeight) {
        // Out of the sector. No score, no penalty.
        swarm.remove(i)
      }
    }
  }

  Timer {
    interval: Math.max(400, Math.round(root.spawnEvery * 1000))
    repeat: true
    running: root.power > 0 && root.visible
    onTriggered: root.spawn()
  }

  Timer {
    interval: 250
    repeat: true
    running: root.power > 0 && root.visible
    onTriggered: root.reap()
  }

  Repeater {
    model: swarm

    delegate: Item {
      id: ghost

      required property int index
      required property real born
      required property int lane
      required property int face
      required property bool dying
      required property real diedAt

      readonly property real fallen:
        (root.clock - ghost.born) * root.fallRate - root.faceHeight
      // 0 while alive, 0..1 across the burst.
      readonly property real burst: ghost.dying
        ? Math.min(1, (root.clock - ghost.diedAt) / root.burstSeconds)
        : 0

      width: root.laneWidth
      height: root.faceHeight
      x: ghost.lane * root.laneWidth
      y: ghost.fallen
      // Fades in as it comes down out of nothing and out again as it leaves,
      // so nothing pops into being at either edge.
      opacity: root.power
        * root.faceOpacity
        * (1 - ghost.burst)
        * Math.min(1, Math.max(0, ghost.fallen + root.faceHeight) / 30)
        * (ghost.dying
           ? 1
           : Math.min(1, Math.max(0, root.height - ghost.fallen) / 34))

      Text {
        id: body
        anchors.centerIn: parent
        text: Faces.textAt(ghost.face)
        font.family: root.monoFamily
        font.pixelSize: root.glyphSize
        color: root.faceColor
        // Swells as it comes apart.
        scale: 1 + ghost.burst * 0.7
        transformOrigin: Item.Center
        renderType: Text.QtRendering
      }

      // The pieces flying off. Eight is enough to read as a break-up and few
      // enough that a column full of them costs nothing.
      Repeater {
        model: ghost.dying ? 8 : 0

        delegate: Rectangle {
          id: shard
          required property int index
          readonly property real angle: shard.index / 8 * 2 * Math.PI
          readonly property real reach: ghost.burst * (root.faceHeight * 0.55)

          width: 3
          height: 3
          color: root.inkColor
          x: ghost.width / 2 + Math.cos(shard.angle) * shard.reach - 1.5
          y: ghost.height / 2 + Math.sin(shard.angle) * shard.reach - 1.5
          opacity: 1 - ghost.burst
        }
      }

      MouseArea {
        anchors.fill: parent
        enabled: !ghost.dying
        cursorShape: Qt.PointingHandCursor
        onClicked: {
          swarm.setProperty(ghost.index, "diedAt", root.clock)
          swarm.setProperty(ghost.index, "dying", true)
          root.purged += 1
        }
      }
    }
  }

  // The tally, for whoever is counting. Deliberately the quietest thing on the
  // column: it is a toy score, not a reading.
  Text {
    anchors.bottom: parent.bottom
    anchors.horizontalCenter: parent.horizontalCenter
    visible: root.purged > 0
    text: "PURGED " + root.purged
    font.family: root.monoFamily
    font.pixelSize: 9
    font.letterSpacing: 2
    color: Qt.rgba(1, 1, 1, 0.28)
    opacity: root.power
  }
}
